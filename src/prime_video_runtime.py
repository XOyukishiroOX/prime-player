"""Verified bridge and direct-hpprime compact G1 player UI."""

import hpprime
import prime_native as native
from prime_video_i18n import text as tr
import prime_video_profile as profile
from prime_video_model import DebugMode, PlayerState
from prime_video_settings import SETTING_KEYS

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


class PlayerScreen:
    def __init__(self):
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
            hpprime.fillrect(0, x, y, width, height, background, background)
        hpprime.textout(0, x, y, value, color)

    def clear(self, color=None):
        if color is None:
            color = self.palette()[0]
        hpprime.fillrect(0, 0, 0, 320, 240, color, color)
        self._view = None
        self._signature = None
        self._play_mode = None
        self._play_lines = [None, None, None, None]
        self._fps_line = None
        self._frame_updated = False

    def video_frame_updated(self):
        # A decoded frame can overwrite the panel even when its text is unchanged.
        self._play_lines = [None, None, None, None]
        self._fps_line = None
        self._frame_updated = True

    @staticmethod
    def video_bottom(debug_mode):
        # Overlays are drawn after presentation, on top of the full video.
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
        self.text("PrimeVideoPlayer 1.1.0", 10, 5, accent, 300, background)
        self.text(tr(self.language, "files", len(model.files)), 10, 23,
                  muted, 300, background)
        hpprime.fillrect(0, 6, 38, 308, 176, card, card)
        if not model.files:
            self.text(tr(self.language, "no_files"), 16, 70, danger, 288,
                      card)
            self._view, self._signature = "LIST", signature
        else:
            for row, index in enumerate(range(first, min(first + 9,
                                                          len(model.files)))):
                entry = model.files[index]
                chosen = index == model.selected
                y = 42 + row * 19
                row_background = selection if chosen else card
                hpprime.fillrect(0, 9, y, 302, 18, row_background,
                                 row_background)
                size_kib = (entry.size + 1023) // 1024
                self.text(entry.name[:23], 14, y + 1,
                          foreground, 214, row_background, False, 16)
                self.text("%s %dK" % (entry.extension[1:], size_kib),
                          232, y + 1, accent if chosen else muted, 76,
                          row_background, False, 16)
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
        background, card, foreground, muted, accent, selection, danger = self.palette()
        debug_mode = model.debug_mode
        session.set_video_bottom(self.video_bottom(debug_mode))
        mode_changed = (self._view != "PLAYBACK" or
                        self._play_mode != debug_mode)
        if mode_changed:
            if (self._view == "PLAYBACK" and not self._frame_updated and
                    getattr(session, "current_frame", False)):
                session.present_current()
            self._play_lines = [None, None, None, None]
            self._fps_line = None
            self._play_mode = debug_mode
        self._view = "PLAYBACK"
        self._signature = None
        if debug_mode == DebugMode.OFF:
            self._frame_updated = False
            return

        # A skipped decode must not cause an overlay-only screen update. The
        # next successfully presented frame will refresh both video and text.
        if (not self._frame_updated and not mode_changed and
                model.state == PlayerState.PLAYING):
            return

        position = (model.seek_target if model.state == PlayerState.SEEKING
                    else session.position_tenths)
        fps_tenths = (0 if paused or model.state == PlayerState.SEEKING else
                      getattr(session, "display_fps_tenths", 0))
        fps_line = "FPS:%d.%d" % (fps_tenths // 10, fps_tenths % 10)
        if debug_mode == DebugMode.PROGRESS:
            signature = (position, model.state, fps_line)
            if (self._play_lines[0] == signature and
                    self._fps_line == fps_line):
                self._frame_updated = False
                return
            if (not self._frame_updated and
                    getattr(session, "current_frame", False)):
                session.present_current()
            hpprime.fillrect(0, 6, 218, 308, 4, muted, muted)
            width = position * 308 // 1000
            if width:
                hpprime.fillrect(0, 6, 218, width, 4, accent, accent)
            label = ((tr(self.language, "seeking") + " %d.%d%%")
                     if model.state == PlayerState.SEEKING
                     else "%d.%d%%") % (position // 10, position % 10)
            self.text(label, 6, 224, foreground, 308, background, False, 15)
            fps_x = max(246, 316 - len(fps_line) * 8)
            self.text(fps_line, fps_x, 2, 0xFFFFFF, 320 - fps_x,
                      background, False, 15)
            self._play_lines[0] = signature
            self._fps_line = fps_line
            self._frame_updated = False
            return

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
        if (self._fps_line != fps_line and not self._frame_updated and
                getattr(session, "current_frame", False)):
            session.present_current()
            self._play_lines = [None, None, None, None]
        for row, line in enumerate(lines):
            if self._play_lines[row] == line:
                continue
            y = 180 + row * 15
            hpprime.fillrect(0, 0, y, 320, 15, background, background)
            self.text(line, 3, y, colors[row], 314, background, False, 15)
            self._play_lines[row] = line
        if self._fps_line != fps_line:
            fps_x = max(246, 316 - len(fps_line) * 8)
            self.text(fps_line, fps_x, 2, 0xFFFFFF, 320 - fps_x,
                      background, False, 15)
            self._fps_line = fps_line
        self._frame_updated = False

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
