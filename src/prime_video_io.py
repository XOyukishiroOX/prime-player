"""Strict native file reader for dynamically discovered UTF-16 paths."""

import ustruct as struct

import prime_native as native
from prime_video_files import utf16le_z

Error = native.Error


class NativeFile:
    def __init__(self, dbg, images, scratch_address, scratch_bytes, entry):
        self.dbg = dbg
        self.images = images
        self.scratch_address = scratch_address
        self.scratch_bytes = scratch_bytes
        self.entry = entry
        self.handle = None
        self.position = 0
        images.contains(scratch_address, scratch_bytes)

    def open(self):
        if self.handle is not None:
            raise Error("FILE_ALREADY_OPEN")
        path = utf16le_z(self.entry.path)
        mode_offset = (len(path) + 3) & ~3
        if mode_offset + 8 > self.scratch_bytes:
            raise Error("NATIVE_PATH_TOO_LONG")
        payload = bytearray(mode_offset + 8)
        payload[:len(path)] = path
        struct.pack_into("<HHHH", payload, mode_offset, 114, 98, 0, 0)
        self.images.write(self.scratch_address, payload)
        handle = self.dbg.raw("open", self.scratch_address,
                              self.scratch_address + mode_offset)
        if not handle:
            raise Error("NATIVE_OPEN_FAILED " + self.entry.path)
        self.images.trusted(handle, 0x2C)
        self.handle = handle
        self.position = 0

    def read_exact_to(self, destination, size):
        if self.handle is None:
            raise Error("FILE_NOT_OPEN")
        if not isinstance(size, int) or size <= 0:
            raise Error("NATIVE_READ_SIZE_INVALID")
        if self.position + size > self.entry.size:
            raise Error("NATIVE_FILE_TRUNCATED declared=%d requested_end=%d" %
                        (self.entry.size, self.position + size))
        self.images.contains(destination, size)
        count = self.dbg.raw("read_file", destination, 1, size, self.handle)
        if count != size:
            raise Error("NATIVE_SHORT_READ %d/%d at=%d" %
                        (count, size, self.position))
        self.position += size
        return size

    def read_small(self, size):
        if size > self.scratch_bytes:
            raise Error("NATIVE_SMALL_READ_TOO_LARGE")
        self.read_exact_to(self.scratch_address, size)
        return self.dbg.read(self.scratch_address, size)

    def read_owned_bytes(self, address, size):
        self.images.contains(address, size)
        chunks = []
        for offset in range(0, size, 8192):
            chunks.append(self.dbg.read(address + offset,
                                        min(8192, size - offset)))
        return b"".join(chunks)

    def seek_absolute(self, offset):
        if self.handle is None:
            raise Error("FILE_NOT_OPEN")
        if not isinstance(offset, int) or not 0 <= offset <= self.entry.size:
            raise Error("NATIVE_SEEK_OFFSET_INVALID")
        result = self.dbg.raw("seek", self.handle, offset, 0)
        if result != 0:
            raise Error("NATIVE_SEEK_FAILED offset=%d result=0x%x" %
                        (offset, result))
        self.position = offset
        return offset

    def verify_eof(self):
        if self.handle is None:
            raise Error("FILE_NOT_OPEN")
        if self.position != self.entry.size:
            raise Error("NATIVE_FILE_SIZE_MISMATCH %d/%d" %
                        (self.position, self.entry.size))
        self.images.contains(self.scratch_address, 1)
        if self.dbg.raw("read_file", self.scratch_address, 1, 1,
                        self.handle) != 0:
            raise Error("NATIVE_FILE_GREW_AFTER_SCAN")

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            result = self.dbg.raw("close_file", handle)
            if result != 0:
                raise Error("NATIVE_CLOSE_FAILED 0x%x; no retry" % result)
