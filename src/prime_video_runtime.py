"""Verified bridge and direct-hpprime compact G1 player UI."""

import hpprime
import prime_native as native
import prime_video_profile as profile
from prime_video_model import DebugMode, PlayerState

Error = native.Error
struct = native.struct
_last_keyboard = 0
_repeat_bit = None
_repeat_event = None
_repeat_started = None
_repeat_last = None

KEY_REPEAT_DELAY_MS = 320
KEY_REPEAT_INTERVAL_MS = 40
LIST_BACKGROUND = 0x101214
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

    def text(self, value, x, y, color=0x101318, width=320,
             background=0xFFFFFF, clear_background=True, height=16):
        value = str(value).replace("\r", " ").replace("\n", " ")
        height = min(height, 240 - y)
        if clear_background and width > 0 and height > 0:
            hpprime.fillrect(0, x, y, width, height, background, background)
        hpprime.textout(0, x, y, value, color)

    def clear(self, color=0xFFFFFF):
        hpprime.fillrect(0, 0, 0, 320, 240, color, color)
        self._view = None
        self._signature = None
        self._play_mode = None
        self._play_lines = [None, None, None, None]

    def video_frame_updated(self):
        # A decoded frame can overwrite the panel even when its text is unchanged.
        self._play_lines = [None, None, None, None]

    @staticmethod
    def video_bottom(debug_mode):
        if debug_mode == DebugMode.FULL:
            return 179
        if debug_mode == DebugMode.PROGRESS:
            return 217
        return 239

    def list(self, model):
        first = (max(0, min(model.selected - 5, len(model.files) - 10))
                 if model.files else 0)
        signature = (model.selected, model.mode, len(model.files), first)
        if self._view == "LIST" and self._signature == signature:
            return
        if self._view != "LIST":
            self.clear(LIST_BACKGROUND)
        else:
            hpprime.fillrect(0, 0, 16, 320, 208, LIST_BACKGROUND,
                             LIST_BACKGROUND)
        self.text("PrimeVideoPlayer 1.0.0", 4, 4, LIST_ACCENT, 312,
                  LIST_BACKGROUND)
        self.text("%d file(s)  end:%s" % (len(model.files), model.mode),
                  4, 20, LIST_MUTED, 312, LIST_BACKGROUND)
        if not model.files:
            self.text("No .M1V or .MJPG files", 4, 54, 0xFF6B6B, 312,
                      LIST_BACKGROUND)
            self.text("ESC: exit", 4, 72, LIST_MUTED, 312,
                      LIST_BACKGROUND)
            self._view, self._signature = "LIST", signature
            return
        for row, index in enumerate(range(first, min(first + 10,
                                                      len(model.files)))):
            entry = model.files[index]
            marker = ">" if index == model.selected else " "
            size_kib = (entry.size + 1023) // 1024
            self.text("%s %-22s %5dK" %
                      (marker, entry.name[:22], size_kib), 4, 40 + row * 16,
                      0xFFFFFF if index == model.selected else LIST_TEXT,
                      312,
                      LIST_SELECTION if index == model.selected else
                      LIST_BACKGROUND)
        self.text("ENTER play  ESC exit  HELP end mode", 4, 224,
                  LIST_MUTED, 312, LIST_BACKGROUND)
        self._view, self._signature = "LIST", signature

    def playback(self, entry, session, model, paused=False):
        debug_mode = model.debug_mode
        session.set_video_bottom(self.video_bottom(debug_mode))
        if self._view != "PLAYBACK" or self._play_mode != debug_mode:
            self._play_lines = [None, None, None, None]
            self._play_mode = debug_mode
        self._view = "PLAYBACK"
        self._signature = None
        if debug_mode == DebugMode.OFF:
            return

        position = (model.seek_target if model.state == PlayerState.SEEKING
                    else session.position_tenths)
        if debug_mode == DebugMode.PROGRESS:
            signature = (position, model.state)
            if self._play_lines[0] == signature:
                return
            hpprime.fillrect(0, 0, 218, 320, 22, 0, 0)
            hpprime.fillrect(0, 4, 218, 308, 3, 0x30343B, 0x30343B)
            width = position * 308 // 1000
            if width:
                hpprime.fillrect(0, 4, 218, width, 3, 0x19A974, 0x19A974)
            label = ("SEEK %d.%d%%" if model.state == PlayerState.SEEKING
                     else "%d.%d%%") % (position // 10, position % 10)
            self.text(label, 4, 222, 0xFFFFFF, 312, 0, False, 15)
            self._play_lines[0] = signature
            return

        total = session.total_frames
        frame_text = ("%d/%d" % (session.frames, total) if total is not None
                      else "%d" % session.frames)
        if model.state == PlayerState.SEEKING:
            status = "SEEK %d.%d%% U/D:.1 L/R:5 ENT:go" % (
                position // 10, position % 10)
        else:
            status = "%s %s ENT:pause ESC:list HELP:ui" % (
                "PAUSE" if paused else "PLAY", model.mode)
        lines = (
            entry.name[:39],
            "%s f:%s t:%dms" %
            (entry.extension[1:], frame_text, session.source_ms),
            "r:%d/%dK pos:%d.%d%% late:%d" %
            ((session.bytes_read + 1023) // 1024,
             (entry.size + 1023) // 1024, position // 10, position % 10,
             session.late_frames),
            status[:39],
        )
        colors = (0xFFFFFF, 0xFFFFFF, 0xFFFFFF, 0xF9C74F)
        for row, line in enumerate(lines):
            if self._play_lines[row] == line:
                continue
            y = 180 + row * 15
            hpprime.fillrect(0, 0, y, 320, 15, 0, 0)
            self.text(line, 3, y, colors[row], 314, 0, False, 15)
            self._play_lines[row] = line

    def error(self, message):
        signature = str(message)
        if self._view == "ERROR" and self._signature == signature:
            return
        self.clear()
        self.text("Playback error", 4, 6, 0xB42318, 312)
        words = str(message)
        for row in range(8):
            if not words:
                break
            self.text(words[:38], 4, 32 + row * 18, 0x101318, 312)
            words = words[38:]
        self.text("ENTER/ESC: return to list", 4, 220, 0x30343B, 312)
        self._view, self._signature = "ERROR", signature
