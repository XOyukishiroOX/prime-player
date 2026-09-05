"""Incremental MJPG and fixed-window MPEG-1 playback sessions."""

import ustruct as struct

import prime_mjpeg_decoder
import prime_native as native
import prime_video_profile as app_profile
import mpeg_stream_profile as mpeg_profile
from mjpg_container import (HEADER_BYTES, MAX_FRAME_BYTES, MjpgError,
                            parse_header, validate_baseline_jpeg)
from prime_video_io import NativeFile
from prime_video_m1v import safe_seek_anchors

Error = native.Error
FULL_CLIP = (0, 0, 319, 239)
ANCHOR_SCAN_BYTES = 512 * 1024


class MjpgPlaybackSession:
    def __init__(self, dbg, entry, emit=None):
        self.dbg, self.entry = dbg, entry
        self.emit = emit or (lambda message, visible=True: None)
        self.decoder = None
        self.file = None
        self.header = None
        self.frames = 0
        self.bytes_read = 0
        self.late_frames = 0
        self.current_frame = False
        self.video_bottom = 239

    def start(self):
        self.decoder = prime_mjpeg_decoder.DecoderSession(self.dbg, self.emit)
        self.decoder.start()
        self.file = NativeFile(self.dbg, self.decoder.images,
                               self.decoder.input_address,
                               self.decoder.input_span, self.entry)
        self.file.open()
        self.header = parse_header(self.file.read_small(HEADER_BYTES))
        self.bytes_read = self.file.position

    @property
    def fps(self):
        return self.header.fps_num, self.header.fps_den

    @property
    def total_frames(self):
        return self.header.frame_count

    @property
    def source_ms(self):
        return self.frames * 1000 * self.header.fps_den // self.header.fps_num

    @property
    def position_tenths(self):
        return min(1000, self.frames * 1000 // self.header.frame_count)

    def set_video_bottom(self, bottom):
        if bottom not in (179, 217, 239):
            raise Error("DISPLAY_CLIP_INVALID")
        if bottom != self.video_bottom:
            self.dbg.raw("clip", 0, 0, 319, bottom)
            self.video_bottom = bottom
            if self.current_frame:
                self.present_current()

    def present_current(self):
        if self.current_frame:
            self.decoder.direct_used = True
            self.dbg.call("put", 0, 0, self.decoder.output_header, 0)

    def next_frame(self):
        if self.frames >= self.header.frame_count:
            self.file.verify_eof()
            return False
        size = struct.unpack("<I", self.file.read_small(4))[0]
        if size == 0 or size > MAX_FRAME_BYTES:
            raise MjpgError("MJPG_FRAME_SIZE_INVALID %d" % size)
        self.file.read_exact_to(self.decoder.input_address, size)
        data = self.file.read_owned_bytes(self.decoder.input_address, size)
        validate_baseline_jpeg(data)
        self.decoder.decode_loaded_to_buffer(size)
        self.current_frame = True
        self.present_current()
        padding = (-size) & 3
        if padding:
            self.file.read_exact_to(self.decoder.input_address + size, padding)
            if self.dbg.read(self.decoder.input_address + size, padding) != b"\0" * padding:
                raise MjpgError("MJPG_NONZERO_PADDING")
        self.frames += 1
        self.bytes_read = self.file.position
        if self.frames == self.header.frame_count:
            self.file.verify_eof()
        return True

    def seek_tenths(self, tenths):
        if not isinstance(tenths, int) or not 0 <= tenths <= 999:
            raise Error("SEEK_PERCENT_INVALID")
        target_frame = min(self.header.frame_count - 1,
                           self.header.frame_count * tenths // 1000)
        self.file.seek_absolute(HEADER_BYTES)
        self.frames = 0
        self.current_frame = False
        while self.frames < target_frame:
            size = struct.unpack("<I", self.file.read_small(4))[0]
            if size == 0 or size > MAX_FRAME_BYTES:
                raise MjpgError("MJPG_FRAME_SIZE_INVALID %d" % size)
            end = self.file.position + size + ((-size) & 3)
            if end > self.entry.size:
                raise MjpgError("MJPG_FRAME_TRUNCATED at=%d" % self.file.position)
            self.file.seek_absolute(end)
            self.frames += 1
        self.bytes_read = self.file.position
        self.next_frame()
        return self.position_tenths

    def close(self):
        errors = []
        if self.file is not None:
            try:
                self.file.close()
            except BaseException as exc:
                errors.append(str(exc))
        if self.decoder is not None:
            try:
                self.decoder.close()
            except BaseException as exc:
                errors.append(str(exc))
        if errors:
            raise Error("; ".join(errors))


class NativeModule:
    def __init__(self, images, image, payload):
        self.images, self.dbg, self.payload = images, images.dbg, payload
        self.address = (image[4] + 63) & ~31
        self.ready = False
        images.contains(self.address - 32, payload.MODULE_BYTES + 64)
        images.write(self.address - 32, mpeg_profile.GUARD)
        images.write(self.address + payload.MODULE_BYTES, mpeg_profile.GUARD)

    def load(self):
        blob = bytearray()
        for chunk in self.payload.MODULE_CHUNKS:
            blob.extend(chunk)
        if len(blob) != self.payload.MODULE_BYTES:
            raise Error("MPEG_MODULE_SIZE_MISMATCH")
        for word_offset, target_offset in self.payload.MODULE_RELOCATIONS:
            if struct.unpack_from("<I", blob, word_offset)[0] != target_offset:
                raise Error("MPEG_RELOCATION_SOURCE_MISMATCH")
            struct.pack_into("<I", blob, word_offset,
                             self.address + target_offset)
        for offset in range(0, len(blob), 4096):
            self.images.write(self.address + offset, blob[offset:offset + 4096])
        for address in range(self.address,
                             self.address + self.payload.MODULE_BYTES, 32):
            self.dbg.maintenance("clean_line", address)
        self.dbg.maintenance("drain")
        self.dbg.maintenance("invalidate_i")
        self.ready = True

    def execute(self, context):
        if not self.ready:
            raise Error("MPEG_MODULE_NOT_READY")
        return self.dbg.invoke(self.address, (context, mpeg_profile.COOKIE))

    def check_guards(self):
        if (self.dbg.read(self.address - 32, 32) != mpeg_profile.GUARD or
                self.dbg.read(self.address + self.payload.MODULE_BYTES, 32) !=
                mpeg_profile.GUARD):
            raise Error("MPEG_CODE_GUARD_CHANGED")


class M1VPlaybackSession:
    def __init__(self, dbg, entry, emit=None):
        self.dbg, self.entry = dbg, entry
        self.emit = emit or (lambda message, visible=True: None)
        self.images = None
        self.file = None
        self.code = None
        self.initialized = False
        self.frames = 0
        self.bytes_read = 0
        self.late_frames = 0
        self.eof_sent = False
        self.stream_anchor = 0
        self.position_bytes = 0
        self.current_frame = False
        self.video_bottom = 239

    def _guarded(self, size):
        image = self.images.create(256, (size + 95 + 1023) // 1024)
        address = (image[4] + 63) & ~31
        self.images.contains(address - 32, size + 64)
        self.images.write(address - 32, mpeg_profile.GUARD)
        self.images.write(address + size, mpeg_profile.GUARD)
        return image, address

    def start(self):
        import mpeg_stream_payload
        self.dbg.verify()
        active, real = self.dbg.call("active"), self.dbg.call("real")
        self.screen = native.read_lcd(self.dbg, active)
        if active != real or self.screen[5] != 32:
            raise Error("UNEXPECTED_LCD_CONTEXT")
        self.active = active
        self.original_clip = native.clip_area(self.dbg, active)
        self.images = native.OwnedImages(self.dbg, active, self.screen)

        output_backing = self.images.create(320, 241)
        self.output = (output_backing[4] + 95) & ~31
        self.output_header = self.output - 20
        self.images.contains(self.output - 52,
                             32 + 20 + mpeg_profile.OUTPUT_BYTES + 32)
        self.images.write(self.output - 52, mpeg_profile.GUARD)
        self.images.write(self.output_header,
                          struct.pack("<2shhhhhII", b"PX", 320, 240,
                                      32, 1280, 2, 0, self.output))
        self.images.write(self.output + mpeg_profile.OUTPUT_BYTES,
                          mpeg_profile.GUARD)

        unused, self.staging = self._guarded(mpeg_profile.STAGING_BYTES)
        unused, self.ring = self._guarded(mpeg_profile.RING_BYTES)
        unused, self.arena = self._guarded(mpeg_profile.ARENA_BYTES)
        context_image, self.context = self._guarded(mpeg_profile.CONTEXT_BYTES)
        code_image = self.images.create(
            256, (mpeg_stream_payload.MODULE_BYTES + 95 + 1023) // 1024)
        self.code = NativeModule(self.images, code_image, mpeg_stream_payload)
        self.saved = self.images.create(320, 240)

        for offset in range(0, mpeg_profile.OUTPUT_BYTES, 4096):
            size = min(4096, mpeg_profile.OUTPUT_BYTES - offset)
            self.images.write(self.saved[4] + offset,
                              self.dbg.read(self.screen[4] + offset, size))
        self.dbg.raw("clip", *FULL_CLIP)
        self.code.load()
        words = [0] * mpeg_profile.RESULT_WORDS
        words[:9] = (mpeg_profile.CONTEXT_MAGIC, self.staging,
                     mpeg_profile.STAGING_BYTES, self.ring,
                     mpeg_profile.RING_BYTES, self.output,
                     mpeg_profile.OUTPUT_BYTES, self.arena,
                     mpeg_profile.ARENA_BYTES)
        words[12] = mpeg_profile.RESULT_MAGIC
        self.images.write(self.context,
                          struct.pack("<%dI" % len(words), *words))
        self._init_decoder()
        self.file = NativeFile(self.dbg, self.images, self.staging,
                               mpeg_profile.STAGING_BYTES, self.entry)
        self.file.open()

    def _init_decoder(self):
        result = self._command(mpeg_profile.COMMAND_INIT_STREAM)
        words = self._context_words()
        if (result != mpeg_profile.SUCCESS or words[13] != 0 or
                words[25] != mpeg_profile.STATE_MAGIC or not words[26] or
                not words[27] or words[24] != 0):
            raise Error("MPEG_INIT_FAILED 0x%x detail=%d" %
                        (result, words[39]))
        self.initialized = True

    @property
    def fps(self):
        return 25, 1

    @property
    def total_frames(self):
        return None

    @property
    def source_ms(self):
        return self.frames * 40

    @property
    def position_tenths(self):
        if not self.entry.size:
            return 0
        return min(1000, self.position_bytes * 1000 // self.entry.size)

    def set_video_bottom(self, bottom):
        if bottom not in (179, 217, 239):
            raise Error("DISPLAY_CLIP_INVALID")
        if bottom != self.video_bottom:
            self.dbg.raw("clip", 0, 0, 319, bottom)
            self.video_bottom = bottom
            if self.current_frame:
                self.present_current()

    def present_current(self):
        if self.current_frame:
            self.dbg.call("put", 0, 0, self.output_header, 0)

    def _context_words(self):
        words = struct.unpack("<%dI" % mpeg_profile.RESULT_WORDS,
                              self.dbg.read(self.context,
                                            mpeg_profile.CONTEXT_BYTES))
        if words[0] != mpeg_profile.CONTEXT_MAGIC or words[12] != mpeg_profile.RESULT_MAGIC:
            raise Error("MPEG_CONTEXT_CORRUPTED")
        return words

    def _command(self, command, feed_count=None, eof=None):
        self.images.write(self.context + 9 * 4, struct.pack("<I", command))
        if feed_count is not None:
            self.images.write(self.context + 10 * 4,
                              struct.pack("<II", feed_count, int(bool(eof))))
        result = self.code.execute(self.context)
        self._context_words()
        return result

    def _feed(self):
        remaining = self.entry.size - self.file.position
        if remaining:
            count = min(mpeg_profile.STAGING_BYTES, remaining)
            self.file.read_exact_to(self.staging, count)
            final = self.file.position == self.entry.size
            if final:
                self.file.verify_eof()
            result = self._command(mpeg_profile.COMMAND_FEED, count, final)
            self.bytes_read = self.file.position
            self.eof_sent = final
        elif not self.eof_sent:
            self.file.verify_eof()
            result = self._command(mpeg_profile.COMMAND_FEED, 0, True)
            self.eof_sent = True
        else:
            raise Error("MPEG_REQUESTED_INPUT_AFTER_EOF")
        if result == mpeg_profile.RING_OVERFLOW:
            raise Error("MPEG_COMPRESSED_WINDOW_EXCEEDS_128_KIB")
        if result != mpeg_profile.SUCCESS:
            raise Error("MPEG_FEED_FAILED 0x%x" % result)

    def _update_position(self, words):
        consumed = words[19]
        self.position_bytes = min(self.entry.size,
                                  self.stream_anchor + consumed)

    def _scan_anchors(self, start, target):
        self.file.seek_absolute(start)
        cursor = start
        tail = b""
        found = []
        end = min(self.entry.size, target + 6)
        while cursor < end:
            count = min(mpeg_profile.STAGING_BYTES, end - cursor)
            chunk = self.file.read_small(count)
            combined = tail + chunk
            base = cursor - len(tail)
            offsets = safe_seek_anchors(combined, base, target)
            for offset in offsets:
                if not found or found[-1] != offset:
                    found.append(offset)
            tail = combined[-512:]
            cursor += count
        return tuple(found)

    def _find_anchor(self, target):
        if target <= 0:
            return 0
        start = max(0, target - ANCHOR_SCAN_BYTES)
        while True:
            anchors = self._scan_anchors(start, target)
            if len(anchors) >= 2:
                return anchors[-2]
            if start == 0:
                return 0
            start = max(0, start - ANCHOR_SCAN_BYTES)

    def _restart_at(self, anchor):
        if self.initialized:
            result = self._command(mpeg_profile.COMMAND_RESET)
            if result != mpeg_profile.SUCCESS:
                raise Error("MPEG_RESET_FAILED 0x%x" % result)
            self.initialized = False
        self._init_decoder()
        self.file.seek_absolute(anchor)
        self.eof_sent = False
        self.frames = 0
        self.bytes_read = anchor
        self.position_bytes = anchor
        self.current_frame = False
        self.stream_anchor = anchor

    def next_frame(self, present=True):
        while True:
            result = self._command(mpeg_profile.COMMAND_NEXT_2X2)
            words = self._context_words()
            if result == mpeg_profile.FRAME_READY:
                self.frames = words[17]
                self._update_position(words)
                self.current_frame = True
                if present:
                    self.present_current()
                return True
            if result == mpeg_profile.NEED_INPUT:
                self._feed()
                continue
            if result == mpeg_profile.END_OF_STREAM:
                return False
            if result == mpeg_profile.UNSUPPORTED and words[39] == 6:
                fps = words[16]
                raise Error(
                    "MPEG_UNSUPPORTED expected=320x240@25 "
                    "actual=%dx%d@%d.%03d" %
                    (words[14], words[15], fps // 1000, fps % 1000))
            raise Error("MPEG_DECODE_FAILED code=0x%x detail=%d" %
                        (result, words[39]))

    def seek_tenths(self, tenths):
        if not isinstance(tenths, int) or not 0 <= tenths <= 999:
            raise Error("SEEK_PERCENT_INVALID")
        target = self.entry.size * tenths // 1000
        anchor = self._find_anchor(target)
        self._restart_at(anchor)
        while self.position_bytes < target:
            if not self.next_frame(False):
                break
        self.present_current()
        return self.position_tenths

    def close(self):
        errors = []
        if self.initialized:
            try:
                result = self._command(mpeg_profile.COMMAND_RESET)
                if result != mpeg_profile.SUCCESS:
                    raise Error("MPEG_RESET_FAILED 0x%x" % result)
            except BaseException as exc:
                errors.append(str(exc))
            self.initialized = False
        if self.file is not None:
            try:
                self.file.close()
            except BaseException as exc:
                errors.append(str(exc))
        if self.images is not None:
            try:
                if self.code is not None:
                    self.code.check_guards()
                if hasattr(self, "saved"):
                    self.dbg.raw("clip", *FULL_CLIP)
                    self.dbg.call("put", 0, 0, self.saved[0], 0)
                    native.compare_buffers(self.dbg, self.saved[4],
                                           self.screen[4])
                self.dbg.raw("clip", *self.original_clip)
            except BaseException as exc:
                errors.append("RESTORE_FAILED: " + str(exc))
            errors.extend(self.images.release())
        if errors:
            raise Error("; ".join(errors))
