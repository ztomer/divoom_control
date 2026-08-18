"""macOS notification app→type routing rules.

Split out of ``macos_notifications.py`` to keep that file under the 500-LOC cap.
Holds DEFAULT_ROUTING, the persisted routing table (load/save/validate), and the
MacAppRouter. Re-exported from ``macos_notifications`` for backward-compatible
imports."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from divoom_lib.models import NOTIFICATION_APPS

logger = logging.getLogger(__name__)


DEFAULT_ROUTING: list[tuple[str, int]] = [
    ("whatsapp",   NOTIFICATION_APPS["WHATSAPP"]),
    ("facebook",   NOTIFICATION_APPS["FACEBOOK"]),
    ("messenger",  NOTIFICATION_APPS["MESSENGER"]),
    ("instagram",  NOTIFICATION_APPS["INSTAGRAM"]),
    ("twitter",    NOTIFICATION_APPS["TWITTER"]),
    ("snapchat",   NOTIFICATION_APPS["SNAPCHAT"]),
    ("line",       NOTIFICATION_APPS["LINE"]),
    ("wechat",     NOTIFICATION_APPS["WECHAT"]),
    ("kakao",      NOTIFICATION_APPS["KAKAO"]),
    ("qq",         NOTIFICATION_APPS["QQ"]),
    ("viber",      NOTIFICATION_APPS["VIBER"]),
    ("skype",      NOTIFICATION_APPS["SKYPE"]),
    # SMS / iMessage / Mail → "text message" (the device's catch-all).
    ("mobilesms",      NOTIFICATION_APPS["TEXT_MESSAGE"]),
    ("messages",       NOTIFICATION_APPS["TEXT_MESSAGE"]),
    ("mail",           NOTIFICATION_APPS["TEXT_MESSAGE"]),
    ("com.apple.mail", NOTIFICATION_APPS["TEXT_MESSAGE"]),
]

# The set of valid Divoom notification app_type values. Used to
# validate user-supplied routing files (a JSON typo like
# ``["whatsapp", 99]`` must not silently crash at notification time).
_VALID_APP_TYPES: frozenset[int] = frozenset(NOTIFICATION_APPS.values())


# Custom routing config path. Honoring the env var lets the GUI
# Settings card point at a project-local config for testing without
# touching the user's real ``~/.config`` tree.
ROUTING_PATH: Path = Path(
    os.environ.get("DIVOOM_CONTROL_ROUTING")
    or (Path.home() / ".config" / "divoom-control" / "notification_routing.json")
)


def _validate_rules(raw: Any) -> list[tuple[str, int]]:
    """Return a clean rules list from a parsed JSON value. Silently
    drop malformed entries; warn once per batch. The result is always
    safe to pass to ``MacAppRouter``.
    """
    if not isinstance(raw, list):
        raise ValueError("routing JSON must be a list of [substring, app_type] pairs")
    clean: list[tuple[str, int]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            logger.warning(f"routing entry {i} not a [str, int] pair: {entry!r}; skipping")
            continue
        substr, app_type = entry
        if not isinstance(substr, str) or not substr:
            logger.warning(f"routing entry {i} has non-string substring: {entry!r}; skipping")
            continue
        try:
            app_type_int = int(app_type)
        except (TypeError, ValueError):
            logger.warning(f"routing entry {i} has non-integer app_type: {entry!r}; skipping")
            continue
        if app_type_int not in _VALID_APP_TYPES:
            logger.warning(
                f"routing entry {i} app_type={app_type_int} not in NOTIFICATION_APPS; skipping"
            )
            continue
        clean.append((substr.lower(), app_type_int))
    return clean


def load_routing_table(path: Optional[Path] = None) -> list[tuple[str, int]]:
    """Load a custom routing table from a JSON file.

    Returns ``DEFAULT_ROUTING`` (a copy) when:
      - the file does not exist (first run / no customization yet), or
      - the file is corrupt / not a JSON list / has no valid entries.

    Logs a warning in the corrupt case so the user knows their
    config wasn't applied.

    File format: a JSON list of [substring, app_type] pairs, e.g.::

        [["whatsapp", 6], ["com.apple.mail", 7]]
    """
    p = Path(path) if path is not None else ROUTING_PATH
    if not p.exists():
        return list(DEFAULT_ROUTING)
    try:
        import json as _json
        with open(p, "r", encoding="utf-8") as f:
            raw = _json.load(f)
        rules = _validate_rules(raw)
        if not rules:
            logger.warning(f"routing file {p} has no valid entries; using defaults")
            return list(DEFAULT_ROUTING)
        logger.info(f"loaded {len(rules)} routing rule(s) from {p}")
        return rules
    except (OSError, ValueError) as e:
        logger.warning(f"routing file {p} is corrupt ({e}); using defaults")
        return list(DEFAULT_ROUTING)


def save_routing_table(
    rules: list[tuple[str, int]],
    path: Optional[Path] = None,
) -> Path:
    """Write a routing table to disk. Creates parent directories.
    Entries are sorted by substring (stable) so re-saving produces a
    deterministic file that's friendly to git diffs.

    Returns the resolved path.
    """
    import json as _json
    p = Path(path) if path is not None else ROUTING_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # Re-validate on the way out so a save() can't persist garbage.
    clean = _validate_rules([list(r) for r in rules])
    clean.sort(key=lambda r: r[0])
    from divoom_lib.utils.atomic_io import atomic_write_text
    atomic_write_text(p, _json.dumps([list(r) for r in clean],
                                     indent=2, ensure_ascii=False) + "\n")
    return p


class MacAppRouter:
    """Maps a macOS notification's `app` field to a Divoom
    ``NOTIFICATION_APPS`` value (1-14). Returns None when no rule
    matches; the caller should drop the notification.

    Matching is case-insensitive substring; first rule wins.

    By default the rule list is the built-in ``DEFAULT_ROUTING``;
    use ``MacAppRouter.from_file()`` to load a user-customized
    table from ``~/.config/divoom-control/notification_routing.json``
    (or a path you specify).
    """

    def __init__(self, rules: Optional[list[tuple[str, int]]] = None) -> None:
        self._rules = list(rules) if rules is not None else list(DEFAULT_ROUTING)

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "MacAppRouter":
        """Build a router from a JSON routing file. Falls back to
        defaults silently when the file is missing or corrupt."""
        return cls(rules=load_routing_table(path))

    def add_rule(self, substring: str, app_type: int) -> None:
        """Add a routing rule. Inserted at the front (highest priority)."""
        self._rules.insert(0, (substring.lower(), int(app_type)))

    @property
    def rules(self) -> list[tuple[str, int]]:
        """Read-only view of the current rule list (substring, app_type)."""
        return list(self._rules)

    def route(self, app_id: str) -> Optional[int]:
        """Return the Divoom app_type for this macOS app_id, or None."""
        if not app_id:
            return None
        a = app_id.lower()
        for substr, app_type in self._rules:
            if substr in a:
                return app_type
        return None
