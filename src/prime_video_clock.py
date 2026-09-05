"""Exact rational source clock with explicit decode/presentation accounting."""

TICK_MODULUS = 0x100000000
LATE_RENDER_MS = 50
FPS_REFRESH_MS = 500


def _signed_delta(first, second):
    value = (first - second) & 0xFFFFFFFF
    return value - TICK_MODULUS if value & 0x80000000 else value


class FrameClock:
    def __init__(self, fps_num, fps_den, ticks, wait):
        if (not isinstance(fps_num, int) or not isinstance(fps_den, int) or
                fps_num <= 0 or fps_den <= 0):
            raise ValueError("CLOCK_BAD_FPS")
        self.fps_num, self.fps_den = fps_num, fps_den
        self.ticks, self.wait = ticks, wait
        self.started = int(ticks()) & 0xFFFFFFFF
        self.frames = 0
        self.presented_frames = 0
        self.dropped_frames = 0
        self.late_frames = 0
        self.display_fps_tenths = 0
        self._fps_started = self.started
        self._fps_presented = 0
        self.paused_at = None

    def source_ms(self, frames=None):
        count = self.frames if frames is None else frames
        return count * 1000 * self.fps_den // self.fps_num

    def _deadline(self, frames):
        return (self.started + self.source_ms(frames)) & 0xFFFFFFFF

    def should_present(self, timing_mode="SYNC"):
        if timing_mode == "COMPLETE":
            return True
        if timing_mode != "SYNC":
            raise ValueError("CLOCK_BAD_TIMING_MODE")
        now = int(self.ticks()) & 0xFFFFFFFF
        current = self._deadline(self.frames)
        next_deadline = self._deadline(self.frames + 1)
        frame_ms = max(1, _signed_delta(next_deadline, current))
        return _signed_delta(now, current) < frame_ms

    def frame_decoded(self, presented, render_ms=0, timing_mode="SYNC"):
        if not isinstance(presented, bool):
            raise ValueError("CLOCK_BAD_PRESENTED")
        if not isinstance(render_ms, int) or render_ms < 0:
            raise ValueError("CLOCK_BAD_RENDER_TIME")
        if timing_mode not in ("SYNC", "COMPLETE"):
            raise ValueError("CLOCK_BAD_TIMING_MODE")
        self.frames += 1
        if presented:
            self.presented_frames += 1
            self._fps_presented += 1
        else:
            self.dropped_frames += 1
        deadline = self._deadline(self.frames)
        now = int(self.ticks()) & 0xFFFFFFFF
        fps_elapsed = _signed_delta(now, self._fps_started)
        if fps_elapsed < 0:
            raise ValueError("CLOCK_REVERSED")
        if fps_elapsed >= FPS_REFRESH_MS:
            self.display_fps_tenths = (
                self._fps_presented * 10000 // max(1, fps_elapsed))
            self._fps_started = now
            self._fps_presented = 0

        counted_late = presented and render_ms >= LATE_RENDER_MS
        if counted_late:
            self.late_frames += 1
        lateness = _signed_delta(now, deadline)
        if timing_mode == "COMPLETE" and counted_late and lateness > 0:
            # COMPLETE never repays a slow frame by shortening later frames.
            self.started = (self.started + lateness) & 0xFFFFFFFF
            deadline = now
            lateness = 0
        if lateness < 0:
            self.wait(-lateness)
        return deadline

    def frame_presented(self, render_ms, timing_mode="SYNC"):
        return self.frame_decoded(True, render_ms, timing_mode)

    def pause(self):
        if self.paused_at is None:
            self.paused_at = int(self.ticks()) & 0xFFFFFFFF
            self.display_fps_tenths = 0
            self._fps_started = self.paused_at
            self._fps_presented = 0

    def resume(self):
        if self.paused_at is not None:
            now = int(self.ticks()) & 0xFFFFFFFF
            paused = _signed_delta(now, self.paused_at)
            if paused < 0:
                raise ValueError("CLOCK_REVERSED")
            self.started = (self.started + paused) & 0xFFFFFFFF
            self.paused_at = None
            self.display_fps_tenths = 0
            self._fps_started = now
            self._fps_presented = 0
