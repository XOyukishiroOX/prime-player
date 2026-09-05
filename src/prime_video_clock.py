"""Monotonic source-rate scheduler with explicit late-frame accounting."""


class FrameClock:
    def __init__(self, fps_num, fps_den, ticks, wait):
        if (not isinstance(fps_num, int) or not isinstance(fps_den, int) or
                fps_num <= 0 or fps_den <= 0):
            raise ValueError("CLOCK_BAD_FPS")
        self.fps_num, self.fps_den = fps_num, fps_den
        self.ticks, self.wait = ticks, wait
        self.started = ticks()
        self.frames = 0
        self.late_frames = 0
        self.paused_at = None

    def source_ms(self):
        return self.frames * 1000 * self.fps_den // self.fps_num

    def frame_presented(self, render_ms):
        if not isinstance(render_ms, int) or render_ms < 0:
            raise ValueError("CLOCK_BAD_RENDER_TIME")
        if render_ms > 50:
            self.late_frames += 1
        self.frames += 1
        deadline = self.started + self.source_ms()
        now = self.ticks()
        if now < deadline:
            self.wait(deadline - now)
        return deadline

    def pause(self):
        if self.paused_at is None:
            self.paused_at = self.ticks()

    def resume(self):
        if self.paused_at is not None:
            now = self.ticks()
            if now < self.paused_at:
                raise ValueError("CLOCK_REVERSED")
            self.started += now - self.paused_at
            self.paused_at = None
