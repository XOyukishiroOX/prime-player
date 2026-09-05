"""Host-testable player data model and logical event contract."""


class FileEntry:
    __slots__ = ("name", "path", "extension", "size")

    def __init__(self, name, path, extension, size):
        self.name = name
        self.path = path
        self.extension = extension
        self.size = size

    def __repr__(self):
        return "FileEntry(%r, %r, %r, %d)" % (
            self.name, self.path, self.extension, self.size)


class PlaybackMode:
    ONCE = "ONCE"
    SINGLE = "SINGLE"
    ALL = "ALL"


class DebugMode:
    OFF = "OFF"
    PROGRESS = "PROGRESS"
    FULL = "FULL"


class PlayerState:
    LIST = "LIST"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    SEEKING = "SEEKING"
    ERROR = "ERROR"


class PlayerModel:
    """Logical state transitions; no firmware key codes or I/O."""

    def __init__(self, files):
        self.files = tuple(files)
        self.selected = 0
        self.index = 0
        self.mode = PlaybackMode.ONCE
        self.debug_mode = DebugMode.PROGRESS
        self.state = PlayerState.LIST
        self.error = None
        self.seek_target = None
        self.seek_return_state = None

    def _cycle_playback_mode(self):
        if self.mode == PlaybackMode.ONCE:
            self.mode = PlaybackMode.SINGLE
        elif self.mode == PlaybackMode.SINGLE:
            self.mode = PlaybackMode.ALL
        else:
            self.mode = PlaybackMode.ONCE

    def _cycle_debug_mode(self):
        if self.debug_mode == DebugMode.OFF:
            self.debug_mode = DebugMode.PROGRESS
        elif self.debug_mode == DebugMode.PROGRESS:
            self.debug_mode = DebugMode.FULL
        else:
            self.debug_mode = DebugMode.OFF

    @staticmethod
    def _clamp_tenths(value):
        return max(0, min(999, int(value)))

    def event(self, name, position_tenths=None):
        if self.state == PlayerState.LIST:
            if name == "UP" and self.files:
                self.selected = (self.selected - 1) % len(self.files)
            elif name == "DOWN" and self.files:
                self.selected = (self.selected + 1) % len(self.files)
            elif name == "ENTER" and self.files:
                self.index = self.selected
                self.state = PlayerState.PLAYING
                return "START"
            elif name == "HELP":
                self._cycle_playback_mode()
            elif name == "BACK":
                return "EXIT"
        elif self.state in (PlayerState.PLAYING, PlayerState.PAUSED):
            if name == "ENTER":
                self.state = (PlayerState.PLAYING if
                              self.state == PlayerState.PAUSED else
                              PlayerState.PAUSED)
                return ("RESUME" if self.state == PlayerState.PLAYING else
                        "PAUSE")
            elif name == "BACK":
                self.state = PlayerState.LIST
                self.selected = self.index
                return "STOP"
            elif name == "LEFT" and self.files:
                self.index = (self.index - 1) % len(self.files)
                self.state = PlayerState.PLAYING
                return "SWITCH"
            elif name == "RIGHT" and self.files:
                self.index = (self.index + 1) % len(self.files)
                self.state = PlayerState.PLAYING
                return "SWITCH"
            elif name in ("UP", "DOWN"):
                if position_tenths is None:
                    return None
                self.seek_return_state = self.state
                self.state = PlayerState.SEEKING
                delta = 1 if name == "UP" else -1
                self.seek_target = self._clamp_tenths(position_tenths + delta)
                return "SEEK_BEGIN"
            elif name == "HELP":
                self._cycle_debug_mode()
                return "DEBUG"
        elif self.state == PlayerState.SEEKING:
            if name == "UP":
                self.seek_target = self._clamp_tenths(self.seek_target + 1)
            elif name == "DOWN":
                self.seek_target = self._clamp_tenths(self.seek_target - 1)
            elif name == "LEFT":
                self.seek_target = self._clamp_tenths(self.seek_target - 50)
            elif name == "RIGHT":
                self.seek_target = self._clamp_tenths(self.seek_target + 50)
            elif name == "ENTER":
                self.state = self.seek_return_state
                self.seek_return_state = None
                return "SEEK"
            elif name == "BACK":
                self.state = self.seek_return_state
                self.seek_return_state = None
                self.seek_target = None
                return "SEEK_CANCEL"
            elif name == "HELP":
                self._cycle_debug_mode()
                return "DEBUG"
        elif self.state == PlayerState.ERROR and name in ("ENTER", "BACK"):
            self.state = PlayerState.LIST
            self.error = None
        return None

    def finished(self):
        if not self.files or self.state not in (PlayerState.PLAYING,
                                                PlayerState.PAUSED):
            return None
        self.state = PlayerState.PLAYING
        if self.mode == PlaybackMode.ONCE:
            self.state = PlayerState.LIST
            self.selected = self.index
            return "DONE"
        if self.mode == PlaybackMode.SINGLE:
            return "RESTART"
        self.index = (self.index + 1) % len(self.files)
        return "NEXT"

    def fail(self, message):
        self.state = PlayerState.ERROR
        self.error = str(message)
