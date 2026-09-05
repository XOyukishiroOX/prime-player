"""Production-only reusable baseline-JPEG decoder for MJPG playback."""

import ustruct as struct

import mjpeg_decoder_payload as payload
import mjpeg_decoder_profile as profile
import prime_native as native

Error = native.Error
FULL_CLIP = (0, 0, 319, 239)


def _write_context(images, address, input_address, size, output, workspace,
                   mode):
    words = list((profile.CONTEXT_MAGIC, input_address, size, output,
                  profile.OUTPUT_BYTES, workspace, profile.WORKSPACE_BYTES,
                  profile.COOKIE) +
                 (0xCCCCCCCC,) * (profile.RESULT_WORDS - 8))
    words[28] = mode
    images.write(address, struct.pack("<%dI" % profile.RESULT_WORDS, *words))


def _check_guard(dbg, address, label):
    if dbg.read(address, 32) != profile.GUARD:
        raise Error(label + "_GUARD_CHANGED")


class DecoderCode:
    def __init__(self, images, image):
        self.images, self.dbg = images, images.dbg
        self.address = (image[4] + 63) & ~31
        self.ready = False
        images.contains(self.address - 32, profile.MODULE_BYTES + 64)
        images.write(self.address - 32, profile.GUARD)
        images.write(self.address + profile.MODULE_BYTES, profile.GUARD)

    def load(self):
        offset = 0
        for chunk in payload.MODULE_CHUNKS:
            if (len(chunk) & 3 or len(chunk) > 4096 or
                    offset + len(chunk) > profile.MODULE_BYTES):
                raise Error("MJPEG_MODULE_CHUNK_BOUNDS")
            self.images.write(self.address + offset, chunk)
            offset += len(chunk)
        if offset != profile.MODULE_BYTES:
            raise Error("MJPEG_MODULE_SIZE_MISMATCH")
        self.check_guards()
        for address in range(self.address,
                             self.address + profile.MODULE_BYTES, 32):
            self.dbg.maintenance("clean_line", address)
        self.dbg.maintenance("drain")
        self.dbg.maintenance("invalidate_i")
        self.ready = True

    def execute(self, context):
        if not self.ready:
            raise Error("MJPEG_CODE_NOT_SYNCHRONIZED")
        return self.dbg.invoke(self.address, (context, profile.COOKIE))

    def check_guards(self):
        if (self.dbg.read(self.address - 32, 32) != profile.GUARD or
                self.dbg.read(self.address + profile.MODULE_BYTES, 32) !=
                profile.GUARD):
            raise Error("MJPEG_CODE_GUARD_CHANGED")


