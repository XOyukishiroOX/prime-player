"""Minimal verified G1 runtime shared by the production player."""

import hpprime
import uio
import ustruct as struct

import mjpeg_decoder_profile
import prime_video_profile as profile


class PlayerError(Exception):
    pass


Error = PlayerError
BASE = 0x307FBCAC
API = {
    "active": (0x1008D, 0),
    "real": (0x10084, 0),
    "create": (0x1008F, 3),
    "put": (0x10072, 4),
    "free": (0x10099, 1),
}
ROM_CHECKS = (
    (0x3007E61C, b"\x5c\xf4\x07\x30"),
    (0x3002A40C,
     b"\x28\x08\x9f\xe5\x08\x00\x90\xe5\x08\x00\x90\xe5\x1e\xff\x2f\xe1"),
    (0x3002A41C,
     b"\x18\x08\x9f\xe5\x08\x00\x90\xe5\x00\x00\x90\xe5\x1e\xff\x2f\xe1"),
    (0x3002CE50, b"\x14\x00\x80\xe2\x1e\xff\x2f\xe1"),
)
CHUNK = 4096
FRAME_BYTES = 320 * 240 * 4


def ram_range(address, size):
    if not isinstance(address, int) or not isinstance(size, int):
        raise Error("RAM address/size must be integers")
    if (size <= 0 or address < 0x30000000 or address + size < address or
            address + size > 0x32000000):
        raise Error("RAM_RANGE 0x%x + %d" % (address, size))


def overlap(a, size_a, b, size_b):
    return a < b + size_b and b < a + size_a


class Bridge:
    """Verified display, file, cache and native-call bridge for one firmware."""

    def __init__(self, stream):
        self.stream = stream
        self.verified = False

    def packet(self, data):
        count = self.stream.write(data)
        if count != len(data):
            raise Error("SHORT_COMMAND %s/%d" % (count, len(data)))

    def read(self, address, size):
        ram_range(address, size)
        if size > 8192:
            raise Error("READ_LIMIT")
        self.packet(struct.pack("<III", 0, address, 0))
        data = self.stream.read(size)
        if data is None or len(data) != size:
            raise Error("SHORT_READ at 0x%x" % address)
        return data

    def verify(self):
        self.verified = False
        for name in API:
            ident = API[name][0]
            address = BASE + (ident - 0x10000) * 12
            expected = struct.pack("<III", 0xE92D0001, 0xE92D4000,
                                   0xEF000000 | ident)
            if self.read(address, 12) != expected:
                raise Error("STUB_MISMATCH " + name)
        for address, expected in ROM_CHECKS:
            if self.read(address, len(expected)) != expected:
                raise Error("ROM_MISMATCH 0x%x" % address)
        for ident, address, unused in profile.RAW_API.values():
            table = 0x3007F45C + (ident - 0x10000) * 4
            if self.read(table, 4) != struct.pack("<I", address):
                raise Error("RAW_DISPATCH_MISMATCH 0x%x" % ident)
        address, unused, guard = profile.SCREEN_ACTIVITY_API
        if self.read(address, len(guard)) != guard:
            raise Error("SCREEN_ACTIVITY_ROM_MISMATCH 0x%x" % address)
        for address, unused, expected in mjpeg_decoder_profile.CACHE_API.values():
            if self.read(address, len(expected)) != expected:
                raise Error("CACHE_ROM_MISMATCH 0x%x" % address)
        self.verified = True

    def call(self, name, *args):
        if not self.verified or name not in API or len(args) != API[name][1]:
            raise Error("BAD_API_ARGUMENTS " + name)
        ident = API[name][0]
        return self.invoke(BASE + (ident - 0x10000) * 12, args)

    def raw(self, name, *args):
        if (not self.verified or name not in profile.RAW_API or
                len(args) != profile.RAW_API[name][2]):
            raise Error("BAD_RAW_ARGUMENTS " + name)
        return self.invoke(profile.RAW_API[name][1], args)

    def invoke(self, address, args):
        if not self.verified or len(args) > 4:
            raise Error("NATIVE_CALL_NOT_VERIFIED")
        packet = bytearray(12 + 4 * len(args))
        struct.pack_into("<III", packet, 0, 2, address, len(args))
        for index, value in enumerate(args):
            if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
                raise Error("NATIVE_BAD_U32")
            struct.pack_into("<I", packet, 12 + index * 4, value)
        self.packet(packet)
        return struct.unpack_from("<I", packet, 0)[0]

    def maintenance(self, name, *args):
        cache = mjpeg_decoder_profile.CACHE_API
        if name not in cache or len(args) != cache[name][1]:
            raise Error("BAD_CACHE_API")
        result = self.invoke(cache[name][0], args)
        expected = args[0] if name == "clean_line" else 0
        if result != expected:
            raise Error("CACHE_RETURN_MISMATCH " + name)

    def close(self):
        self.verified = False
        self.stream.close()


