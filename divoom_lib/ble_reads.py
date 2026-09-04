"""BLE Hardening Phase 5 — ``get_*`` read-back resilience.

Device reads (name / alarms / brightness …) are flaky: the query frame often
gets no reply on a real device, so the raw read returns ``None`` and the UI
can't tell "the device said nothing" from a real value — it spins or shows a
wrong/blank field (weakness W9 / task #20).

This wraps any async read in a bounded retry with a short per-attempt timeout
and a **last-good cache**, returning a typed :class:`ReadResult` so the caller
degrades gracefully:

  * fresh value      → ``ok=True, from_cache=False``
  * reply lost but a previous good value exists → ``ok=True, from_cache=True``
    (the UI keeps showing the last known value instead of a dash/spinner)
  * never got a value and nothing cached → ``ok=False`` + a typed reason the UI
    renders as "—" (unknown), NOT a wrong value.

The read callable and ``sleep`` are injected, so every path is unit-tested
without hardware. (The separate question of WHY the query frame is unanswered —
a per-model 0x42/0x46 framing variant — is a hardware-protocol investigation
tracked alongside; this layer makes the timeout degrade gracefully regardless.)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from .ble_connection import FailureReason

logger = logging.getLogger("divoom_lib.ble_reads")


@dataclass
class ReadResult:
    ok: bool
    value: Any = None
    from_cache: bool = False           # served a stale last-good value
    reason: FailureReason = FailureReason.NONE
    detail: str = ""

    @property
    def known(self) -> bool:
        """True when we have *a* value to show (fresh or cached). The UI renders
        a dash only when this is False."""
        return self.ok


class ReadCache:
    """Tiny last-good store keyed by read name (per device). Survives across
    calls so a transient unanswered query falls back to the last value."""
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    def put(self, key: str, value: Any) -> None:
        self._values[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._values


def _default_validate(value: Any) -> bool:
    return value is not None


async def read_with_retry(
    factory: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 2,
    timeout: float = 2.5,
    validate: Optional[Callable[[Any], bool]] = None,
    cache: Optional[ReadCache] = None,
    cache_key: Optional[str] = None,
    sleep=asyncio.sleep,
    retry_delay: float = 0.25,
) -> ReadResult:
    """Run ``factory()`` (a fresh read coroutine per attempt) with a bounded
    retry + per-attempt timeout. A valid value is cached and returned fresh; on
    exhaustion, a cached last-good value is returned (``from_cache=True``) or, if
    none, a typed ``ok=False`` reason the UI renders as unknown."""
    validate = validate or _default_validate
    last_reason = FailureReason.TIMEOUT
    detail = ""
    for attempt in range(attempts):
        try:
            value = await asyncio.wait_for(factory(), timeout=timeout)
            if validate(value):
                if cache is not None and cache_key is not None:
                    cache.put(cache_key, value)
                return ReadResult(True, value, from_cache=False)
            last_reason = FailureReason.DROPPED   # replied, but with junk/empty
            detail = "read returned an invalid/empty value"
        except asyncio.TimeoutError:
            last_reason = FailureReason.TIMEOUT
            detail = f"no reply within {timeout}s"
        except Exception as e:  # noqa: BLE001 — a flaky read shouldn't raise out
            last_reason = FailureReason.UNKNOWN
            detail = str(e)
        logger.debug("read %s attempt %d/%d: %s (%s)",
                     cache_key, attempt + 1, attempts, last_reason.value, detail)
        if attempt < attempts - 1:
            await sleep(retry_delay)

    # Exhausted — degrade gracefully to the last known value if we have one.
    if cache is not None and cache_key is not None and cache_key in cache:
        logger.info("read %s unanswered; serving last-good cached value", cache_key)
        return ReadResult(True, cache.get(cache_key), from_cache=True,
                          reason=last_reason, detail=detail)
    return ReadResult(False, None, reason=last_reason, detail=detail)
