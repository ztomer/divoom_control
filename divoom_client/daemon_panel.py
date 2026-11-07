"""Panel-scope RPCs: topology, live jobs, per-device activity, artwork and the HOT update.

Split out of ``daemon_protocol.py`` when ``ruff format`` took it past the 500-line
rule (tests/test_file_size.py). They belong together because each is a thin wrapper
that names one panel (or the wall) and hands the work to the daemon: no framing, no
retry, no socket handling of their own -- that stays in ``DaemonClient.send_command``.
"""

from __future__ import annotations


class PanelDataMixin:
    """Panel-scoped daemon commands. Mixed into :class:`DaemonClient`."""

    def get_topology(self) -> dict:
        return self.send_command("get_topology")

    def set_topology(self, topology: dict) -> dict:
        return self.send_command("set_topology", {"topology": topology})

    def probe_lan(self) -> dict:
        return self.send_command("probe_lan")

    def live_job_start(self, mac: str, kind: str, params: dict) -> dict:
        return self.send_command("live_job_start", {"mac": mac, "kind": kind, "params": params})

    def live_job_stop(self, mac: str, kind: str) -> dict:
        return self.send_command("live_job_stop", {"mac": mac, "kind": kind})

    def live_job_list(self, mac: str | None = None) -> dict:
        return self.send_command("live_job_list", {"mac": mac})

    def live_jobs_stop_for(self, mac: str | None = None) -> dict:
        """Stop all live jobs for a device (default: the daemon's active device).
        Called before a channel/display switch so a running widget doesn't
        clobber it on its next tick."""
        return self.send_command("live_jobs_stop_for", {"mac": mac})

    def set_device_activity(self, mac: str, kind: str, name: str | None = None, preview: str | None = None) -> dict:
        """R46 #3 / R50: record what a device is showing (for the menubar tiles).
        ``preview`` is an optional rasterized PNG data URL for the tile thumbnail."""
        return self.send_command("set_device_activity", {"mac": mac, "kind": kind, "name": name, "preview": preview})

    def get_device_activity(self) -> dict:
        """R46 #3: {mac: {name, kind, at}} of what each device is showing."""
        return self.send_command("get_device_activity", {})

    def sync_artwork(
        self, file_id: str, *, mac: str | None = None, default_size: int | None = None, target: str = "device"
    ) -> dict:
        """Ask the daemon to download a gallery asset and stream it to the owned
        device/wall (binary stays in the daemon process).

        Uses the long ``sync_read_timeout`` — the daemon only replies after the
        download + full BLE stream, which takes far longer than the quick-command
        timeout (a short read here falsely reported every upload as failed).
        Pixel art: shown only on a panel (``mac``) of its own size (D14)."""
        from divoom_client.daemon_config import load_daemon_config

        args = {"file_id": file_id, "target": target, "mac": mac, "default_size": default_size}
        return self.send_command(
            "sync_artwork",
            {k: v for k, v in args.items() if v is not None},
            read_timeout=load_daemon_config().sync_read_timeout,
        )

    def custom_art_push(
        self, file_ids: list[str], page: int, slot: int | None = None, slots: dict | None = None, mac: str | None = None
    ) -> dict:
        """Push cloud files to custom art ``page`` (0-2) on the panel ``mac``
        names (without it, the daemon's selected one: `art.rs`). ``slots`` is
        the full-page {slot 0-11: file_id} mapping (unmapped slots are
        cleared); ``file_ids`` from ``slot`` on is the legacy form."""
        from divoom_client.daemon_config import load_daemon_config

        args = {"file_ids": file_ids, "page": page, "slot": slot, "slots": slots}
        if mac:
            args["mac"] = mac
        return self.send_command("custom_art_push", args, read_timeout=load_daemon_config().sync_read_timeout)

    def hot_update(self, *, device_size: int = 16, show: bool = True, address: str = "", by: str = "button") -> dict:
        """Start a HOT channel update in the background on the daemon (returns
        immediately). Call ``hot_update_progress()`` to poll progress.
        ``address`` names the panel; the daemon records the run's verdict under
        it, ``by`` saying which path ran it (``button`` or ``sync_now``; U.5)."""
        return self.send_command(
            "hot_update", {"device_size": device_size, "show": show, "address": address, "by": by}, read_timeout=30
        )

    def hot_update_progress(self) -> dict:
        """Query the current HOT channel update progress. Returns a phase dict:
        ``{"phase": "idle"|"starting"|"fetching_manifest"|"downloading"|"uploading"|"done"|"error",
        "current": int, "total": int, ...}``."""
        return self.send_command("hot_update_progress", {})
