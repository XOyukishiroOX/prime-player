"""Pack baseline 320x240 JPEG files into the PrimeVideoPlayer MJPG format."""

import argparse
from pathlib import Path
import sys
import struct

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mjpg_container import (HEADER_BYTES, MAGIC, MAX_FRAME_BYTES, VERSION,
                            validate_baseline_jpeg)


def pack(output, inputs, fps_num=10, fps_den=1):
    if fps_den <= 0 or fps_num < fps_den or fps_num > 12 * fps_den:
        raise ValueError("FPS must be between 1 and 12")
    frames = []
    for path in inputs:
        data = Path(path).read_bytes()
        validate_baseline_jpeg(data)
        if len(data) > MAX_FRAME_BYTES:
            raise ValueError("JPEG exceeds 65536 bytes: %s" % path)
        frames.append(data)
    if not frames:
        raise ValueError("at least one JPEG is required")
    header = MAGIC + struct.pack("<HHHHHHIIII", VERSION, HEADER_BYTES, 320, 240,
                                 fps_num, fps_den, len(frames), 0, 0, 0)
    payload = bytearray(header)
    for data in frames:
        payload.extend(struct.pack("<I", len(data)))
        payload.extend(data)
        payload.extend(b"\x00" * ((-len(data)) & 3))
    Path(output).write_bytes(payload)
    return {"output": str(output), "bytes": len(payload),
            "frames": len(frames), "fps": "%d/%d" % (fps_num, fps_den)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--fps-num", type=int, default=10)
    parser.add_argument("--fps-den", type=int, default=1)
    args = parser.parse_args()
    print(pack(args.output, args.inputs, args.fps_num, args.fps_den))


if __name__ == "__main__":
    main()
