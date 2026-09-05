"""Pure MPEG-1 start-code helpers shared by device and host verification."""

PICTURE_START = b"\x00\x00\x01\x00"
SEQUENCE_START = b"\x00\x00\x01\xb3"
FRAME_RATES = {
    1: (24000, 1001), 2: (24, 1), 3: (25, 1),
    4: (30000, 1001), 5: (30, 1), 6: (50, 1),
    7: (60000, 1001), 8: (60, 1),
}
# Same ratios used by the pinned pl_mpeg sequence-header implementation.
PIXEL_ASPECT = {
    1: (10000, 10000), 2: (6735, 10000), 3: (7031, 10000),
    4: (7615, 10000), 5: (8055, 10000), 6: (8437, 10000),
    7: (8935, 10000), 8: (9157, 10000), 9: (9815, 10000),
    10: (10255, 10000), 11: (10695, 10000), 12: (10950, 10000),
    13: (11575, 10000), 14: (12051, 10000),
}
ARENA_FIXED_BYTES = 808
MAX_ARENA_BYTES = 0x01F00000


class M1VFormatError(ValueError):
    pass


class M1VInfo:
    __slots__ = ("width", "height", "aspect_code", "rate_code",
                 "fps_num", "fps_den", "par_num", "par_den",
                 "macroblock_width", "macroblock_height", "arena_bytes")

    def __init__(self, width, height, aspect_code, rate_code):
        if not 1 <= width <= 4095 or not 1 <= height <= 4095:
            raise M1VFormatError("MPEG_SEQUENCE_SIZE_INVALID")
        if aspect_code not in PIXEL_ASPECT:
            raise M1VFormatError("MPEG_ASPECT_CODE_INVALID %d" % aspect_code)
        if rate_code not in FRAME_RATES:
            raise M1VFormatError("MPEG_RATE_CODE_INVALID %d" % rate_code)
        self.width, self.height = width, height
        self.aspect_code, self.rate_code = aspect_code, rate_code
        self.fps_num, self.fps_den = FRAME_RATES[rate_code]
        self.par_num, self.par_den = PIXEL_ASPECT[aspect_code]
        self.macroblock_width = (width + 15) // 16
        self.macroblock_height = (height + 15) // 16
        padded_pixels = (self.macroblock_width * 16 *
                         self.macroblock_height * 16)
        frame_bytes = padded_pixels + padded_pixels // 2
        self.arena_bytes = ARENA_FIXED_BYTES + frame_bytes * 3
        if self.arena_bytes > MAX_ARENA_BYTES:
            raise M1VFormatError("MPEG_ARENA_EXCEEDS_NATIVE_WINDOW %d" %
                                 self.arena_bytes)


def parse_sequence_header(data):
    """Parse the first complete MPEG-1 sequence header in a byte window."""
    if not isinstance(data, (bytes, bytearray)):
        raise M1VFormatError("MPEG_HEADER_NOT_BINARY")
    position = bytes(data).find(SEQUENCE_START)
    if position < 0:
        raise M1VFormatError("MPEG_SEQUENCE_HEADER_NOT_FOUND")
    if position + 8 > len(data):
        raise M1VFormatError("MPEG_SEQUENCE_HEADER_TRUNCATED")
    header = data[position + 4:position + 8]
    width = (header[0] << 4) | (header[1] >> 4)
    height = ((header[1] & 15) << 8) | header[2]
    aspect_code = header[3] >> 4
    rate_code = header[3] & 15
    return M1VInfo(width, height, aspect_code, rate_code)


def scale_geometry(info, mode, target_width=320, target_height=240):
    """Return source crop and destination rectangle for a display mode."""
    if not isinstance(info, M1VInfo) or mode not in (
            "FIT", "ORIGINAL", "FILL", "STRETCH"):
        raise M1VFormatError("MPEG_SCALE_ARGUMENT_INVALID")
    if target_width <= 0 or target_height <= 0:
        raise M1VFormatError("MPEG_SCALE_TARGET_INVALID")
    sw, sh = info.width, info.height
    sx = sy = 0
    if mode == "STRETCH":
        dw, dh = target_width, target_height
    elif mode == "ORIGINAL":
        crop_w, crop_h = min(sw, target_width), min(sh, target_height)
        sx, sy = (sw - crop_w) // 2, (sh - crop_h) // 2
        sw, sh = crop_w, crop_h
        dw, dh = sw, sh
    elif mode == "FIT":
        if sw * info.par_num * target_height >= sh * info.par_den * target_width:
            dw = target_width
            dh = max(1, target_width * sh * info.par_den //
                     (sw * info.par_num))
        else:
            dh = target_height
            dw = max(1, target_height * sw * info.par_num //
                     (sh * info.par_den))
    else:  # FILL
        if sw * info.par_num * target_height >= sh * info.par_den * target_width:
            crop_w = max(1, sh * target_width * info.par_den //
                         (target_height * info.par_num))
            crop_w = min(sw, crop_w)
            sx, sw = (sw - crop_w) // 2, crop_w
        else:
            crop_h = max(1, sw * info.par_num * target_height //
                         (target_width * info.par_den))
            crop_h = min(sh, crop_h)
            sy, sh = (sh - crop_h) // 2, crop_h
        dw, dh = target_width, target_height
    dx, dy = (target_width - dw) // 2, (target_height - dh) // 2
    return sx, sy, sw, sh, dx, dy, dw, dh


def i_picture_offsets(data, base_offset=0, before=None):
    offsets = []
    position = 0
    while True:
        position = data.find(PICTURE_START, position)
        if position < 0 or position + 6 > len(data):
            break
        absolute = base_offset + position
        picture_type = (data[position + 5] >> 3) & 7
        if picture_type == 1 and (before is None or absolute <= before):
            offsets.append(absolute)
        position += 4
    return tuple(offsets)


def safe_seek_anchors(data, base_offset=0, before=None):
    """Return sequence-header anchors whose next picture is an I-picture."""
    anchors = []
    latest_sequence = None
    position = 0
    while True:
        position = data.find(b"\x00\x00\x01", position)
        if position < 0 or position + 4 > len(data):
            break
        absolute = base_offset + position
        code = data[position + 3]
        if code == 0xB3:
            latest_sequence = absolute
        elif code == 0 and position + 6 <= len(data):
            picture_type = (data[position + 5] >> 3) & 7
            if (picture_type == 1 and latest_sequence is not None and
                    (before is None or absolute <= before)):
                anchors.append(latest_sequence)
        position += 4
    return tuple(anchors)


def bootstrap_prefix(data):
    picture = data.find(PICTURE_START)
    if picture < 0:
        raise M1VFormatError("MPEG_BOOTSTRAP_PICTURE_NOT_FOUND")
    prefix = bytes(data[:picture])
    if SEQUENCE_START not in prefix:
        raise M1VFormatError("MPEG_BOOTSTRAP_SEQUENCE_NOT_FOUND")
    return prefix
