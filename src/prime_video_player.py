"""PrimeVideoPlayer 1.1.1 application state machine and resource ownership."""

import sys
import prime_native as native
from prime_video_clock import FrameClock
from prime_video_files import NativeDirectoryScanner
from prime_video_model import PlayerModel, PlayerState
from prime_video_positions import PositionStore
from prime_video_settings import SettingsStore, default_settings
from prime_video_runtime import (PlayerBridge, PlayerScreen, ScreenAwake,
                                 key_event, ticks_ms, wait_ms)
from prime_video_sessions import M1VPlaybackSession, MjpgPlaybackSession

Error = native.Error


class PlayerLog(native.RunLog):
    def __init__(self, path="prime_video_player.log"):
        native.RunLog.__init__(
            self, path, "PrimeVideoPlayer 1.1.1 G1/2025-09-15")


class PrimeVideoPlayer:
    def __init__(self, bridge_factory=None, screen=None, emit=None,
                 position_store=None, settings_store=None):
        self.bridge_factory = bridge_factory or self._new_bridge
        self.screen = screen or PlayerScreen()
        self.emit = emit or (lambda message, visible=True: None)
        self.bridge = None
        self.session = None
        self.screen_awake = None
        self.clock = None
        self.positions = position_store or PositionStore()
        self.settings_store = settings_store or SettingsStore()

    @staticmethod
    def _new_bridge():
        return PlayerBridge(native.uio.FileIO("debug"))

    def _temporary_scan(self):
        bridge = self.bridge_factory()
        images = None
        primary = None
        cleanup = []
        files = None
        try:
            bridge.verify()
            active, real = bridge.call("active"), bridge.call("real")
            screen = native.read_lcd(bridge, active)
            if active != real or screen[5] != 32:
                raise Error("UNEXPECTED_LCD_CONTEXT")
            images = native.OwnedImages(bridge, active, screen)
            scratch = images.create(256, 1)
            files = NativeDirectoryScanner(bridge, images, scratch).scan()
        except BaseException as exc:
            primary = exc
        finally:
            if images is not None:
                cleanup.extend(images.release())
            try:
                bridge.close()
            except BaseException as exc:
                cleanup.append("DEBUG_CLOSE_FAILED: " + str(exc))
        if primary is not None:
            if cleanup:
                raise Error(str(primary) + "; CLEANUP: " + "; ".join(cleanup))
            raise primary
        if cleanup:
            raise Error("; ".join(cleanup))
        return files

    def _open_current(self, model):
        if (self.session is not None or self.screen_awake is not None or
                self.bridge is not None):
            raise Error("PLAYER_SESSION_ALREADY_OPEN")
        self.bridge = self.bridge_factory()
        try:
            self.bridge.verify()
            self.screen_awake = ScreenAwake(self.bridge)
            self.screen_awake.start()
            entry = model.files[model.index]
            session_type = (M1VPlaybackSession if entry.extension == ".M1V"
                            else MjpgPlaybackSession)
            self.session = session_type(self.bridge, entry, self.emit,
                                        model.settings)
            self.session.start()
            self.session.set_video_bottom(
                self.screen.video_bottom(model.debug_mode))
            remembered = self.positions.get(entry)
            if remembered:
                actual = self.session.seek_tenths(remembered)
                self.screen.video_frame_updated()
                self.screen.playback(entry, self.session, model, False)
                self.emit("PLAY_RESUME %s requested=%d actual=%d" %
                          (entry.name, remembered, actual), False)
            fps_num, fps_den = self.session.fps
            self.clock = FrameClock(fps_num, fps_den, ticks_ms, wait_ms)
            self.emit("PLAY_START %s bytes=%d" % (entry.name, entry.size), False)
        except BaseException as primary:
            try:
                self._close_current()
            except BaseException as cleanup:
                raise Error(str(primary) + "; CLEANUP: " + str(cleanup))
            raise

    def _close_current(self):
        errors = []
        if self.session is not None:
            session, self.session = self.session, None
            try:
                session.close()
            except BaseException as exc:
                errors.append("SESSION_CLOSE_FAILED: " + str(exc))
        self.clock = None
        if self.screen_awake is not None:
            screen_awake, self.screen_awake = self.screen_awake, None
            try:
                screen_awake.close()
            except BaseException as exc:
                errors.append("SCREEN_AWAKE_CLOSE_FAILED: " + str(exc))
        if self.bridge is not None:
            bridge, self.bridge = self.bridge, None
            try:
                bridge.close()
            except BaseException as exc:
                errors.append("DEBUG_CLOSE_FAILED: " + str(exc))
        if errors:
            raise Error("; ".join(errors))

    def _save_current_position(self, model, clear=False):
        if self.session is None:
            return
        entry = self.session.entry
        if clear:
            self.positions.clear(entry)
            self.emit("POSITION_CLEAR " + entry.name, False)
        else:
            position = self.session.position_tenths
            self.positions.set(entry, position)
            self.emit("POSITION_SAVE %s %d" % (entry.name, position), False)

    def _new_clock(self, model):
        fps_num, fps_den = self.session.fps
        self.clock = FrameClock(fps_num, fps_den, ticks_ms, wait_ms)
        self.session.display_fps_tenths = 0
        if model.state == PlayerState.PAUSED:
            self.clock.pause()

    def _stop_with_primary(self, primary):
        cleanup = None
        try:
            self._close_current()
        except BaseException as exc:
            cleanup = exc
        if cleanup is not None:
            return str(primary) + "; CLEANUP: " + str(cleanup)
        return str(primary)

    def _play_event(self, model, event):
        if event is None:
            return None
        action = model.event(event, self.session.position_tenths)
        if action == "PAUSE":
            self.clock.pause()
            self.session.display_fps_tenths = 0
            self._save_current_position(model)
        elif action == "RESUME":
            self.clock.resume()
            self.session.display_fps_tenths = 0
        elif action == "SEEK_BEGIN":
            if model.seek_return_state == PlayerState.PLAYING:
                self.clock.pause()
        elif action == "SEEK_CANCEL":
            if model.state == PlayerState.PLAYING:
                self.clock.resume()
        elif action == "SEEK":
            target = model.seek_target
            self.session.seek_tenths(target)
            model.seek_target = None
            self._new_clock(model)
            self._save_current_position(model)
            self.screen.video_frame_updated()
            self.screen.playback(model.files[model.index], self.session, model,
                                 model.state == PlayerState.PAUSED)
        elif action in ("STOP", "SWITCH"):
            self._save_current_position(model)
        return action

    def _run_current(self, model):
        while model.state in (PlayerState.PLAYING, PlayerState.PAUSED,
                              PlayerState.SEEKING):
            self.screen_awake.refresh()
            entry = model.files[model.index]
            if model.state in (PlayerState.PAUSED, PlayerState.SEEKING):
                self.screen.playback(entry, self.session, model,
                                     model.state == PlayerState.PAUSED)
                action = self._play_event(model, key_event(repeat=True))
                if action in ("STOP", "SWITCH"):
                    return action
                wait_ms(20)
                continue
            render_start = ticks_ms()
            present = self.clock.should_present(model.settings.timing)
            if not self.session.next_frame(present):
                self._save_current_position(model, True)
                return model.finished()
            if present:
                self.screen.video_frame_updated()
                self.screen.playback(entry, self.session, model, False)
            render_end = ticks_ms()
            render_ms = render_end - render_start
            if render_ms < 0:
                render_ms &= 0xFFFFFFFF
            self.clock.frame_decoded(present, render_ms,
                                     model.settings.timing)
            self.session.late_frames = self.clock.late_frames
            self.session.presented_frames = self.clock.presented_frames
            self.session.dropped_frames = self.clock.dropped_frames
            self.session.display_fps_tenths = self.clock.display_fps_tenths
            action = self._play_event(model, key_event())
            if action in ("STOP", "SWITCH"):
                return action
        return None

    def run(self):
        model = PlayerModel(())
        primary = None
        try:
            try:
                try:
                    settings = self.settings_store.load()
                except BaseException as exc:
                    self.screen.error("SETTINGS_STORE_INVALID: " + str(exc))
                    while True:
                        event = key_event()
                        if event == "ENTER":
                            settings = self.settings_store.reset()
                            break
                        if event == "BACK":
                            return
                        wait_ms(25)
                model = PlayerModel(self._temporary_scan(), settings)
                try:
                    self.positions.load()
                except BaseException as exc:
                    self.emit("POSITION_LOAD_FAILED: " + str(exc), False)
                    self.positions.records = {}
                self.emit("SCAN_OK files=%d" % len(model.files), False)
                self.screen.list(model)
            except BaseException as exc:
                model.fail(exc)
                self.screen.error(model.error)

            while True:
                if model.state == PlayerState.LIST:
                    action = model.event(key_event())
                    if action == "EXIT":
                        return
                    if action == "START":
                        try:
                            self._open_current(model)
                        except BaseException as exc:
                            model.fail(self._stop_with_primary(exc))
                            self.screen.error(model.error)
                    else:
                        self.screen.list(model)
                        wait_ms(25)
                    continue

                if model.state == PlayerState.SETTINGS:
                    self.screen.settings(model)
                    action = model.event(key_event(repeat=True))
                    if action == "SETTINGS_SAVE":
                        try:
                            self.settings_store.save(model.settings_draft)
                        except BaseException as exc:
                            model.fail("SETTINGS_SAVE_FAILED: " + str(exc))
                            self.screen.error(model.error)
                        else:
                            model.commit_settings()
                            self.screen.list(model)
                    elif action == "SETTINGS_CANCEL":
                        self.screen.list(model)
                    else:
                        wait_ms(25)
                    continue

                if model.state == PlayerState.ERROR:
                    self.screen.error(model.error)
                    model.event(key_event())
                    if model.state == PlayerState.LIST:
                        self.screen.list(model)
                    else:
                        wait_ms(25)
                    continue

                try:
                    action = self._run_current(model)
                    self._close_current()
                    if action in ("STOP", "DONE"):
                        self.screen.list(model)
                    elif action in ("SWITCH", "RESTART", "NEXT"):
                        self._open_current(model)
                    else:
                        raise Error("PLAYER_ACTION_INVALID " + repr(action))
                except BaseException as exc:
                    model.fail(self._stop_with_primary(exc))
                    self.screen.error(model.error)
        except BaseException as exc:
            primary = exc
            raise
        finally:
            if (self.session is not None or self.screen_awake is not None or
                    self.bridge is not None):
                try:
                    self._close_current()
                except BaseException as cleanup:
                    if primary is None:
                        raise
                    try:
                        self.emit("FINAL_CLEANUP_FAILED: " + str(cleanup), False)
                    except BaseException:
                        pass


def main():
    if sys.implementation.name != "micropython":
        raise Error("Physical HP Prime G1 only")
    log = PlayerLog()
    player = PrimeVideoPlayer(emit=log.emit)
    try:
        player.run()
        log.emit("PLAYER_EXIT_CLEAN", False)
    except BaseException as exc:
        try:
            log.emit("STOP %s: %s" % (type(exc).__name__, exc), False)
        except BaseException:
            pass
        raise
