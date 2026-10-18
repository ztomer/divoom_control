"""ToolsApi — alarm/sleep/timer/countdown/noise/memorial/timeplan/screen/reset (REVIEW §1.2).

Extracts the scheduling/tools/device settings command surface.

Every method names the ONE panel it acts on, first (P5.7): the web UI resolves
it at the gesture and passes its mac, and `ApiBase._display(mac, wall=False)`
is where it becomes a target. These used to act on `current_divoom`, the panel
the bench last selected, read when the call RAN -- a rename clicked on one
panel and followed by a click on another renamed the second. A Tools action
on the wall is refused: an alarm or a timer is one panel's, and the wall used
to resolve to whichever panel the bench had held last.
"""
from __future__ import annotations

import json
import logging
from divoom_gui.api import ApiBase

logger = logging.getLogger("divoom_gui.api.tools")


class ToolsApi(ApiBase):
    def __init__(self, loop_thread, daemon_client_getter, state_getter):
        super().__init__(loop_thread, daemon_client_getter, state_getter)

    @staticmethod
    def _as_bool(v) -> bool:
        return v in (True, 1, "1", "true", "True", "on", "yes")

    def _panel(self, mac):
        """The one panel a Tools action names, or None (refused)."""
        return self._display(mac, wall=False)

    # ── Alarms ────────────────────────────────────────────────────────

    @staticmethod
    def _alarm_cache_path():
        from pathlib import Path
        return Path.home() / ".config" / "divoom-control" / "alarms.json"

    def _load_alarm_cache(self) -> dict:
        """`{mac: [alarm, ...]}`. The file used to be ONE list for whichever
        panel was selected when it was written; such a file names no panel,
        so it is read as nothing rather than shown as every panel's."""
        try:
            p = self._alarm_cache_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {k: v for k, v in data.items() if isinstance(v, list)}
        except Exception as e:
            logger.warning(f"alarm cache read failed: {e}")
        return {}

    def _store_alarm_cache(self, mac: str, index: int, entry: dict) -> None:
        """Remember the last alarm state WE wrote to `mac` (R34 §4): the
        device-side get_* read-back is flaky on real hardware (task #20), so
        this cache is the display fallback — without it the table shows
        empty-by-bug. Keyed by panel: one panel's alarms are not another's."""
        try:
            cache = self._load_alarm_cache()
            alarms = cache.setdefault(mac, [])
            while len(alarms) <= index:
                alarms.append({})
            alarms[index] = entry
            p = self._alarm_cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"alarm cache write failed: {e}")

    def get_alarms(self, mac: str) -> str:
        target = self._panel(mac)
        try:
            if target is not None:
                alarms = self._run_async(target.alarm.get_alarm_time())
                if alarms:
                    return json.dumps(alarms)
        except Exception as e:
            logger.error(f"get_alarms failed: {e}")
        # Device read empty/failed → what we last wrote to THIS panel
        # (see _store_alarm_cache); a call naming no panel gets none.
        return json.dumps(self._load_alarm_cache().get(mac, []) if isinstance(mac, str) else [])

    def set_alarm(self, mac: str, index: int, enabled, hour: int, minute: int,
                  week: int = 0, mode: int = 0, trigger_mode: int = 0) -> bool:
        logger.info(f"GUI Action: Set alarm {index} {int(hour):02d}:{int(minute):02d} "
                    f"enabled={enabled} week={week} on {mac}...")
        status = 1 if (enabled in (True, 1, "1", "true", "True")) else 0
        ok = self._tool_call(mac, lambda d: d.alarm.set_alarm(
            int(index), status, int(hour), int(minute), int(week),
            int(mode), int(trigger_mode)), "alarm")
        if ok:
            self._store_alarm_cache(mac, int(index), {
                "status": status, "hour": int(hour), "minute": int(minute),
                "week": int(week),
            })
        return ok

    # ── Sleep Aid ────────────────────────────────────────────────────

    def start_sleep(self, mac: str, minutes: int = 30, color: str = "#2040ff",
                    volume: int = 10) -> bool:
        from divoom_lib.utils.converters import color_to_rgb_list
        try:
            rgb = color_to_rgb_list(color)
        except Exception as e:
            logger.error(f"start_sleep: bad colour {color!r}: {e}")
            return False
        return self._tool_call(mac, lambda d: d.sleep.show_sleep(
            sleeptime=int(minutes), volume=int(volume), color=rgb, on=1),
            f"sleep {minutes}min color={color} vol={volume}")

    def stop_sleep(self, mac: str) -> bool:
        return self._tool_call(mac, lambda d: d.sleep.show_sleep(on=0), "stop sleep")

    # ── Tools (timer/countdown/noise) ────────────────────────────────

    def _tool_call(self, mac, fn, label: str) -> bool:
        logger.info(f"GUI Action: Tool {label} on {mac}...")
        try:
            target = self._panel(mac)
            if target is None:
                return False
            return bool(self._run_async(fn(target)))
        except Exception as e:
            logger.error(f"tool {label} failed: {e}")
            return False

    def set_timer(self, mac: str, action: str = "start") -> bool:
        from divoom_lib.models import (
            STI_CTRL_FLAG_TIMER_STARTED, STI_CTRL_FLAG_TIMER_PAUSED, STI_CTRL_FLAG_TIMER_RESET)
        flag = {"start": STI_CTRL_FLAG_TIMER_STARTED, "stop": STI_CTRL_FLAG_TIMER_PAUSED,
                "reset": STI_CTRL_FLAG_TIMER_RESET}.get(action, STI_CTRL_FLAG_TIMER_STARTED)
        return self._tool_call(mac, lambda d: d.timer.set_timer(flag), f"timer {action}")

    def set_countdown(self, mac: str, action: str = "start", minutes: int = 5, seconds: int = 0) -> bool:
        from divoom_lib.models import STI_CTRL_FLAG_COUNTDOWN_START, STI_CTRL_FLAG_COUNTDOWN_CANCEL
        flag = STI_CTRL_FLAG_COUNTDOWN_CANCEL if action == "stop" else STI_CTRL_FLAG_COUNTDOWN_START
        return self._tool_call(mac, lambda d: d.countdown.set_countdown(flag, int(minutes), int(seconds)),
                               f"countdown {action} {minutes}:{seconds}")

    def set_noise(self, mac: str, action: str = "start") -> bool:
        from divoom_lib.models import STI_CTRL_FLAG_NOISE_START, STI_CTRL_FLAG_NOISE_STOP
        flag = STI_CTRL_FLAG_NOISE_STOP if action == "stop" else STI_CTRL_FLAG_NOISE_START
        return self._tool_call(mac, lambda d: d.noise.set_noise(flag), f"noise {action}")

    # ── Device settings ──────────────────────────────────────────────

    def set_hour_type(self, mac: str, is_24h) -> bool:
        return self._tool_call(mac, lambda d: d.system.set_hour_type(1 if self._as_bool(is_24h) else 0), "hour type")

    def set_temp_unit(self, mac: str, fahrenheit) -> bool:
        return self._tool_call(mac, lambda d: d.device.set_temp_type(1 if self._as_bool(fahrenheit) else 0), "temp unit")

    def sync_time(self, mac: str) -> bool:
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
            mac, lambda d: d.system.set_date_time(
                year=now.year, month=now.month, day=now.day,
                hour=now.hour, minute=now.minute, second=now.second),
            "time sync")

    def set_device_name(self, mac: str, name: str) -> bool:
        return self._tool_call(mac, lambda d: d.device.set_device_name(str(name)), "device name")

    def get_device_name(self, mac: str) -> str | None:
        logger.info(f"GUI Action: Getting the name of {mac}...")
        try:
            target = self._panel(mac)
            if target is None:
                return None
            return self._run_async(target.device.get_device_name())
        except Exception as e:
            logger.error(f"Device name get failed: {e}")
            return None

    def set_auto_power_off(self, mac: str, minutes: int) -> bool:
        # R72 P1.3: `device.` and not `system.` -- the daemon accepts
        # system./device./sound./bare for THIS command but only device./bare for
        # set_low_power below, and a path it does not accept falls through to a
        # generic "unknown method" that says nothing about the typo.
        return self._tool_call(
            mac, lambda d: d.device.set_auto_power_off(int(minutes)), "auto power off")

    def set_low_power(self, mac: str, on) -> bool:
        return self._tool_call(
            mac, lambda d: d.device.set_low_power(1 if self._as_bool(on) else 0),
            "low power")

    def set_fm_frequency(self, mac: str, freq_x10: int) -> bool:
        return self._tool_call(mac, lambda d: d.radio.set_radio_frequency(int(freq_x10)), "fm")

    def set_memorial(self, mac: str, index, enabled, month, day, hour, minute, title="") -> bool:
        on = 1 if self._as_bool(enabled) else 0
        have = 1 if title else 0
        return self._tool_call(
            mac, lambda d: d.alarm.set_memorial_time(int(index), on, int(month), int(day),
                                                int(hour), int(minute), have, str(title)),
            "memorial")

    # ── Display orientation + factory reset ──────────────────────────

    def set_screen_dir(self, mac: str, direction) -> bool:
        return self._tool_call(mac, lambda d: d.design.set_screen_dir(int(direction)),
                               "screen direction")

    def set_screen_mirror(self, mac: str, on) -> bool:
        return self._tool_call(mac, lambda d: d.design.set_screen_mirror(self._as_bool(on)),
                               "screen mirror")

    def factory_reset(self, mac: str, confirm="") -> bool:
        if str(confirm) != "RESET":
            logger.warning("factory_reset refused: missing/invalid confirm token")
            return False
        return self._tool_call(mac, lambda d: d.design.factory_reset(), "factory reset")

    # ── Scoreboard (a channel control, P5.6) ───────────────────────

    def set_scoreboard(self, mac: str, on_off: int, red: int = 0, blue: int = 0) -> dict:
        """A channel control: it names its panel like the rest (P5.6), and
        answers the write's outcome (P6.4)."""
        logger.info(f"GUI Action: Setting scoreboard on {mac} on_off={on_off} red={red} blue={blue}...")
        return self._write(mac, "scoreboard", lambda t: t.scoreboard.set_scoreboard(
            int(on_off), int(red), int(blue)))

    def get_work_mode(self, mac: str):
        logger.info(f"GUI Action: Getting the work mode of {mac}...")
        try:
            target = self._panel(mac)
            if target is None:
                return None
            return self._run_async(target.device.get_work_mode())
        except Exception as e:
            logger.error(f"Work mode get failed: {e}")
            return None

    def send_notification(self, mac: str, app_type, text="") -> bool:
        t = int(app_type)
        if not (1 <= t <= 14):
            logger.warning(f"send_notification: app_type {t} out of range 1-14")
            return False
        msg = str(text or "").strip()
        if msg:
            return self._tool_call(
                mac, lambda d: d.notification.show_notification_text(t, msg),
                "notification")
        return self._tool_call(
            mac, lambda d: d.notification.show_notification(t), "notification")