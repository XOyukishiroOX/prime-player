"""Fixed G1 interfaces and bounds for the independent PrimeMJPEGDecoder."""

CACHE_API = {
    'clean_line': (0x3007E824, 1, b'\x3a\x0f\x07\xee\x0e\xf0\xa0\xe1'),
    'drain': (0x3007E854, 0, b'\x00\x00\xa0\xe3\x9a\x0f\x07\xee\x0e\xf0\xa0\xe1'),
    'invalidate_i': (0x3007E7E4, 0, b'\x00\x00\xa0\xe3\x15\x0f\x07\xee\x0e\xf0\xa0\xe1'),
}

APP_DIR = "C:\\DATA\\PrimeMJPEGDecoder.hpappdir\\"
WIDTH, HEIGHT, OUTPUT_BYTES = 320, 240, 320 * 240 * 4
CONTEXT_MAGIC, RESULT_MAGIC, COOKIE = 0x4A504358, 0x4A504C30, 0x4A504547
SUCCESS = 0x4A500100
RESULT_WORDS = 32
WORKSPACE_BYTES = 32768
MODULE_BYTES = 31936
MAX_FRAME_BYTES = 65536
GUARD = b'\xa5' * 32
MODE_DECODE_OFFSCREEN = 0
MODE_DECODE_CLEAN = 2
