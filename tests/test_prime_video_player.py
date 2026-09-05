"""Host-only tests for discovery, file I/O, format, clock, and state logic."""

import io
import struct
import sys
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
host_hpprime = types.SimpleNamespace(
    ticks=lambda: 0,
    keyboard=lambda: 0,
    fillrect=lambda *args: None,
    textout=lambda *args: None,
)
with patch.dict(sys.modules, {
        "ustruct": struct,
        "uio": types.SimpleNamespace(),
        "hpprime": host_hpprime}):
    import prime_native as native_runtime
    import prime_video_profile as profile
    import prime_video_runtime as runtime
    from mjpg_container import (MjpgError, MjpgReader, parse_bytes,
                                validate_baseline_jpeg)
    from prime_video_clock import FrameClock
    from prime_video_files import (NativeDirectoryScanner, collect_files,
                                   decode_utf16le_z, utf16le_z)
    from prime_video_io import NativeFile
    from prime_video_model import (DebugMode, FileEntry, PlaybackMode,
                                   PlayerModel, PlayerState)
    from prime_video_m1v import (FRAME_RATES, M1VFormatError, M1VInfo,
                                bootstrap_prefix, i_picture_offsets,
                                parse_sequence_header, safe_seek_anchors,
                                scale_geometry)
    from prime_video_positions import decode_positions, encode_positions
    from prime_video_settings import (SettingsStore, decode_settings,
                                      default_settings, encode_settings)
sys.path.pop(0)


class MemoryDevice:
    SCRATCH = 0x31000000
    STRING = 0x31001000
    HANDLE = 0x302D3000

    def __init__(self, records=(), file_data=b""):
        self.segments = [(self.SCRATCH, bytearray(4096))]
        self.records = list(records)
        self.record_index = 0
        self.closed_find = 0
        self.close_result = 0
        self.file_data = bytes(file_data)
        self.file_position = 0
        self.closed_file = 0

    def _segment(self, address, size):
        for base, data in self.segments:
            if base <= address and address + size <= base + len(data):
                return data, address - base
        raise AssertionError("unmapped 0x%x + %d" % (address, size))

    def store(self, address, data):
        try:
            segment, offset = self._segment(address, len(data))
        except AssertionError:
            self.segments.append((address, bytearray(data)))
        else:
            segment[offset:offset + len(data)] = data

    def read(self, address, size):
        segment, offset = self._segment(address, size)
        return bytes(segment[offset:offset + size])

    def _publish_record(self, context):
        name, size, attributes = self.records[self.record_index]
        encoded = bytes(utf16le_z(name))
        encoded += b"\0" * (512 - len(encoded))
        pointer = self.STRING + self.record_index * 0x400
        self.store(pointer, encoded)
        block = bytearray(profile.FIND_CONTEXT_BYTES)
        struct.pack_into("<I", block, profile.FIND_LFN_POINTER_OFFSET, pointer)
        struct.pack_into("<I", block, profile.FIND_SIZE_OFFSET, size)
        block[profile.FIND_ATTRIBUTES_OFFSET] = attributes
        self.store(context, block)

    def raw(self, name, *args):
        if name == "find_first":
            if not self.records:
                return 0xFFFFFFFF
            self.record_index = 0
            self._publish_record(args[1])
            return 0
        if name == "find_next":
            self.record_index += 1
            if self.record_index >= len(self.records):
                return 0xFFFFFFFF
            self._publish_record(args[0])
            return 0
        if name == "find_close":
            self.closed_find += 1
            return self.close_result
        if name == "open":
            self.file_position = 0
            return self.HANDLE
        if name == "read_file":
            destination, item_size, count, handle = args
            assert item_size == 1 and handle == self.HANDLE
            data = self.file_data[self.file_position:self.file_position + count]
            self.store(destination, data)
            self.file_position += len(data)
            return len(data)
        if name == "seek":
            handle, offset, origin = args
            assert handle == self.HANDLE and origin == 0
            if offset > len(self.file_data):
                return 1
            self.file_position = offset
            return 0
        if name == "close_file":
            self.closed_file += 1
            return self.close_result
        raise AssertionError(name)


class FakeImages:
    def __init__(self, device):
        self.dbg = device

    def contains(self, address, size):
        self.dbg._segment(address, size)

    def write(self, address, data):
        if len(data) & 3:
            raise AssertionError("unaligned write")
        self.dbg.store(address, data)

    def trusted(self, address, size):
        if address != MemoryDevice.HANDLE or size != 0x2C:
            raise AssertionError("unexpected handle")


