"""Strict PrimeVideoPlayer MJPG container parser."""

try:
    import ustruct as struct
except ImportError:
    import struct

MAGIC = b"PVMJ"
VERSION = 1
HEADER_BYTES = 32
WIDTH, HEIGHT = 320, 240
MAX_FPS = 12
MAX_FRAME_BYTES = 65536


class MjpgError(ValueError):
    pass


class MjpgHeader:
    __slots__ = ("version", "header_bytes", "width", "height",
                 "fps_num", "fps_den", "frame_count", "flags")

    def __init__(self, version, header_bytes, width, height, fps_num, fps_den,
                 frame_count, flags):
        self.version = version
        self.header_bytes = header_bytes
        self.width = width
        self.height = height
        self.fps_num = fps_num
        self.fps_den = fps_den
        self.frame_count = frame_count
        self.flags = flags

    @property
    def fps(self):
        return self.fps_num * 1.0 / self.fps_den


def parse_header(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) != HEADER_BYTES:
        raise MjpgError("MJPG_HEADER_TRUNCATED")
    if bytes(data[:4]) != MAGIC:
        raise MjpgError("MJPG_BAD_MAGIC")
    values = struct.unpack_from("<HHHHHHIIII", data, 4)
    (version, header_bytes, width, height, fps_num, fps_den, frame_count,
     flags, reserved0, reserved1) = values
    if version != VERSION:
        raise MjpgError("MJPG_BAD_VERSION %d" % version)
    if header_bytes != HEADER_BYTES:
        raise MjpgError("MJPG_BAD_HEADER_SIZE %d" % header_bytes)
    if (width, height) != (WIDTH, HEIGHT):
        raise MjpgError("MJPG_BAD_DIMENSIONS %dx%d" % (width, height))
    if fps_den == 0 or fps_num < fps_den or fps_num > MAX_FPS * fps_den:
        raise MjpgError("MJPG_BAD_FPS %d/%d" % (fps_num, fps_den))
    if frame_count == 0:
        raise MjpgError("MJPG_EMPTY_FRAME_SET")
    if flags != 0 or reserved0 != 0 or reserved1 != 0:
        raise MjpgError("MJPG_RESERVED_FLAGS_NONZERO")
    return MjpgHeader(version, header_bytes, width, height, fps_num, fps_den,
                      frame_count, flags)


def _marker_is_standalone(marker):
    return marker == 0x01 or 0xD0 <= marker <= 0xD9


