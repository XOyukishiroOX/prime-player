"""Pure MPEG-1 start-code helpers shared by device and host verification."""

PICTURE_START = b"\x00\x00\x01\x00"
SEQUENCE_START = b"\x00\x00\x01\xb3"


class M1VFormatError(ValueError):
    pass


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