class FileDiscoveryTests(unittest.TestCase):
    def test_utf16_round_trip_including_surrogate_pair(self):
        text = "Movie-\u4e2d-\U0001f3ac.M1V"
        encoded = utf16le_z(text)
        self.assertEqual(decode_utf16le_z(encoded), text)
        with self.assertRaisesRegex(native_runtime.Error, "UNTERMINATED"):
            decode_utf16le_z(encoded[:-2])

    def test_collect_filters_attributes_extensions_and_stably_sorts(self):
        records = [
            ("z.MjPg", 9, 0),
            ("A.m1v", 7, 0),
            ("folder.M1V", 0, profile.ATTR_DIRECTORY),
            ("hidden.MJPG", 1, profile.ATTR_HIDDEN),
            ("system.m1v", 1, profile.ATTR_SYSTEM),
            ("note.txt", 2, 0),
            ("a.MJPG", 8, 0),
        ]
        files = collect_files(records)
        self.assertEqual([item.name for item in files], ["A.m1v", "a.MJPG", "z.MjPg"])
        self.assertEqual([item.extension for item in files], [".M1V", ".MJPG", ".MJPG"])
        self.assertTrue(all(item.path.startswith(profile.APP_DIR) for item in files))

    def test_native_scanner_reads_lfn_size_attributes_and_closes(self):
        long_name = "\u6d4b\u8bd5-" + "x" * 90 + ".MJPG"
        device = MemoryDevice([
            ("B.M1V", 0x12345678, 0),
            (long_name, 42, 0),
            ("skip.M1V", 1, profile.ATTR_DIRECTORY),
        ])
        scanner = NativeDirectoryScanner(device, FakeImages(device),
                                         (0, 0, 0, 0, device.SCRATCH))
        files = scanner.scan()
        self.assertEqual([item.name for item in files], ["B.M1V", long_name])
        self.assertEqual(files[0].size, 0x12345678)
        self.assertEqual(device.closed_find, 1)

    def test_find_close_failure_is_explicit(self):
        device = MemoryDevice([("A.M1V", 1, 0)])
        device.close_result = 7
        scanner = NativeDirectoryScanner(device, FakeImages(device),
                                         (0, 0, 0, 0, device.SCRATCH))
        with self.assertRaisesRegex(native_runtime.Error, "FIND_CLOSE_FAILED"):
            scanner.scan()
        self.assertEqual(device.closed_find, 1)


class NativeFileTests(unittest.TestCase):
    def test_dynamic_utf16_open_exact_reads_eof_and_single_close(self):
        data = b"0123456789"
        device = MemoryDevice(file_data=data)
        entry = FileEntry("\u6d4b\u8bd5.M1V", profile.APP_DIR + "\u6d4b\u8bd5.M1V",
                          ".M1V", len(data))
        native = NativeFile(device, FakeImages(device), device.SCRATCH, 4096, entry)
        native.open()
        self.assertEqual(native.read_small(4), b"0123")
        native.read_exact_to(device.SCRATCH + 64, 6)
        self.assertEqual(device.read(device.SCRATCH + 64, 6), b"456789")
        native.verify_eof()
        native.seek_absolute(3)
        self.assertEqual(native.read_small(2), b"34")
        native.close()
        native.close()
        self.assertEqual(device.closed_file, 1)

    def test_declared_size_and_short_read_fail_without_fallback(self):
        device = MemoryDevice(file_data=b"abc")
        entry = FileEntry("bad.M1V", profile.APP_DIR + "bad.M1V", ".M1V", 5)
        native = NativeFile(device, FakeImages(device), device.SCRATCH, 4096, entry)
        native.open()
        with self.assertRaisesRegex(native_runtime.Error, "SHORT_READ"):
            native.read_exact_to(device.SCRATCH + 64, 5)
        native.close()


