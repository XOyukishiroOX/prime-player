"""Verified bridge and direct-hpprime compact G1 player UI."""

import hpprime
import prime_native as native
from prime_video_i18n import text as tr
import prime_video_profile as profile
from prime_video_model import DebugMode, PlayerState
from prime_video_settings import SETTING_KEYS
from prime_video_compositor import FrameCompositor

Error = native.Error
struct = native.struct
_last_keyboard = 0
_repeat_bit = None
_repeat_event = None
_repeat_started = None
_repeat_last = None

KEY_REPEAT_DELAY_MS = 320
KEY_REPEAT_INTERVAL_MS = 40
LIST_BACKGROUND = 0x0B1117
LIST_TEXT = 0xE7EAEC
LIST_MUTED = 0xA8B0B8
LIST_ACCENT = 0x55D6BE
LIST_SELECTION = 0x25735A


class PlayerBridge(native.Bridge):
    pass


def ticks_ms():
    value = hpprime.ticks()
    if not isinstance(value, (int, float)) or value < 0 or value != int(value):
        raise Error("TICKS_INVALID")
    return int(value)


def wait_ms(milliseconds):
    if not isinstance(milliseconds, int) or milliseconds < 0:
        raise Error("WAIT_INVALID")
    if milliseconds <= 0:
        return
    start = ticks_ms()
    while True:
        now = ticks_ms()
        elapsed = now - start
        if elapsed < 0:
            elapsed &= 0xFFFFFFFF
        if elapsed >= milliseconds:
            return


def _elapsed_ms(now, earlier):
    elapsed = now - earlier
    if elapsed < 0:
        elapsed &= 0xFFFFFFFF
    return elapsed


def _clear_key_repeat():
    global _repeat_bit, _repeat_event, _repeat_started, _repeat_last
    _repeat_bit = None
    _repeat_event = None
    _repeat_started = None
    _repeat_last = None


def _reset_key_state():
    global _last_keyboard
    _last_keyboard = 0
    _clear_key_repeat()


def key_event(repeat=False):
    global _last_keyboard, _repeat_bit, _repeat_event
    global _repeat_started, _repeat_last
    value = hpprime.keyboard()
    if not isinstance(value, int) or value < 0:
        raise Error("KEYBOARD_INVALID")
    value = int(value)
    pressed = value & ~_last_keyboard
    _last_keyboard = value
    for bit, event in profile.KEY_EVENTS:
        if pressed & (1 << bit):
            if event in ("UP", "DOWN"):
                _repeat_bit = bit
                _repeat_event = event
                _repeat_started = None
                _repeat_last = None
            else:
                _clear_key_repeat()
            return event
    if _repeat_bit is None:
        return None
    if not value & (1 << _repeat_bit):
        _clear_key_repeat()
        return None
    if not repeat:
        return None
    now = ticks_ms()
    if _repeat_started is None:
        _repeat_started = now
        _repeat_last = now
        return None
    if (_elapsed_ms(now, _repeat_started) < KEY_REPEAT_DELAY_MS or
            _elapsed_ms(now, _repeat_last) < KEY_REPEAT_INTERVAL_MS):
        return None
    _repeat_last = now
    return _repeat_event


