"""Compose video and the stock hpprime UI before a single LCD submission."""

import prime_native as native
import prime_video_grob_profile as profile

struct = native.struct
Error = native.Error
GUARD = b"\xa5" * 32


class FrameCompositor:
    """Own the pixels and descriptor; borrow G9 only during synchronous drawing.

    The 48-byte application image layout matches the stock dimgrob constructor.
    No application allocator/destructor is used for these caller-owned objects.
    The original G9 pointer and its contents are preserved, including on errors.
    """

    def __init__(self, images, width=320, height=240):
        if not (32 <= width <= 320 and 1 <= height <= 240):
            raise Error("COMPOSITOR_DIMENSIONS_INVALID")
        self.images = images
        self.dbg = images.dbg
        self.width, self.height = width, height
        self.frame_bytes = width * height * 4
        self.bound = False
        self.ready = False
        self.previous = None

    def start(self):
        for address, expected in profile.CHECKS:
            if self.dbg.read(address, len(expected)) != expected:
                raise Error("COMPOSITOR_FIRMWARE_MISMATCH 0x%x" % address)
        backing = self.images.create(self.width, self.height + 1)
        self.pixels = (backing[4] + 95) & ~31
        self.header = self.pixels - 20
        self.images.contains(self.pixels - 52, self.frame_bytes + 84)
        self.images.write(self.pixels - 52, GUARD)
        self.images.write(self.header, struct.pack(
            "<2shhhhhII", b"PX", self.width, self.height, 32,
            self.width * 4, 2, 0, self.pixels))
        self.images.write(self.pixels + self.frame_bytes, GUARD)
        descriptor = self.images.create(64, 1)
        self.object = descriptor[4] + 32
        words = [0] * 12
        words[0] = profile.IMAGE_VTABLE
        words[3:6] = (self.width, self.height, self.pixels)
        self.descriptor_bytes = struct.pack("<12I", *words)
        self.images.write(self.object - 32, GUARD)
        self.images.write(self.object, self.descriptor_bytes)
        self.images.write(self.object + 48, GUARD)
        self.ready = True

    def _slot(self):
        return struct.unpack("<I", self.dbg.read(profile.GROB_SLOT, 4))[0]

    def _set_slot(self, pointer):
        # This single guarded firmware slot is the only non-owned write.
        self.dbg.packet(struct.pack("<III", 1, profile.GROB_SLOT, pointer))
        if self._slot() != pointer:
            raise Error("COMPOSITOR_GROB_SLOT_WRITE_FAILED")

    def begin(self, source):
        if not self.ready or self.bound:
            raise Error("COMPOSITOR_STATE_INVALID")
        self.images.contains(source, self.frame_bytes)
        self.images.contains(self.pixels, self.frame_bytes)
        self.dbg.invoke(profile.COPY_ADDRESS,
                        (self.pixels, source, self.frame_bytes))
        return self.bind()

    def bind(self):
        """Bind without copying; caller must clear the pixels before drawing."""
        if not self.ready or self.bound:
            raise Error("COMPOSITOR_STATE_INVALID")
        self.previous = self._slot()
        # Mark before the write so even a failed readback can be unwound.
        self.bound = True
        try:
            self._set_slot(self.object)
        except BaseException:
            self.end()
            raise
        return profile.GROB

    def end(self):
        if self.bound:
            self._set_slot(self.previous)
            self.bound = False
            self.previous = None

    def present(self, x=0, y=0):
        if not self.ready or self.bound:
            raise Error("COMPOSITOR_NOT_FINISHED")
        if not (0 <= x <= 320 - self.width and 0 <= y <= 240 - self.height):
            raise Error("COMPOSITOR_POSITION_INVALID")
        self.dbg.call("put", x, y, self.header, 0)

    def close(self):
        self.end()
        if self.ready:
            for address in (self.pixels - 52,
                            self.pixels + self.frame_bytes,
                            self.object - 32, self.object + 48):
                if self.dbg.read(address, 32) != GUARD:
                    raise Error("COMPOSITOR_BUFFER_GUARD_CHANGED")
            if self.dbg.read(self.object, 48) != self.descriptor_bytes:
                raise Error("COMPOSITOR_DESCRIPTOR_CHANGED")
        self.ready = False
