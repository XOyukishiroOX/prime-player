"""Strict host-testable file discovery for PrimeVideoPlayer."""

import ustruct as struct

import prime_native as native
from prime_video_model import FileEntry
import prime_video_profile as profile

Error = native.Error


def utf16le_z(text, max_units=None):
    if not isinstance(text, str):
        raise Error("UTF16_PATH_NOT_TEXT")
    values = []
    for character in text:
        value = ord(character)
        if value == 0:
            raise Error("UTF16_PATH_CONTAINS_NUL")
        if value <= 0xFFFF:
            if 0xD800 <= value <= 0xDFFF:
                raise Error("UTF16_PATH_UNPAIRED_SURROGATE")
            values.append(value)
        elif value <= 0x10FFFF:
            value -= 0x10000
            values.extend((0xD800 | (value >> 10), 0xDC00 | (value & 0x3FF)))
        else:
            raise Error("UTF16_PATH_CODEPOINT_INVALID")
    if max_units is not None and len(values) > max_units:
        raise Error("UTF16_PATH_TOO_LONG %d/%d" % (len(values), max_units))
    data = bytearray((len(values) + 1) * 2)
    for index, value in enumerate(values):
        struct.pack_into("<H", data, index * 2, value)
    return data


def decode_utf16le_z(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) & 1:
        raise Error("UTF16_NAME_BUFFER_INVALID")
    result = []
    index = 0
    while index < len(data):
        value = struct.unpack_from("<H", data, index)[0]
        index += 2
        if value == 0:
            return "".join(result)
        if 0xD800 <= value <= 0xDBFF:
            if index >= len(data):
                raise Error("UTF16_NAME_SURROGATE_TRUNCATED")
            low = struct.unpack_from("<H", data, index)[0]
            index += 2
            if not 0xDC00 <= low <= 0xDFFF:
                raise Error("UTF16_NAME_SURROGATE_INVALID")
            result.append(chr(0x10000 + ((value - 0xD800) << 10) + low - 0xDC00))
        elif 0xDC00 <= value <= 0xDFFF:
            raise Error("UTF16_NAME_SURROGATE_INVALID")
        else:
            result.append(chr(value))
    raise Error("UTF16_NAME_UNTERMINATED")


def supported_extension(name):
    if not isinstance(name, str) or name in ("", ".", ".."):
        return None
    dot = name.rfind(".")
    if dot < 0:
        return None
    extension = name[dot:].upper()
    return extension if extension in (".M1V", ".MJPG") else None


def collect_files(records, app_dir=profile.APP_DIR):
    entries = []
    for name, size, attributes in records:
        extension = supported_extension(name)
        if extension is None or attributes & profile.IGNORED_ATTRIBUTES:
            continue
        if not isinstance(size, int) or not 0 <= size <= 0xFFFFFFFF:
            raise Error("SCAN_FILE_SIZE_INVALID " + repr(name))
        if len(entries) >= profile.MAX_FILES:
            raise Error("SCAN_FILE_LIMIT_EXCEEDED %d" % profile.MAX_FILES)
        entries.append(FileEntry(name, app_dir + name, extension, size))
    entries.sort(key=lambda item: item.name.lower())
    return tuple(entries)


class NativeDirectoryScanner:
    """Call only the verified G1 wide find ABI; no Python filesystem fallback."""

    PATTERN_OFFSET = 0
    CONTEXT_OFFSET = 640
    SCRATCH_BYTES = 1024

    def __init__(self, dbg, images, scratch):
        self.dbg = dbg
        self.images = images
        self.base = scratch[4]
        images.contains(self.base, self.SCRATCH_BYTES)

    def _read_name(self, address):
        if not address or address & 1:
            raise Error("SCAN_LFN_POINTER_INVALID 0x%x" % address)
        size = (profile.MAX_FILENAME_UNITS + 1) * 2
        native.ram_range(address, size)
        return decode_utf16le_z(self.dbg.read(address, size))

    def _record(self):
        context = self.dbg.read(self.base + self.CONTEXT_OFFSET,
                                profile.FIND_CONTEXT_BYTES)
        pointer = struct.unpack_from("<I", context,
                                     profile.FIND_LFN_POINTER_OFFSET)[0]
        size = struct.unpack_from("<I", context, profile.FIND_SIZE_OFFSET)[0]
        attributes = context[profile.FIND_ATTRIBUTES_OFFSET]
        return self._read_name(pointer), size, attributes

    def scan(self):
        pattern = utf16le_z(profile.SCAN_PATTERN, 319)
        payload = bytearray(self.SCRATCH_BYTES)
        payload[:len(pattern)] = pattern
        self.images.write(self.base, payload)
        context_address = self.base + self.CONTEXT_OFFSET
        result = self.dbg.raw("find_first", self.base + self.PATTERN_OFFSET,
                              context_address, 0)
        if result == 0xFFFFFFFF:
            return ()
        if result != 0:
            raise Error("SCAN_FIND_FIRST_FAILED 0x%x" % result)
        records = []
        primary = None
        close_error = None
        try:
            while True:
                records.append(self._record())
                result = self.dbg.raw("find_next", context_address)
                if result == 0xFFFFFFFF:
                    break
                if result != 0:
                    raise Error("SCAN_FIND_NEXT_FAILED 0x%x" % result)
        except BaseException as exc:
            primary = exc
        try:
            result = self.dbg.raw("find_close", context_address)
            if result != 0:
                raise Error("SCAN_FIND_CLOSE_FAILED 0x%x; no retry" % result)
        except BaseException as exc:
            close_error = exc
        if primary is not None:
            if close_error is not None:
                raise Error(str(primary) + "; CLEANUP: " + str(close_error))
            raise primary
        if close_error is not None:
            raise close_error
        return collect_files(records)