def read_surface(dbg, address, width, height, expected_depth=None):
    ram_range(address, 20)
    if address & 3:
        raise Error("SURFACE_ALIGNMENT")
    magic, w, h, depth, pitch, encoding, palette, buffer = struct.unpack(
        "<2shhhhhII", dbg.read(address, 20))
    if magic != b"PX" or (w, h) != (width, height):
        raise Error("SURFACE_HEADER 0x%x" % address)
    if (depth not in (16, 32) or pitch != width * (depth // 8) or
            encoding != 2 or palette != 0 or
            (expected_depth is not None and depth != expected_depth)):
        raise Error("SURFACE_FORMAT depth=%d pitch=%d" % (depth, pitch))
    ram_range(buffer, pitch * height)
    if buffer & 3:
        raise Error("BUFFER_ALIGNMENT")
    return address, width, height, pitch, buffer, depth


def read_lcd(dbg, address):
    ram_range(address, 0x100)
    if address & 3:
        raise Error("LCD_ALIGNMENT")
    surface, pixel_end, pixel_size = struct.unpack("<III", dbg.read(address, 12))
    info = read_surface(dbg, surface, 320, 240)
    if pixel_size != info[3] * info[2] or pixel_end != info[4] + pixel_size:
        raise Error("LCD_BUFFER_BOUNDS")
    return info


class OwnedImages:
    """Only validated, owned image buffers may be written by native code."""

    def __init__(self, dbg, active, screen):
        self.dbg, self.active, self.screen = dbg, active, screen
        self.allocated = []
        self.buffers = []
        self.protected = (
            (0x30000000, 0x80000), (0x30600000, 0x7640F8),
            (active, 0x100), (screen[0], 20), (screen[4], FRAME_BYTES),
        )

    def trusted(self, address, size):
        ram_range(address, size)
        if address & 3 or any(overlap(address, size, a, count)
                              for a, count in self.protected + tuple(self.allocated)):
            raise Error("UNTRUSTED_NATIVE_POINTER; stop and do not repeat")

    def create(self, width, height):
        if (not isinstance(width, int) or not isinstance(height, int) or
                width <= 0 or height <= 0 or width * height > 0x7FFFFF):
            raise Error("CREATE_SIZE_INVALID")
        size = width * height * 4
        image = self.dbg.call("create", self.active, width, height)
        if not image:
            raise Error("CREATE_FAILED")
        self.trusted(image, size + 20)
        self.allocated.append((image, size + 20))
        info = read_surface(self.dbg, image, width, height, 32)
        if info[4] != image + 20:
            raise Error("CREATE_NOT_CONTIGUOUS")
        self.buffers.append((info[4], size))
        return info

    def contains(self, address, size):
        if (not self.dbg.verified or size <= 0 or
                not any(a <= address and address + size <= a + count
                        for a, count in self.buffers)):
            raise Error("WRITE_NOT_OWNED")

    def write(self, address, data):
        self.contains(address, len(data))
        if address & 3 or len(data) & 3 or len(data) > CHUNK:
            raise Error("OWNED_WRITE_BOUNDS")
        for offset in range(0, len(data), 4):
            self.dbg.packet(struct.pack(
                "<III", 1, address + offset,
                struct.unpack_from("<I", data, offset)[0]))
        if self.dbg.read(address, len(data)) != data:
            raise Error("OWNED_WRITE_READBACK_MISMATCH")

    def release_last(self, info):
        if not self.allocated or self.allocated[-1][0] != info[0]:
            raise Error("RELEASE_ORDER_INVALID")
        image, unused = self.allocated.pop()
        self.buffers.remove((info[4], info[3] * info[2]))
        self.dbg.call("free", image)

    def release(self):
        errors = []
        self.buffers = []
        while self.allocated:
            address, unused = self.allocated.pop()
            try:
                self.dbg.call("free", address)
            except BaseException as exc:
                errors.append("FREE_FAILED_NO_RETRY 0x%x: %s" % (address, exc))
        return errors


def clip_area(dbg, active):
    clip = struct.unpack("<hhhh", dbg.read(active + 0x6C, 8))
    if not (0 <= clip[0] <= clip[2] < 320 and 0 <= clip[1] <= clip[3] < 240):
        raise Error("CLIP_AREA_INVALID " + repr(clip))
    return clip


def compare_buffers(dbg, first, second, size=FRAME_BYTES):
    for offset in range(0, size, CHUNK):
        count = min(CHUNK, size - offset)
        if dbg.read(first + offset, count) != dbg.read(second + offset, count):
            raise Error("FRAME_BUFFER_MISMATCH offset=%d" % offset)


def check_screen(dbg, active, screen):
    if dbg.call("active") != active or read_lcd(dbg, active) != screen:
        raise Error("ACTIVE_SCREEN_CHANGED")


def ticks_ms():
    value = hpprime.ticks()
    if not isinstance(value, (int, float)) or value < 0 or value != int(value):
        raise Error("TICKS_INVALID")
    return int(value)


def wait_ms(milliseconds):
    if not isinstance(milliseconds, int) or milliseconds < 0:
        raise Error("WAIT_INVALID")
    start = ticks_ms()
    while milliseconds:
        now = ticks_ms()
        elapsed = now - start
        if elapsed < 0:
            elapsed &= 0xFFFFFFFF
        if elapsed >= milliseconds:
            return


class RunLog:
    def __init__(self, path, heading):
        self.path = path
        self.lines = [heading]
        self.persist()

    @staticmethod
    def _text(value):
        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8")
        raise Error("LOG_MESSAGE_NOT_TEXT")

    def persist(self):
        payload = ("\n".join(self._text(line) for line in self.lines) +
                   "\n").encode("utf-8")
        stream = uio.FileIO(self.path, "wb")
        try:
            if stream.write(payload) != len(payload):
                raise Error("LOG_SHORT_WRITE")
        finally:
            stream.close()
        stream = uio.FileIO(self.path, "rb")
        try:
            if stream.read(len(payload) + 1) != payload:
                raise Error("LOG_READBACK_MISMATCH")
        finally:
            stream.close()

    def emit(self, message, visible=True):
        message = self._text(message)
        self.lines.append(message)
        self.persist()
        if visible:
            print(message)
