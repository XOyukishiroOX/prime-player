"""Strict, versioned PrimeVideoPlayer settings."""

import prime_native as native

Error = native.Error
MAGIC = b"PVSET1\n"
MAX_BYTES = 1024
SETTING_KEYS = ("language", "theme", "scale", "overlay", "end_mode",
                "timing")
SETTING_VALUES = {
    "language": ("ZH_CN", "EN"),
    "theme": ("DARK", "LIGHT"),
    "scale": ("FIT", "ORIGINAL", "FILL", "STRETCH"),
    "overlay": ("OFF", "PROGRESS", "FULL"),
    "end_mode": ("ONCE", "SINGLE", "ALL"),
    "timing": ("SYNC", "COMPLETE"),
}
DEFAULTS = ("ZH_CN", "DARK", "FIT", "PROGRESS", "ONCE", "SYNC")


class PlayerSettings:
    __slots__ = SETTING_KEYS

    def __init__(self, language="ZH_CN", theme="DARK", scale="FIT",
                 overlay="PROGRESS", end_mode="ONCE", timing="SYNC"):
        values = (language, theme, scale, overlay, end_mode, timing)
        for key, value in zip(SETTING_KEYS, values):
            if value not in SETTING_VALUES[key]:
                raise Error("SETTING_VALUE_INVALID %s=%s" % (key, value))
            setattr(self, key, value)

    def copy(self):
        return PlayerSettings(*(getattr(self, key) for key in SETTING_KEYS))

    def cycle(self, key, delta):
        if key not in SETTING_VALUES or delta not in (-1, 1):
            raise Error("SETTING_CYCLE_INVALID")
        values = SETTING_VALUES[key]
        current = getattr(self, key)
        setattr(self, key, values[(values.index(current) + delta) % len(values)])

    def as_tuple(self):
        return tuple(getattr(self, key) for key in SETTING_KEYS)


def default_settings():
    return PlayerSettings(*DEFAULTS)


def encode_settings(settings):
    if not isinstance(settings, PlayerSettings):
        raise Error("SETTINGS_OBJECT_INVALID")
    lines = [MAGIC]
    for key in SETTING_KEYS:
        lines.append((key + "=" + getattr(settings, key) + "\n").encode("ascii"))
    payload = b"".join(lines)
    if len(payload) > MAX_BYTES:
        raise Error("SETTINGS_STORE_TOO_LARGE")
    return payload


def decode_settings(payload):
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > MAX_BYTES:
        raise Error("SETTINGS_STORE_INVALID")
    payload = bytes(payload)
    if not payload.startswith(MAGIC):
        raise Error("SETTINGS_STORE_BAD_MAGIC")
    values = {}
    ordered_keys = []
    for raw in payload[len(MAGIC):].splitlines():
        try:
            key, value = raw.decode("ascii").split("=", 1)
        except BaseException:
            raise Error("SETTINGS_STORE_BAD_RECORD")
        if key in values or key not in SETTING_VALUES or value not in SETTING_VALUES[key]:
            raise Error("SETTINGS_STORE_BAD_RECORD")
        values[key] = value
        ordered_keys.append(key)
    if tuple(ordered_keys) != SETTING_KEYS:
        raise Error("SETTINGS_STORE_MISSING_OR_REORDERED")
    return PlayerSettings(*(values[key] for key in SETTING_KEYS))


class SettingsStore:
    def __init__(self, path="prime_video_settings.dat", opener=None):
        self.path = path
        self.opener = opener or native.uio.FileIO

    def load(self):
        try:
            stream = self.opener(self.path, "rb")
        except OSError:
            return default_settings()
        try:
            payload = stream.read(MAX_BYTES + 1)
        finally:
            stream.close()
        return decode_settings(payload)

    def save(self, settings):
        payload = encode_settings(settings)
        stream = self.opener(self.path, "wb")
        try:
            if stream.write(payload) != len(payload):
                raise Error("SETTINGS_STORE_SHORT_WRITE")
        finally:
            stream.close()
        stream = self.opener(self.path, "rb")
        try:
            actual = stream.read(MAX_BYTES + 1)
        finally:
            stream.close()
        if actual != payload:
            raise Error("SETTINGS_STORE_READBACK_MISMATCH")
        return settings.copy()

    def reset(self):
        return self.save(default_settings())
