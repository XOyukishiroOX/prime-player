"""Small strict playback-position store using MicroPython FileIO only."""

import prime_native as native
import prime_video_profile as profile

Error = native.Error
MAGIC = b"PVPOS1\n"
MAX_BYTES = 32768


def encode_positions(records):
    lines = [MAGIC]
    for path in sorted(records):
        size, tenths = records[path]
        if (not isinstance(path, str) or "\t" in path or "\n" in path or
                not isinstance(size, int) or not 0 <= size <= 0xFFFFFFFF or
                not isinstance(tenths, int) or not 1 <= tenths <= 999):
            raise Error("POSITION_RECORD_INVALID")
        lines.append(("%d\t%d\t%s\n" % (size, tenths, path)).encode("utf-8"))
    payload = b"".join(lines)
    if len(payload) > MAX_BYTES:
        raise Error("POSITION_STORE_TOO_LARGE")
    return payload


def decode_positions(payload):
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > MAX_BYTES:
        raise Error("POSITION_STORE_INVALID")
    payload = bytes(payload)
    if not payload.startswith(MAGIC):
        raise Error("POSITION_STORE_BAD_MAGIC")
    records = {}
    for raw_line in payload[len(MAGIC):].splitlines():
        if not raw_line:
            continue
        try:
            size_text, tenths_text, path = raw_line.decode("utf-8").split("\t", 2)
            size, tenths = int(size_text), int(tenths_text)
        except BaseException:
            raise Error("POSITION_STORE_BAD_RECORD")
        if (path in records or not path or not 0 <= size <= 0xFFFFFFFF or
                not 1 <= tenths <= 999):
            raise Error("POSITION_STORE_BAD_RECORD")
        records[path] = (size, tenths)
    if len(records) > profile.MAX_FILES:
        raise Error("POSITION_STORE_RECORD_LIMIT")
    return records


class PositionStore:
    def __init__(self, path=profile.POSITION_FILE, opener=None):
        self.path = path
        self.opener = opener or native.uio.FileIO
        self.records = {}

    def load(self):
        try:
            stream = self.opener(self.path, "rb")
        except OSError:
            self.records = {}
            return self.records
        try:
            payload = stream.read(MAX_BYTES + 1)
        finally:
            stream.close()
        self.records = decode_positions(payload)
        return self.records

    def get(self, entry):
        record = self.records.get(entry.path)
        return record[1] if record is not None and record[0] == entry.size else 0

    def set(self, entry, tenths):
        tenths = int(tenths)
        if 1 <= tenths <= 999:
            self.records[entry.path] = (entry.size, tenths)
        else:
            self.records.pop(entry.path, None)
        self.save()

    def clear(self, entry):
        if entry.path in self.records:
            del self.records[entry.path]
            self.save()

    def save(self):
        payload = encode_positions(self.records)
        stream = self.opener(self.path, "wb")
        try:
            if stream.write(payload) != len(payload):
                raise Error("POSITION_STORE_SHORT_WRITE")
        finally:
            stream.close()
        stream = self.opener(self.path, "rb")
        try:
            actual = stream.read(len(payload) + 1)
        finally:
            stream.close()
        if actual != payload:
            raise Error("POSITION_STORE_READBACK_MISMATCH")
