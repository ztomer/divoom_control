"""ToolsApi — alarm/sleep/timer/countdown/noise/memorial/timeplan/screen/reset (REVIEW §1.2).

Extracts the scheduling/tools/device settings command surface.
"""
from __future__ import annotations

import json
import logging
import sys
from divoom_gui.api import ApiBase

logger = logging.getLogger("divoom_gui.api.tools")


class ToolsApi(ApiBase):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    @staticmethod
    def _as_bool(v) -> bool:
        return v in (True, 1, "1", "true", "True", "on", "yes")

    # ── Alarms ────────────────────────────────────────────────────────

    @staticmethod
    def _alarm_cache_path():
        from pathlib import Path
        return Path.home() / ".config" / "divoom-control" / "alarms.json"

    def _load_alarm_cache(self) -> list:
        try:
            p = self._alarm_cache_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"alarm cache read failed: {e}")
        return []

    def _store_alarm_cache(self, index: int, entry: dict) -> None:
        """Remember the last alarm state WE wrote (R34 §4): the device-side
        get_* read-back is flaky on real hardware (task #20), so this cache is
        the display fallback — without it the table shows empty-by-bug."""
        try:
            alarms = self._load_alarm_cache()
            while len(alarms) <= index:
                alarms.append({})
            alarms[index] = entry
            p = self._alarm_cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(alarms, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"alarm cache write failed: {e}")

    def get_alarms(self) -> str:
        try:
            target = self._current_divoom
            if target:
                alarms = self._run_async(target.alarm.get_alarm_time())
                if alarms:
                    return json.dumps(alarms)
        except Exception as e:
            logger.error(f"get_alarms failed: {e}")
        # Device read empty/failed → last-written cache (see _store_alarm_cache).
        return json.dumps(self._load_alarm_cache())

    def set_alarm(self, index: int, enabled, hour: int, minute: int,
                  week: int = 0, mode: int = 0, trigger_mode: int = 0) -> bool:
        logger.info(f"GUI Action: Set alarm {index} {int(hour):02d}:{int(minute):02d} "
                    f"enabled={enabled} week={week}...")
        try:
            status = 1 if (enabled in (True, 1, "1", "true", "True")) else 0
            target = self._current_divoom
            if not target:
                return False
            ok = bool(self._run_async(target.alarm.set_alarm(
                int(index), status, int(hour), int(minute), int(week),
                int(mode), int(trigger_mode))))
            if ok:
                self._store_alarm_cache(int(index), {
                    "status": status, "hour": int(hour), "minute": int(minute),
                    "week": int(week),
                })
            return ok
        except Exception as e:
            logger.error(f"set_alarm failed: {e}")
            return False

    # ── Sleep Aid ────────────────────────────────────────────────────

    def start_sleep(self, minutes: int = 30, color: str = "#2040ff", volume: int = 10) -> bool:
        logger.info(f"GUI Action: Start sleep {minutes}min color={color} vol={volume}...")
        try:
            target = self._current_divoom
            if not target:
                return False
            from divoom_lib.utils.converters import color_to_rgb_list
            rgb = color_to_rgb_list(color)
            return bool(self._run_async(target.sleep.show_sleep(
                sleeptime=int(minutes), volume=int(volume), color=rgb, on=1)))
        except Exception as e:
            logger.error(f"start_sleep failed: {e}")
            return False

    def stop_sleep(self) -> bool:
        logger.info("GUI Action: Stop sleep...")
        try:
            target = self._current_divoom
            if not target:
                return False
            return bool(self._run_async(target.sleep.show_sleep(on=0)))
        except Exception as e:
            logger.error(f"stop_sleep failed: {e}")
            return False

    # ── Tools (timer/countdown/noise) ────────────────────────────────

    def _tool_call(self, fn, label: str) -> bool:
        logger.info(f"GUI Action: Tool {label}...")
        try:
            target = self._current_divoom
            if not target:
                return False
            return bool(self._run_async(fn(target)))
        except Exception as e:
            logger.error(f"tool {label} failed: {e}")
            return False

    def set_timer(self, action: str = "start") -> bool:
        from divoom_lib.models import (
            STI_CTRL_FLAG_TIMER_STARTED, STI_CTRL_FLAG_TIMER_PAUSED, STI_CTRL_FLAG_TIMER_RESET)
        flag = {"start": STI_CTRL_FLAG_TIMER_STARTED, "stop": STI_CTRL_FLAG_TIMER_PAUSED,
                "reset": STI_CTRL_FLAG_TIMER_RESET}.get(action, STI_CTRL_FLAG_TIMER_STARTED)
        return self._tool_call(lambda d: d.timer.set_timer(flag), f"timer {action}")

    def set_countdown(self, action: str = "start", minutes: int = 5, seconds: int = 0) -> bool:
        from divoom_lib.models import STI_CTRL_FLAG_COUNTDOWN_START, STI_CTRL_FLAG_COUNTDOWN_CANCEL
        flag = STI_CTRL_FLAG_COUNTDOWN_CANCEL if action == "stop" else STI_CTRL_FLAG_COUNTDOWN_START
        return self._tool_call(lambda d: d.countdown.set_countdown(flag, int(minutes), int(seconds)),
                               f"countdown {action} {minutes}:{seconds}")

    def set_noise(self, action: str = "start") -> bool:
        from divoom_lib.models import STI_CTRL_FLAG_NOISE_START, STI_CTRL_FLAG_NOISE_STOP
        flag = STI_CTRL_FLAG_NOISE_STOP if action == "stop" else STI_CTRL_FLAG_NOISE_START
        return self._tool_call(lambda d: d.noise.set_noise(flag), f"noise {action}")

    # ── Device settings ──────────────────────────────────────────────

    def set_hour_type(self, is_24h) -> bool:
        return self._tool_call(lambda d: d.system.set_hour_type(1 if self._as_bool(is_24h) else 0), "hour type")

    def set_temp_unit(self, fahrenheit) -> bool:
        return self._tool_call(lambda d: d.device.set_temp_type(1 if self._as_bool(fahrenheit) else 0), "temp unit")

    def sync_time(self) -> bool:
        """Set the device clock to this machine's local time.

        R72 P1.2. This used to build the packet through
        `divoom_lib.system.date_time.DateTimeCommand` -- a duplicate of the
        daemon's `set_date_time`, and a BROKEN one: that module's own comment
        records an `AttributeError` "swallowed by the GUI tool wrapper into a
        silent False, so Sync Time never worked".

        The calendar values are passed explicitly and that is deliberate. The
        daemon owns the PACKET; the client owns "what time is it where the user
        is", which needs a timezone the daemon would have to pull in a whole
        tz database to answer. Passing six integers is not a second
        implementation of anything.

        Note the daemon REFUSES an argument-less call now (R72 P1.2): its
        defaults are 2000-01-01, so `sync_time` with no arguments used to set
        the device to the year 2000 and report success.
        """
        import datetime
        now = datetime.datetime.now()
        return self._tool_call(
            lambda d: d.system.set_date_time(
                year=now.year, month=now.month, day=now.day,
                hour=now.hour, minute=now.minute, second=now.second),
            "time sync")

    def set_device_name(self, name: str) -> bool:
        return self._tool_call(lambda d: d.device.set_device_name(str(name)), "device name")

    def get_device_name(self) -> str | None:
        logger.info("GUI Action: Getting current device name...")
        try:
            target = self._current_divoom
            if not target:
                return None
            return self._run_async(target.device.get_device_name())
        except Exception as e:
            logger.error(f"Device name get failed: {e}")
            return None

    def set_auto_power_off(self, minutes: int) -> bool:
        # R72 P1.3: `device.` and not `system.` -- the daemon accepts
        # system./device./sound./bare for THIS command but only device./bare for
        # set_low_power below, and a path it does not accept falls through to a
        # generic "unknown method" that says nothing about the typo.
        return self._tool_call(
            lambda d: d.device.set_auto_power_off(int(minutes)), "auto power off")

    def set_low_power(self, on) -> bool:
        return self._tool_call(
            lambda d: d.device.set_low_power(1 if self._as_bool(on) else 0),
            "low power")

    def set_fm_frequency(self, freq_x10: int) -> bool:
        return self._tool_call(lambda d: d.radio.set_radio_frequency(int(freq_x10)), "fm")

    def set_memorial(self, index, enabled, month, day, hour, minute, title="") -> bool:
        on = 1 if self._as_bool(enabled) else 0
        have = 1 if title else 0
        return self._tool_call(
            lambda d: d.alarm.set_memorial_time(int(index), on, int(month), int(day),
                                                int(hour), int(minute), have, str(title)),
            "memorial")

    # ── Display orientation + factory reset ──────────────────────────

    def set_screen_dir(self, direction) -> bool:
        return self._tool_call(lambda d: d.design.set_screen_dir(int(direction)),
                               "screen direction")

    def set_screen_mirror(self, on) -> bool:
        return self._tool_call(lambda d: d.design.set_screen_mirror(self._as_bool(on)),
                               "screen mirror")

    def factory_reset(self, confirm="") -> bool:
        if str(confirm) != "RESET":
            logger.warning("factory_reset refused: missing/invalid confirm token")
            return False
        return self._tool_call(lambda d: d.design.factory_reset(), "factory reset")

    # ── Scoreboard (uses _tool_call pattern) ────────────────────────

    def set_scoreboard(self, on_off: int, red: int = 0, blue: int = 0) -> bool:
        logger.info(f"GUI Action: Setting scoreboard on_off={on_off} red={red} blue={blue}...")
        try:
            target = self._current_divoom
            if not target:
                return False
            return self._run_async(target.scoreboard.set_scoreboard(int(on_off), int(red), int(blue)))
        except Exception as e:
            logger.error(f"Scoreboard set failed: {e}")
            return False

    # ── Volume / brightness getters (read-only, single device) ──────

    def get_volume(self):
        logger.info("GUI Action: Getting current volume...")
        try:
            target = self._current_divoom
            if not target:
                return None
            return self._run_async(target.music.get_volume())
        except Exception as e:
            logger.error(f"Volume get failed: {e}")
            return None

    def get_brightness(self):
        logger.info("GUI Action: Getting current brightness...")
        try:
            target = self._current_divoom
            if not target:
                return None
            return self._run_async(target.device.get_brightness())
        except Exception as e:
            logger.error(f"Brightness get failed: {e}")
            return None

    def get_work_mode(self):
        logger.info("GUI Action: Getting current work mode...")
        try:
            target = self._current_divoom
            if not target:
                return None
            return self._run_async(target.device.get_work_mode())
        except Exception as e:
            logger.error(f"Work mode get failed: {e}")
            return None

    def send_notification(self, app_type, text="") -> bool:
        t = int(app_type)
        if not (1 <= t <= 14):
            logger.warning(f"send_notification: app_type {t} out of range 1-14")
            return False
        msg = str(text or "").strip()
        if msg:
            return self._tool_call(
                lambda d: d.notification.show_notification_text(t, msg),
                "notification")
        return self._tool_call(
            lambda d: d.notification.show_notification(t), "notification")