class FormatClockModelTests(unittest.TestCase):
    @staticmethod
    def container(frame, fps_num=10, fps_den=1, count=1, trailing=b""):
        header = struct.pack("<4sHHHHHHIIII", b"PVMJ", 1, 32, 320, 240,
                             fps_num, fps_den, count, 0, 0, 0)
        return (header + struct.pack("<I", len(frame)) + frame +
                b"\0" * ((-len(frame)) & 3) + trailing)

    def test_mjpg_valid_and_strict_eof(self):
        frame = (ROOT / "tests/fixtures/F00.JPG").read_bytes()
        validate_baseline_jpeg(frame)
        header, frames = parse_bytes(self.container(frame))
        self.assertEqual((header.width, header.height, header.frame_count),
                         (320, 240, 1))
        self.assertEqual(frames, (frame,))
        with self.assertRaisesRegex(MjpgError, "TRAILING_DATA"):
            parse_bytes(self.container(frame, trailing=b"X"))

    def test_mjpg_rejects_bad_header_fps_count_padding_and_truncation(self):
        frame = (ROOT / "tests/fixtures/F00.JPG").read_bytes()
        for payload, message in (
                (self.container(frame, fps_den=0), "BAD_FPS"),
                (self.container(frame, count=2), "TRUNCATED_READ"),
                (self.container(frame)[:-1], "TRUNCATED_READ")):
            with self.subTest(message=message):
                with self.assertRaisesRegex(MjpgError, message):
                    parse_bytes(payload)
        malformed = bytearray(self.container(frame))
        if (-len(frame)) & 3:
            malformed[-1] = 1
            with self.assertRaisesRegex(MjpgError, "NONZERO_PADDING"):
                parse_bytes(malformed)

    def test_clock_waits_and_counts_only_rendering_over_50ms(self):
        state = {"now": 100}
        def ticks():
            return state["now"]
        def wait(ms):
            state["now"] += ms
        clock = FrameClock(25, 1, ticks, wait)
        clock.frame_presented(49)
        self.assertEqual(state["now"], 140)
        self.assertEqual(clock.late_frames, 0)
        clock.frame_presented(50)
        self.assertEqual(clock.late_frames, 1)
        clock.frame_decoded(False, 100)
        self.assertEqual(clock.late_frames, 1)
        clock.pause()
        self.assertEqual(clock.display_fps_tenths, 0)
        state["now"] += 500
        clock.resume()
        self.assertEqual(clock.frames, 3)

    def test_clock_measures_displayed_fps_and_complete_shifts_late_time(self):
        state = {"now": 0}
        measured = FrameClock(25, 1, lambda: state["now"],
                              lambda milliseconds: None)
        for frame in range(25):
            state["now"] = (frame + 1) * 20
            measured.frame_decoded(True, 1)
        self.assertEqual(measured.display_fps_tenths, 500)

        state["now"] = 0
        complete = FrameClock(25, 1, lambda: state["now"],
                              lambda milliseconds: state.__setitem__(
                                  "now", state["now"] + milliseconds))
        state["now"] = 60
        complete.frame_presented(60, "COMPLETE")
        self.assertEqual(complete.late_frames, 1)
        complete.frame_presented(10, "COMPLETE")
        self.assertEqual(state["now"], 100)

        state["now"] = 0
        sync = FrameClock(25, 1, lambda: state["now"],
                          lambda milliseconds: state.__setitem__(
                              "now", state["now"] + milliseconds))
        state["now"] = 60
        sync.frame_presented(60, "SYNC")
        sync.frame_presented(10, "SYNC")
        self.assertEqual(state["now"], 80)

    def test_player_model_actions_and_loop_end(self):
        files = [FileEntry("a.M1V", "a", ".M1V", 1),
                 FileEntry("b.MJPG", "b", ".MJPG", 2)]
        model = PlayerModel(files)
        self.assertEqual(model.mode, PlaybackMode.ONCE)
        self.assertEqual(model.event("HELP"), "SETTINGS_OPEN")
        self.assertEqual(model.state, PlayerState.SETTINGS)
        for unused in range(4):
            model.event("DOWN")
        model.event("RIGHT")
        self.assertEqual(model.settings_draft.end_mode, PlaybackMode.SINGLE)
        self.assertEqual(model.event("ENTER"), "SETTINGS_SAVE")
        self.assertEqual(model.state, PlayerState.SETTINGS)
        model.commit_settings()
        self.assertEqual(model.mode, PlaybackMode.SINGLE)
        self.assertEqual(model.event("ENTER"), "START")
        self.assertEqual(model.event("ENTER"), "PAUSE")
        self.assertEqual(model.event("ENTER"), "RESUME")
        self.assertEqual(model.finished(), "RESTART")
        model.mode = PlaybackMode.ALL
        self.assertEqual(model.mode, PlaybackMode.ALL)
        self.assertEqual(model.finished(), "NEXT")
        self.assertEqual(model.index, 1)
        self.assertEqual(model.event("LEFT"), "SWITCH")
        self.assertEqual(model.event("BACK"), "STOP")
        self.assertEqual(model.state, PlayerState.LIST)

    def test_default_completion_seek_selector_and_debug_modes(self):
        model = PlayerModel([FileEntry("a.M1V", "a", ".M1V", 1000)])
        self.assertEqual(model.event("ENTER"), "START")
        self.assertEqual(model.event("UP", 500), "SEEK_BEGIN")
        self.assertEqual((model.state, model.seek_target),
                         (PlayerState.SEEKING, 501))
        model.event("RIGHT")
        model.event("DOWN")
        self.assertEqual(model.seek_target, 550)
        self.assertEqual(model.event("HELP"), "DEBUG")
        self.assertEqual(model.debug_mode, DebugMode.FULL)
        self.assertEqual(model.event("ENTER"), "SEEK")
        self.assertEqual(model.state, PlayerState.PLAYING)
        self.assertEqual(model.finished(), "DONE")
        self.assertEqual(model.state, PlayerState.LIST)

    def test_position_records_and_mpeg_i_picture_helpers(self):
        records = {"C:\\DATA\\Movie.M1V": (12345, 501)}
        self.assertEqual(decode_positions(encode_positions(records)), records)
        sequence = b"\x00\x00\x01\xb3" + b"\x11" * 8
        i_picture = b"\x00\x00\x01\x00\x00\x08"
        p_picture = b"\x00\x00\x01\x00\x00\x10"
        stream = sequence + b"GOP" + i_picture + b"payload" + p_picture
        self.assertEqual(bootstrap_prefix(stream), sequence + b"GOP")
        self.assertEqual(i_picture_offsets(stream), (len(sequence) + 3,))
        self.assertEqual(safe_seek_anchors(stream), (0,))
        with self.assertRaisesRegex(native_runtime.Error, "BAD_MAGIC"):
            decode_positions(b"bad")

    def test_mpeg_sequence_header_supports_all_standard_rates(self):
        for code, expected in FRAME_RATES.items():
            header = bytes((0x14, 0x01, 0xE0, 0x10 | code))
            info = parse_sequence_header(b"prefix\0" + b"\0\0\1\xb3" + header)
            self.assertEqual((info.width, info.height), (320, 480))
            self.assertEqual((info.fps_num, info.fps_den), expected)
            self.assertEqual(info.rate_code, code)

    def test_mpeg_sequence_header_rejects_invalid_and_oversize_inputs(self):
        with self.assertRaisesRegex(M1VFormatError, "NOT_FOUND"):
            parse_sequence_header(b"not mpeg")
        with self.assertRaisesRegex(M1VFormatError, "TRUNCATED"):
            parse_sequence_header(b"\0\0\1\xb3\x14")
        with self.assertRaisesRegex(M1VFormatError, "RATE_CODE"):
            parse_sequence_header(b"\0\0\1\xb3\x14\x01\xe0\x19")
        with self.assertRaisesRegex(M1VFormatError, "NATIVE_WINDOW"):
            M1VInfo(4095, 4095, 1, 3)

    def test_mpeg_arena_rounding_and_four_scale_modes(self):
        exact = M1VInfo(320, 240, 1, 3)
        odd = M1VInfo(318, 238, 1, 3)
        wide = M1VInfo(320, 180, 1, 3)
        large = M1VInfo(640, 480, 1, 3)
        self.assertEqual(exact.arena_bytes, 346408)
        self.assertEqual(odd.arena_bytes, exact.arena_bytes)
        self.assertEqual(large.arena_bytes, 1383208)
        self.assertEqual(scale_geometry(wide, "FIT"),
                         (0, 0, 320, 180, 0, 30, 320, 180))
        self.assertEqual(scale_geometry(wide, "FILL"),
                         (40, 0, 240, 180, 0, 0, 320, 240))
        self.assertEqual(scale_geometry(large, "ORIGINAL"),
                         (160, 120, 320, 240, 0, 0, 320, 240))
        self.assertEqual(scale_geometry(wide, "STRETCH"),
                         (0, 0, 320, 180, 0, 0, 320, 240))

    def test_settings_round_trip_defaults_corruption_and_readback(self):
        defaults = default_settings()
        self.assertEqual(defaults.as_tuple(),
                         ("ZH_CN", "DARK", "FIT", "PROGRESS", "ONCE",
                          "SYNC"))
        self.assertEqual(decode_settings(encode_settings(defaults)).as_tuple(),
                         defaults.as_tuple())
        records = encode_settings(defaults).splitlines(True)
        reordered = records[0] + records[2] + records[1] + b"".join(records[3:])
        with self.assertRaisesRegex(native_runtime.Error,
                                    "MISSING_OR_REORDERED"):
            decode_settings(reordered)
        with self.assertRaisesRegex(native_runtime.Error, "BAD_MAGIC"):
            decode_settings(b"damaged")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "settings.dat")
            store = SettingsStore(path, open)
            self.assertEqual(store.load().as_tuple(), defaults.as_tuple())
            changed = defaults.copy()
            changed.cycle("language", 1)
            changed.cycle("scale", 1)
            store.save(changed)
            self.assertEqual(store.load().as_tuple(), changed.as_tuple())
            Path(path).write_bytes(b"bad")
            with self.assertRaisesRegex(native_runtime.Error, "BAD_MAGIC"):
                store.load()

    def test_clock_sync_skips_expired_display_but_complete_never_drops(self):
        state = {"now": 0}
        clock = FrameClock(60000, 1001, lambda: state["now"],
                           lambda milliseconds: None)
        self.assertTrue(clock.should_present("SYNC"))
        state["now"] = 20
        self.assertFalse(clock.should_present("SYNC"))
        self.assertTrue(clock.should_present("COMPLETE"))
        clock.frame_decoded(False, 20)
        self.assertEqual((clock.frames, clock.presented_frames,
                          clock.dropped_frames, clock.late_frames),
                         (1, 0, 1, 0))
        exact = FrameClock(24000, 1001, lambda: 0,
                           lambda milliseconds: None)
        self.assertEqual(exact.source_ms(24000), 1001000)