def validate_baseline_jpeg(data):
    if not isinstance(data, (bytes, bytearray)):
        raise MjpgError("MJPG_JPEG_NOT_BINARY")
    data = bytes(data)
    if len(data) == 0 or len(data) > MAX_FRAME_BYTES:
        raise MjpgError("MJPG_JPEG_SIZE_INVALID %d" % len(data))
    if data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        raise MjpgError("MJPG_JPEG_NOT_COMPLETE")
    position = 2
    saw_sof0 = False
    saw_sos = False
    eoi = False
    while position < len(data):
        if data[position] != 0xFF:
            raise MjpgError("MJPG_JPEG_MARKER_EXPECTED")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise MjpgError("MJPG_JPEG_MARKER_TRUNCATED")
        marker = data[position]
        position += 1
        if marker == 0xD9:
            if not saw_sos or position != len(data):
                raise MjpgError("MJPG_JPEG_TRAILING_BYTES")
            eoi = True
            break
        if marker == 0xDA:
            if position + 2 > len(data):
                raise MjpgError("MJPG_JPEG_SOS_TRUNCATED")
            segment = struct.unpack_from(">H", data, position)[0]
            if segment < 2 or position + segment > len(data):
                raise MjpgError("MJPG_JPEG_SOS_LENGTH")
            position += segment
            saw_sos = True
            break
        if _marker_is_standalone(marker):
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if marker == 0xC2:
                raise MjpgError("MJPG_PROGRESSIVE_JPEG_UNSUPPORTED")
            if marker != 0xC0:
                raise MjpgError("MJPG_JPEG_UNSUPPORTED_SOF 0x%02x" % marker)
        if position + 2 > len(data):
            raise MjpgError("MJPG_JPEG_SEGMENT_TRUNCATED")
        segment = struct.unpack_from(">H", data, position)[0]
        if segment < 2 or position + segment > len(data):
            raise MjpgError("MJPG_JPEG_SEGMENT_LENGTH")
        if marker == 0xC0:
            if segment < 17:
                raise MjpgError("MJPG_JPEG_SOF_LENGTH")
            precision = data[position + 2]
            height = struct.unpack_from(">H", data, position + 3)[0]
            width = struct.unpack_from(">H", data, position + 5)[0]
            components = data[position + 7]
            if (precision, width, height, components) != (8, WIDTH, HEIGHT, 3):
                raise MjpgError("MJPG_JPEG_SOF_FORMAT")
            if segment != 17:
                raise MjpgError("MJPG_JPEG_SOF_COMPONENTS")
            sampling = data[position + 9:position + 10] + data[position + 12:position + 13] + data[position + 15:position + 16]
            if sampling != b"\x22\x11\x11":
                raise MjpgError("MJPG_JPEG_NOT_420")
            saw_sof0 = True
        position += segment
    if saw_sos and position < len(data):
        # The entropy-coded scan is byte-oriented; stuffed 0xff00 bytes and
        # restart markers are data, while EOI is the only terminating marker.
        while position < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            while position < len(data) and data[position] == 0xFF:
                position += 1
            if position >= len(data):
                raise MjpgError("MJPG_JPEG_SCAN_TRUNCATED")
            marker = data[position]
            position += 1
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                continue
            if marker == 0xD9:
                if position != len(data):
                    raise MjpgError("MJPG_JPEG_TRAILING_BYTES")
                eoi = True
                break
            raise MjpgError("MJPG_JPEG_UNEXPECTED_SCAN_MARKER 0x%02x" % marker)
    if not saw_sof0 or not saw_sos or not eoi:
        raise MjpgError("MJPG_JPEG_BASELINE_MARKERS_MISSING")
    return len(data)


def read_exact(stream, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise MjpgError("MJPG_TRUNCATED_READ %d" % size)
        chunks.append(bytes(chunk))
        remaining -= len(chunk)
    return b"".join(chunks)


class MjpgReader:
    """Read a strict MJPG stream from a seekable binary stream."""

    def __init__(self, stream, validate_frames=True):
        self.stream = stream
        self.header = parse_header(read_exact(stream, HEADER_BYTES))
        self.index = 0
        self.validate_frames = validate_frames

    def next_frame(self):
        if self.index >= self.header.frame_count:
            raise MjpgError("MJPG_FRAME_COUNT_EXCEEDED")
        size = struct.unpack("<I", read_exact(self.stream, 4))[0]
        if size == 0 or size > MAX_FRAME_BYTES:
            raise MjpgError("MJPG_FRAME_SIZE_INVALID %d" % size)
        data = read_exact(self.stream, size)
        if self.validate_frames:
            validate_baseline_jpeg(data)
        padding = (-size) & 3
        if padding:
            if read_exact(self.stream, padding) != b"\x00" * padding:
                raise MjpgError("MJPG_NONZERO_PADDING")
        self.index += 1
        return data

    def finish(self):
        if self.index != self.header.frame_count:
            raise MjpgError("MJPG_FRAME_COUNT_MISMATCH %d/%d" %
                            (self.index, self.header.frame_count))
        trailing = self.stream.read(1)
        if trailing:
            raise MjpgError("MJPG_TRAILING_DATA")


def parse_bytes(data, validate_frames=True):
    try:
        import io
        reader = MjpgReader(io.BytesIO(data), validate_frames)
        frames = []
        for unused in range(reader.header.frame_count):
            frames.append(reader.next_frame())
        reader.finish()
        return reader.header, tuple(frames)
    except ImportError:
        raise MjpgError("MJPG_HOST_IO_UNAVAILABLE")