class ScreenAwake:
    """Reports playback activity without changing firmware dim settings."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.active = False
        self.last_refresh = None

    def _notify_activity(self):
        address, argc, guard = profile.SCREEN_ACTIVITY_API
        self.bridge.invoke(address, (1,))

    def start(self, now=None):
        if self.active:
            raise Error("SCREEN_AWAKE_ALREADY_STARTED")
        self.active = True
        self._notify_activity()
        self.last_refresh = ticks_ms() if now is None else now

    def refresh(self, now=None):
        if not self.active:
            return
        now = ticks_ms() if now is None else now
        if (_elapsed_ms(now, self.last_refresh) <
                profile.SCREEN_ACTIVITY_REFRESH_MS):
            return
        self._notify_activity()
        self.last_refresh = now

    def close(self):
        if not self.active:
            return
        self.active = False
        self._notify_activity()
        self.last_refresh = None


class ListTextCanvas:
    """Clip complete filenames to an actual 214 x 16 pixel image, not characters."""

    def __init__(self, bridge=None):
        self.bridge = bridge
        self.images = None
        self.canvas = None
        self.original_clip = None

    def start(self):
        if self.bridge is None:
            self.bridge = PlayerBridge(native.uio.FileIO("debug"))
        self.bridge.verify()
        active = self.bridge.call("active")
        screen = native.read_lcd(self.bridge, active)
        if active != self.bridge.call("real") or screen[5] != 32:
            raise Error("UNEXPECTED_LCD_CONTEXT")
        self.images = native.OwnedImages(self.bridge, active, screen)
        self.canvas = FrameCompositor(self.images, 214, 16)
        self.canvas.start()
        self.original_clip = native.clip_area(self.bridge, active)
        self.bridge.raw("clip", 0, 0, 319, 239)

    def draw(self, value, x, y, color, background):
        value = str(value).replace("\r", " ").replace("\n", " ")
        target = self.canvas.bind()
        try:
            hpprime.fillrect(target, 0, 0, 214, 16, background, background)
            hpprime.textout(target, 0, 0, value, color)
        finally:
            self.canvas.end()
        self.canvas.present(x, y)

    def close(self):
        errors = []
        if self.canvas is not None:
            try:
                self.canvas.close()
            except BaseException as exc:
                errors.append(str(exc))
        if self.original_clip is not None:
            try:
                self.bridge.raw("clip", *self.original_clip)
                if native.clip_area(self.bridge, self.images.active) != self.original_clip:
                    raise Error("LIST_TEXT_CLIP_RESTORE_MISMATCH")
            except BaseException as exc:
                errors.append(str(exc))
        if self.images is not None and not (self.canvas and self.canvas.bound):
            errors.extend(self.images.release())
        if self.bridge is not None:
            bridge, self.bridge = self.bridge, None
            try:
                bridge.close()
            except BaseException as exc:
                errors.append(str(exc))
        if errors:
            raise Error("LIST_TEXT_CLEANUP_FAILED: " + "; ".join(errors))


class PlayerScreen:
    def __init__(self, text_canvas_factory=None):
        self._text_canvas_factory = text_canvas_factory or ListTextCanvas
        self._target = 0
        self._view = None
        self._signature = None
        self._play_mode = None
        self._play_lines = [None, None, None, None]
        self._fps_line = None
        self._frame_updated = False
        self.language = "ZH_CN"
        self.theme = "DARK"

    def palette(self, theme=None):
        theme = theme or self.theme
        if theme == "LIGHT":
            return (0xF1F5F7, 0xFFFFFF, 0x17242B, 0x607179,
                    0x087E72, 0xD6EFEB, 0xB42318)
        return (0x0B1117, 0x121C24, 0xEDF7F5, 0x91A7AD,
                0x35D0BA, 0x173C3B, 0xFF7A86)

    def text(self, value, x, y, color=0x101318, width=320,
             background=0xFFFFFF, clear_background=True, height=16):
        value = str(value).replace("\r", " ").replace("\n", " ")
        height = min(height, 240 - y)
        if clear_background and width > 0 and height > 0:
            hpprime.fillrect(self._target, x, y, width, height, background, background)
        hpprime.textout(self._target, x, y, value, color)

    def clear(self, color=None):
        if color is None:
            color = self.palette()[0]
        hpprime.fillrect(0, 0, 0, 320, 240, color, color)
        self._target = 0
        self._view = None
        self._signature = None
        self._play_mode = None
        self._play_lines = [None, None, None, None]
        self._fps_line = None
        self._frame_updated = False

    def video_frame_updated(self):
        # A fresh RGB frame needs a new composition even if its text is unchanged.
        self._play_lines = [None, None, None, None]
        self._fps_line = None
        self._frame_updated = True

    @staticmethod
    def video_bottom(debug_mode):
        # Video and overlays share the full offscreen composition.
        return 239

    def list(self, model):
        self.language = model.settings.language
        self.theme = model.settings.theme
        background, card, foreground, muted, accent, selection, danger = self.palette()
        first = (max(0, min(model.selected - 5, len(model.files) - 10))
                 if model.files else 0)
        signature = (model.selected, model.mode, len(model.files), first,
                     model.settings.as_tuple())
        if self._view == "LIST" and self._signature == signature:
            return
        if self._view != "LIST":
            self.clear(background)
        else:
            hpprime.fillrect(0, 0, 0, 320, 218, background, background)
        self.text("PrimeVideoPlayer 1.1.1", 10, 5, accent, 300, background)
        self.text(tr(self.language, "files", len(model.files)), 10, 23,
                  muted, 300, background)
        hpprime.fillrect(0, 6, 38, 308, 176, card, card)
        if not model.files:
            self.text(tr(self.language, "no_files"), 16, 70, danger, 288,
                      card)
            self._view, self._signature = "LIST", signature
        else:
            canvas = self._text_canvas_factory()
            try:
                canvas.start()
                for row, index in enumerate(range(first, min(first + 9,
                                                              len(model.files)))):
                    entry = model.files[index]
                    chosen = index == model.selected
                    y = 42 + row * 19
                    row_background = selection if chosen else card
                    hpprime.fillrect(0, 9, y, 302, 18, row_background,
                                     row_background)
                    size_kib = (entry.size + 1023) // 1024
                    canvas.draw(entry.name, 14, y + 1, foreground, row_background)
                    self.text("%s %dK" % (entry.extension[1:], size_kib),
                              232, y + 1, accent if chosen else muted, 76,
                              row_background, False, 16)
            finally:
                canvas.close()
        footer = tr(self.language, "list_help")
        self.text(footer, 6, 222, muted, 308, background)
        self._view, self._signature = "LIST", signature

    def settings(self, model):
        draft = model.settings_draft
        self.language, self.theme = draft.language, draft.theme
        background, card, foreground, muted, accent, selection, danger = self.palette()
        signature = (model.settings_selected, draft.as_tuple())
        if self._view == "SETTINGS" and self._signature == signature:
            return
        self.clear(background)
        self.text(tr(self.language, "settings_title"), 10, 6, accent, 300,
                  background)
        for row, key in enumerate(SETTING_KEYS):
            y = 36 + row * 29
            chosen = row == model.settings_selected
            row_background = selection if chosen else card
            hpprime.fillrect(0, 8, y, 304, 25, row_background, row_background)
            self.text(tr(self.language, key), 14, y + 4, foreground, 142,
                      row_background, False, 17)
            value = getattr(draft, key)
            self.text(tr(self.language, value), 160, y + 4,
                      accent if chosen else muted, 145, row_background,
                      False, 17)
        footer = tr(self.language, "settings_help")
        self.text(footer, 8, 222, muted, 304, background)
        self._view, self._signature = "SETTINGS", signature

    def playback(self, entry, session, model, paused=False):
        self.language, self.theme = (model.settings.language,
                                     model.settings.theme)
        debug_mode = model.debug_mode
        session.set_video_bottom(self.video_bottom(debug_mode))
        if not session.current_frame:
            return
        # The player never calls this for a skipped playing frame. Paused and
        # seeking views may update independently, always from a clean RGB frame.
        position = (model.seek_target if model.state == PlayerState.SEEKING
                    else session.position_tenths)
        fps_tenths = (0 if paused or model.state == PlayerState.SEEKING else
                      getattr(session, "display_fps_tenths", 0))
        signature = (entry.name, debug_mode, model.state, position, fps_tenths,
                     session.frames, session.bytes_read, session.late_frames,
                     model.mode, self.language, self.theme)
        if (self._view == "PLAYBACK" and self._signature == signature and
                not self._frame_updated):
            return
        if debug_mode == DebugMode.OFF:
            # With no overlay there is no intermediate UI state to expose.
            session.present_current()
        else:
            self._target = session.begin_composition()
            try:
                self._draw_overlay(entry, session, model, paused,
                                   position, fps_tenths)
            finally:
                self._target = 0
                session.end_composition()
            # No physical screen write is permitted until all UI is complete.
            session.present_composition()
        self._view = "PLAYBACK"
        self._play_mode = debug_mode
        self._signature = signature
        self._frame_updated = False

    def _draw_overlay(self, entry, session, model, paused, position, fps_tenths):
        background, card, foreground, muted, accent, selection, danger = self.palette()
        fps_line = "FPS:%d.%d" % (fps_tenths // 10, fps_tenths % 10)
        if model.debug_mode == DebugMode.PROGRESS:
            hpprime.fillrect(self._target, 6, 218, 308, 4, muted, muted)
            width = position * 308 // 1000
            if width:
                hpprime.fillrect(self._target, 6, 218, width, 4, accent, accent)
            label = ((tr(self.language, "seeking") + " %d.%d%%")
                     if model.state == PlayerState.SEEKING
                     else "%d.%d%%") % (position // 10, position % 10)
            self.text(label, 6, 224, foreground, 308, background, False, 15)
        else:
            total = session.total_frames
            frame_text = ("%d/%d" % (session.frames, total) if total is not None
                          else "%d" % session.frames)
            if model.state == PlayerState.SEEKING:
                status = tr(self.language, "seek_help", position // 10,
                            position % 10)
            else:
                status = tr(self.language, "play_help",
                    tr(self.language, "pause") if paused else
                    tr(self.language, "playing"), tr(self.language, model.mode),
                    tr(self.language, "play") if paused else
                    tr(self.language, "pause"))
            presented = getattr(session, "presented_frames", session.frames)
            dropped = getattr(session, "dropped_frames", 0)
            lines = (
                entry.name[:39],
                tr(self.language, "detail_time", entry.extension[1:], frame_text,
                   session.source_ms),
                tr(self.language, "detail_stats",
                   (session.bytes_read + 1023) // 1024,
                   (entry.size + 1023) // 1024, position // 10, position % 10,
                   session.late_frames, presented, dropped),
                status[:39],
            )
            colors = (foreground, foreground, foreground, accent)
            for row, line in enumerate(lines):
                y = 180 + row * 15
                hpprime.fillrect(self._target, 0, y, 320, 15, background, background)
                self.text(line, 3, y, colors[row], 314, background, False, 15)
        fps_x = max(246, 316 - len(fps_line) * 8)
        self.text(fps_line, fps_x, 2, 0xFFFFFF, 320 - fps_x,
                  background, False, 15)

    def error(self, message):
        signature = str(message)
        if self._view == "ERROR" and self._signature == signature:
            return
        background, card, foreground, muted, accent, selection, danger = self.palette()
        self.clear(background)
        settings_error = signature.startswith("SETTINGS_STORE_INVALID")
        memory_error = ("MPEG_OUT_OF_MEMORY" in signature or
                        "CREATE_FAILED" in signature)
        title = tr(self.language, "settings_error" if settings_error else
                   "playback_error")
        self.text(title, 10, 7, danger, 300,
                  background)
        hpprime.fillrect(0, 8, 32, 304, 174, card, card)
        words = ((tr(self.language, "memory_error") + " | " + signature)
                 if memory_error else signature)
        for row in range(8):
            if not words:
                break
            self.text(words[:38], 14, 38 + row * 18, foreground, 292, card)
            words = words[38:]
        footer = (tr(self.language, "reset_settings") if settings_error else
                  "ENTER/ESC: " + tr(self.language, "return_list"))
        self.text(footer, 8, 220,
                  muted, 304, background)
        self._view, self._signature = "ERROR", signature
