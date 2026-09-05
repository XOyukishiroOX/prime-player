"""PrimeVideoPlayer 1.1.0 fixed G1 firmware profile."""

VERSION = "1.1.0"
TARGET = "HP Prime G1 / firmware 2025-09-15"
APP_DIR = "C:\\DATA\\PrimeVideoPlayer.hpappdir\\"
SCAN_PATTERN = APP_DIR + "*.*"
POSITION_FILE = "prime_video_positions.dat"

RAW_API = {
    "open": (0x1026F, 0x3003C0E4, 2),
    "close_file": (0x100CA, 0x3003C710, 1),
    "seek": (0x100CF, 0x3003CABC, 3),
    "read_file": (0x100D4, 0x3003CF04, 4),
    "cwd": (0x100E3, 0x3003DDD8, 2),
    "clip": (0x10073, 0x3002E6A4, 4),
    "find_first": (0x10270, 0x3003E588, 3),
    "find_next": (0x10271, 0x3003E434, 1),
    "find_close": (0x100DA, 0x3003E7C8, 1),
}

# Resets the firmware's accumulated idle time. With argument 1 it also
# restores the configured brightness if the LCD has already been dimmed.
SCREEN_ACTIVITY_API = (
    0x30037744,
    1,
    b"\xb8\x15\x9f\xe5\x10\x40\x2d\xe9\x00\x20\xa0\xe3\x01\x00\x50\xe3"
    b"\xb0\x22\xc1\xe1\x34\x00\x91\x05\x00\x00\x50\x03\x10\x80\xbd\x18"
    b"\x9c\x05\x9f\xe5\xec\xff\xff\xeb\x04\x00\x50\xe3\x03\x00\xa0\x23"
    b"\x10\x40\xbd\xe8\x00\x08\xa0\xe1\x20\x08\xa0\xe1\xd3\x54\xff\xea",
)
SCREEN_ACTIVITY_REFRESH_MS = 1000

FIND_CONTEXT_BYTES = 40
FIND_LFN_POINTER_OFFSET = 0x08
FIND_SIZE_OFFSET = 0x14
FIND_ATTRIBUTES_OFFSET = 0x25
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_DIRECTORY = 0x10
IGNORED_ATTRIBUTES = ATTR_HIDDEN | ATTR_SYSTEM | ATTR_DIRECTORY
MAX_FILENAME_UNITS = 255
MAX_FILES = 256

# Bit positions returned by hpprime.keyboard(). The order is also the priority
# when more than one new key is pressed in the same sample.
KEY_EVENTS = (
    (30, "ENTER"),
    (4, "BACK"),
    (2, "UP"),
    (12, "DOWN"),
    (7, "LEFT"),
    (8, "RIGHT"),
    (3, "HELP"),
)