class DecoderSession:
    """Reusable one-frame decoder without probe/demo entry points."""

    def __init__(self, dbg, emit=None):
        self.dbg = dbg
        self.emit = emit or (lambda message, visible=True: None)
        self.images = None
        self.code = None
        self.started = False
        self.closed = False
        self.direct_used = False

    def start(self):
        if self.started or self.closed:
            raise Error("DECODER_SESSION_STATE_INVALID")
        self.dbg.verify()
        active, real = self.dbg.call("active"), self.dbg.call("real")
        screen = native.read_lcd(self.dbg, active)
        if active != real or screen[5] != 32 or screen[4] & 31:
            raise Error("UNEXPECTED_LCD_CONTEXT")
        self.active, self.screen = active, screen
        self.original_clip = native.clip_area(self.dbg, active)
        self.images = native.OwnedImages(self.dbg, active, screen)
        self._allocate()
        self.code.load()
        self._save_screen()
        self.started = True

    def _allocate(self):
        output_backing = self.images.create(320, 241)
        self.output = (output_backing[4] + 95) & ~31
        self.output_header = self.output - 20
        self.images.contains(self.output - 52,
                             32 + 20 + profile.OUTPUT_BYTES + 32)
        self.images.write(self.output - 52, profile.GUARD)
        self.images.write(self.output_header,
                          struct.pack("<2shhhhhII", b"PX", 320, 240,
                                      32, 1280, 2, 0, self.output))
        self.images.write(self.output + profile.OUTPUT_BYTES, profile.GUARD)

        self.input_image = self.images.create(
            256, (profile.MAX_FRAME_BYTES + 95 + 1023) // 1024)
        self.input_address = (self.input_image[4] + 63) & ~31
        self.input_span = profile.MAX_FRAME_BYTES + (-profile.MAX_FRAME_BYTES & 3)
        self.images.contains(self.input_address - 32, self.input_span + 64)
        self.images.write(self.input_address - 32, profile.GUARD)
        self.images.write(self.input_address + self.input_span, profile.GUARD)

        workspace_image = self.images.create(256, 33)
        self.workspace = (workspace_image[4] + 63) & ~31
        self.images.contains(self.workspace - 32, profile.WORKSPACE_BYTES + 64)
        self.images.write(self.workspace - 32, profile.GUARD)
        self.images.write(self.workspace + profile.WORKSPACE_BYTES, profile.GUARD)

        self.contexts = []
        for unused in range(2):
            image = self.images.create(64, 1)
            address = image[4] + 32
            self.images.write(address - 32, profile.GUARD)
            self.images.write(address + profile.RESULT_WORDS * 4, profile.GUARD)
            self.contexts.append(address)
        self.offscreen_context, self.direct_context = self.contexts
        _write_context(self.images, self.offscreen_context, self.input_address,
                       256, self.output, self.workspace,
                       profile.MODE_DECODE_OFFSCREEN)
        _write_context(self.images, self.direct_context, self.input_address,
                       256, self.screen[4], self.workspace,
                       profile.MODE_DECODE_CLEAN)

        code_image = self.images.create(
            256, (profile.MODULE_BYTES + 95 + 1023) // 1024)
        self.code = DecoderCode(self.images, code_image)
        self.saved = self.images.create(320, 240)

    def _save_screen(self):
        for offset in range(0, profile.OUTPUT_BYTES, 4096):
            size = min(4096, profile.OUTPUT_BYTES - offset)
            self.images.write(self.saved[4] + offset,
                              self.dbg.read(self.screen[4] + offset, size))
        native.compare_buffers(self.dbg, self.saved[4], self.screen[4])
        native.check_screen(self.dbg, self.active, self.screen)
        self.dbg.raw("clip", *FULL_CLIP)
        if native.clip_area(self.dbg, self.active) != FULL_CLIP:
            raise Error("SET_FULL_CLIP_FAILED")
        self.clip_active = True

    def _write_size(self, context, size):
        if not isinstance(size, int) or not 256 <= size <= profile.MAX_FRAME_BYTES:
            raise Error("FRAME_SIZE_INVALID")
        self.images.contains(context + 8, 4)
        self.dbg.packet(struct.pack("<III", 1, context + 8, size))

    def _decode_loaded(self, size, context, output):
        if not self.started or self.closed:
            raise Error("DECODER_SESSION_NOT_STARTED")
        self._write_size(context, size)
        result = self.code.execute(context)
        if result != profile.SUCCESS:
            raise Error("MJPEG_NATIVE_RETURN 0x%x" % result)
        words = struct.unpack("<%dI" % profile.RESULT_WORDS,
                              self.dbg.read(context,
                                            profile.RESULT_WORDS * 4))
        expected = (profile.CONTEXT_MAGIC, self.input_address, size, output,
                    profile.OUTPUT_BYTES, self.workspace,
                    profile.WORKSPACE_BYTES, profile.COOKIE,
                    profile.RESULT_MAGIC, 0, profile.WIDTH, profile.HEIGHT)
        if tuple(words[:12]) != expected:
            raise Error("MJPEG_RESULT_MISMATCH")
        return words

    def decode_loaded_to_buffer(self, size):
        return self._decode_loaded(size, self.offscreen_context, self.output)

    def check_state(self):
        self.code.check_guards()
        for context in self.contexts:
            _check_guard(self.dbg, context - 32, "CONTEXT_LEFT")
            _check_guard(self.dbg, context + profile.RESULT_WORDS * 4,
                         "CONTEXT_RIGHT")
        _check_guard(self.dbg, self.output - 52, "OUTPUT_LEFT")
        _check_guard(self.dbg, self.output + profile.OUTPUT_BYTES,
                     "OUTPUT_RIGHT")
        _check_guard(self.dbg, self.workspace - 32, "WORKSPACE_LEFT")
        _check_guard(self.dbg, self.workspace + profile.WORKSPACE_BYTES,
                     "WORKSPACE_RIGHT")
        native.check_screen(self.dbg, self.active, self.screen)

    def close(self):
        if self.closed:
            return
        errors = []
        if self.images is not None:
            if getattr(self, "clip_active", False):
                try:
                    native.check_screen(self.dbg, self.active, self.screen)
                    if self.direct_used:
                        self.dbg.raw("clip", *FULL_CLIP)
                        self.dbg.call("put", 0, 0, self.saved[0], 0)
                        native.compare_buffers(self.dbg, self.saved[4],
                                               self.screen[4])
                    self.dbg.raw("clip", *self.original_clip)
                    if native.clip_area(self.dbg, self.active) != self.original_clip:
                        raise Error("CLIP_RESTORE_MISMATCH")
                except BaseException as exc:
                    errors.append("RESTORE_FAILED: " + str(exc))
            errors.extend(self.images.release())
        self.closed = True
        self.started = False
        if errors:
            raise Error("; ".join(errors))