class DirectHpPrimeRuntimeTests(unittest.TestCase):
    def test_ticks_wait_and_keyboard_use_direct_hpprime_apis(self):
        now = [100]
        keyboard = [0]
        def ticks():
            value = now[0]
            now[0] += 5
            return value
        direct = types.SimpleNamespace(ticks=ticks,
                                       keyboard=lambda: keyboard[0],
                                       fillrect=lambda *args: None,
                                       textout=lambda *args: None)
        with patch.object(runtime, "hpprime", direct):
            runtime._reset_key_state()
            self.assertEqual(runtime.ticks_ms(), 100)
            runtime.wait_ms(10)
            keyboard[0] = 1 << 8
            self.assertEqual(runtime.key_event(), "RIGHT")
            self.assertIsNone(runtime.key_event())
            keyboard[0] = 0
            self.assertIsNone(runtime.key_event())
            keyboard[0] = 1 << 30
            self.assertEqual(runtime.key_event(), "ENTER")

    def test_up_down_long_press_repeat_is_opt_in(self):
        now = [0]
        keyboard = [0]
        direct = types.SimpleNamespace(ticks=lambda: now[0],
                                       keyboard=lambda: keyboard[0],
                                       fillrect=lambda *args: None,
                                       textout=lambda *args: None)
        with patch.object(runtime, "hpprime", direct):
            runtime._reset_key_state()
            keyboard[0] = 1 << 2
            self.assertEqual(runtime.key_event(), "UP")
            self.assertIsNone(runtime.key_event(repeat=True))
            now[0] = runtime.KEY_REPEAT_DELAY_MS - 1
            self.assertIsNone(runtime.key_event(repeat=True))
            now[0] = runtime.KEY_REPEAT_DELAY_MS
            self.assertEqual(runtime.key_event(repeat=True), "UP")
            now[0] += runtime.KEY_REPEAT_INTERVAL_MS - 1
            self.assertIsNone(runtime.key_event(repeat=True))
            now[0] += 1
            self.assertEqual(runtime.key_event(repeat=True), "UP")
            now[0] += runtime.KEY_REPEAT_INTERVAL_MS
            self.assertIsNone(runtime.key_event(repeat=False))
            keyboard[0] = 0
            self.assertIsNone(runtime.key_event(repeat=True))

    def test_screen_awake_uses_activity_reset_and_closes_bright(self):
        class Bridge:
            def __init__(self):
                self.calls = []

            def invoke(self, address, args):
                self.calls.append((address, args))
                return 0

        bridge = Bridge()
        awake = runtime.ScreenAwake(bridge)
        awake.start(100)
        self.assertEqual(len(bridge.calls), 1)
        awake.refresh(1099)
        self.assertEqual(len(bridge.calls), 1)
        awake.refresh(1100)
        self.assertEqual(len(bridge.calls), 2)
        awake.close()
        awake.close()
        self.assertEqual(len(bridge.calls), 3)
        self.assertTrue(all(call == (runtime.profile.SCREEN_ACTIVITY_API[0],
                                    (1,)) for call in bridge.calls))

    def test_screen_draws_with_fillrect_and_textout(self):
        fills, texts = [], []
        direct = types.SimpleNamespace(ticks=lambda: 0, keyboard=lambda: 0,
                                       fillrect=lambda *args: fills.append(args),
                                       textout=lambda *args: texts.append(args))
        with patch.object(runtime, "hpprime", direct):
            screen = runtime.PlayerScreen()
            screen.clear()
            screen.text("line\nbreak", 4, 6, 0x112233, 100, 0xFFFFFF)
        dark = runtime.PlayerScreen().palette()[0]
        self.assertEqual(fills[0], (0, 0, 0, 320, 240, dark, dark))
        self.assertEqual(fills[1], (0, 4, 6, 100, 16, 0xFFFFFF, 0xFFFFFF))
        self.assertEqual(texts, [(0, 4, 6, "line break", 0x112233)])

    def test_list_is_not_redrawn_while_idle_and_full_panel_fits(self):
        fills, texts = [], []
        direct = types.SimpleNamespace(ticks=lambda: 0, keyboard=lambda: 0,
                                       fillrect=lambda *args: fills.append(args),
                                       textout=lambda *args: texts.append(args))
        model = PlayerModel([FileEntry("movie.M1V", "movie.M1V", ".M1V",
                                       1024 * 1024)])
        with patch.object(runtime, "hpprime", direct):
            screen = runtime.PlayerScreen()
            screen.list(model)
            self.assertEqual(fills[0], (0, 0, 0, 320, 240,
                                        runtime.LIST_BACKGROUND,
                                        runtime.LIST_BACKGROUND))
            draw_count = len(fills) + len(texts)
            screen.list(model)
            self.assertEqual(len(fills) + len(texts), draw_count)

            class Session:
                total_frames = None
                frames = 12
                source_ms = 480
                bytes_read = 524288
                late_frames = 0
                display_fps_tenths = 247
                position_tenths = 500
                current_frame = True
                bottom = None
                present_calls = 0

                def set_video_bottom(self, bottom):
                    self.bottom = bottom

                def present_current(self):
                    self.present_calls += 1

            model.state = PlayerState.PLAYING
            model.debug_mode = DebugMode.FULL
            texts[:] = []
            session = Session()
            screen.playback(model.files[0], session, model)
            draw_count = len(fills) + len(texts)
            screen.playback(model.files[0], session, model)
            self.assertEqual(len(fills) + len(texts), draw_count)
            screen.video_frame_updated()
            screen.playback(model.files[0], session, model)
            self.assertGreater(len(fills) + len(texts), draw_count)
        self.assertEqual(session.bottom, 239)
        self.assertTrue(texts)
        self.assertLessEqual(max(item[2] for item in texts), 225)

    def test_progress_fps_is_transparent_and_pause_or_off_clears_it(self):
        fills, texts = [], []
        direct = types.SimpleNamespace(ticks=lambda: 0, keyboard=lambda: 0,
                                       fillrect=lambda *args: fills.append(args),
                                       textout=lambda *args: texts.append(args))
        model = PlayerModel([FileEntry("movie.M1V", "movie.M1V", ".M1V",
                                       1024)])
        model.state = PlayerState.PLAYING
        model.debug_mode = DebugMode.PROGRESS

        class Session:
            position_tenths = 125
            display_fps_tenths = 247
            current_frame = True
            present_calls = 0

            def set_video_bottom(self, bottom):
                pass

            def present_current(self):
                self.present_calls += 1

        with patch.object(runtime, "hpprime", direct):
            screen = runtime.PlayerScreen()
            session = Session()
            screen.video_frame_updated()
            screen.playback(model.files[0], session, model)
            self.assertFalse(any(call[1:5] == (0, 216, 320, 24)
                                 for call in fills))
            self.assertIn("FPS:24.7", [call[3] for call in texts])

            texts[:] = []
            model.state = PlayerState.PAUSED
            screen.playback(model.files[0], session, model, paused=True)
            self.assertEqual(session.present_calls, 1)
            self.assertIn("FPS:0.0", [call[3] for call in texts])

            model.debug_mode = DebugMode.OFF
            screen.playback(model.files[0], session, model, paused=True)
            self.assertEqual(session.present_calls, 2)


if __name__ == "__main__":
    unittest.main()
