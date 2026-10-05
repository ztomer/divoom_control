"""The one place the GUI e2e suites get a browser.

Before R66 each of the 15 e2e modules called
``p.chromium.launch(headless=True)`` itself and guarded with
``pytest.importorskip("playwright.async_api")``. Two problems, both fixed here:

1. **The guard did not guard.** ``importorskip`` only checks that the Python
   MODULE imports. It says nothing about the browser BINARY, so a machine with
   the playwright package but no downloaded browser did not skip -- it raised
   ``BrowserType.launch: Executable doesn't exist`` and produced **69 failures**
   that read exactly like real regressions (measured 2026-08-17 on a clean
   checkout). ``require_browser()`` probes the binary, so a missing browser
   skips like it always claimed to.

2. **The engine was copy-pasted 17 times.** Swapping it meant touching every
   file, which is why it never happened. It is now one function.

Version: CI pins the **browser build** to ``official/stable/156.0.1-beta.34``
(the current latest on that channel) via ``camoufox set``, with the pip package
at 0.5.5. Pinning the package is NOT sufficient on its own -- camoufox accepts
any build in ``[alpha.1, 1)``, so a bare ``camoufox fetch`` takes the newest one
regardless, and the build is the half that decides whether the suite passes.

**Keep the pin, keep it CURRENT.** The pin buys determinism -- a red run means a
code change, not "the browser moved" -- and determinism comes from naming a
SPECIFIC build, not from naming an OLD one. It was moved off 152.0.4-beta.29 on
2026-10-04, two releases late: by then beta.29 had been superseded twice and was
no longer even installed on the machine running the suite, so the pin had stopped
describing reality. Verified on 156.0.1-beta.34: 165 passed / 1 failed across the browser
suites and 14/14 in ``test_main_world_bridge.py``, which is this module's own
claim working -- "when the browser next moves the goalposts, it is one function
again". Move it forward in its own commit when the channel moves, with the
suites run against the candidate first.

**The isolated world.** From build 152.0.4-beta.29 (2026-08-20) page scripting
runs in an ISOLATED WORLD, so main-world globals the app defines --
``window.DivoomState`` and every render function -- read as ``undefined``. The
page itself is fine: probed on 2026-08-30, all 29 scripts fetch 200, the DOM
builds, and there is not a single console or page error. Only the *view*
changed, which is why that upgrade turned CI red on 2026-08-25 with 60 failures
and no code change.

That 60 is HISTORY, not a standing cost. It is what the transition cost BEFORE
the three bridges below existed, and it is the reason they were written. Later
builds -- including the current pin -- cost nothing: the suites pass on them. Do
not cite it as evidence that moving forward is expensive; measure it, which is
one ``pytest --run-browser`` run against the candidate build.

Three separate holes had to be closed, and only the first was known:

1. ``page.evaluate`` reaches the main world again through an ``mw:`` script
   prefix, enabled by ``main_world_eval=True`` at launch. BOTH are required:
   the flag alone does not restore the old default, and the prefix without the
   flag raises "Main world evaluation is disabled". See :func:`eval_js`.

2. **``wait_for_function`` has no main-world form at all.** Probed 2026-08-30
   across camoufox 0.5.4 and 0.5.5 on beta.29: with ``mw:`` and the launch flag
   both on, ``page.wait_for_function("mw:window.MARKER === 42")`` still times
   out, while the identical expression through ``page.evaluate`` returns 42.
   camoufox documents the prefix for ``evaluate`` only. So the migration this
   module's earlier note described -- "prefix every evaluate /
   wait_for_function" -- was only half possible. :func:`wait_js` polls
   ``evaluate`` instead.

3. **``add_init_script`` has no main-world form either**, which matters more
   than it sounds: the suites mock the backend by defining ``window.__api``
   before the app's own scripts read it. All four spellings (page/context,
   plain, ``mw:``-prefixed, keyword) leave the page unable to see what they
   installed. :func:`add_init_js` bridges it the way userscripts always have --
   see :func:`main_world_bootstrap`.

Everything goes through these helpers rather than each suite prefixing its own
strings. This module already exists because the launch call was copy-pasted 17
times and swapping it meant touching every file; 191 open-coded ``mw:`` prefixes
would rebuild that exact problem one layer up. When the browser next moves the
goalposts, it is one function again.

Engine: **camoufox** (anti-detect Firefox) rather than Chromium. It is the house
browser-automation transport (see the ``gemini-camoufox`` skill), so this
consolidates on one engine instead of also carrying a ~130 MB Chromium download
that every fresh dev environment silently failed without. camoufox exposes
``launch_options()`` -- executable_path/args/env/firefox_user_prefs -- which makes
``p.firefox.launch(**opts)`` a drop-in for the old chromium call, so the suites
keep their existing ``async_playwright()`` structure.
"""

from __future__ import annotations

import json
import os
import time

import pytest

# How long a UI wait may take before a test gives up.
#
# This is a BUDGET, not an assertion. No e2e test here measures how FAST the UI
# is; every wait asserts that a condition EVENTUALLY holds. So a tight budget
# cannot catch a defect a generous one misses — it can only turn a momentarily
# slow machine into a red test that reads like a regression. The suites had
# ~47 ad-hoc budgets (16x 2000ms, 14x 4000ms, 7x 5000ms), each invented at its
# call site, and on 2026-08-23 two of them went red during a release while the
# machine was busy with a py2app build: the same suite that normally finishes
# in 372s took 618s.
#
# Deliberately NOT applied to absence assertions ("this must not appear"),
# where a short timeout IS the assertion. Those keep their own explicit values.
#
# Sized from a measurement, not a guess (2026-09-12, v0.37 step 5): the whole
# subset (150 tests) run twice under a CPU burner on half the cores plus a
# cargo-check loop, load average 30-130, went 150/150 both times in 597s and
# 587s against 412s unloaded -- but the SAME readiness wait that takes 3s
# unloaded took 16s under load (test_e2e_widget_selection, a 5x swing), 3s
# short of the old 20s budget. Since every wait returns the moment its
# condition holds, a larger cap costs nothing on a green run and only
# lengthens a red one, so the cap carries the measured swing with margin.
# Override with DIVOOM_E2E_TIMEOUT_MS.
UI_TIMEOUT_MS = int(os.environ.get("DIVOOM_E2E_TIMEOUT_MS", "60000"))


#: Set by ``tests/conftest.py`` from ``--run-browser``. The opt-in lives HERE,
#: at the one seam every browser launch goes through, rather than in a scan of
#: each module's text for the word "playwright": that scan skipped WHOLE
#: modules, and two of them (the round-6 layout suite, the stack-teardown
#: suite) were mostly source-grep and subprocess tests that never touch a
#: browser -- 30-odd tests hidden by default, two of them stale for months
#: (found 2026-09-12).
RUN_BROWSER = False


def require_browser() -> None:
    """Skip the test unless browser tests are opted in AND a launchable
    browser is actually present.

    Checks the binary, not just the import — that distinction is the whole
    point of this helper.
    """
    if not RUN_BROWSER:
        pytest.skip("launches a real browser; run with --run-browser")
    pytest.importorskip("playwright.async_api")
    pytest.importorskip("camoufox.utils")
    try:
        from camoufox.pkgman import installed_verstr

        version = installed_verstr()
    except Exception as exc:  # not downloaded, or pkgman API moved
        pytest.skip(f"camoufox browser unavailable ({exc}) — run: python3 -m camoufox fetch")
    if not version:
        pytest.skip("camoufox browser not downloaded — run: python3 -m camoufox fetch")


async def launch(p):
    """Launch the e2e browser from an ``async_playwright()`` instance.

    Drop-in for the old ``p.chromium.launch(headless=True)``.

    Calls :func:`require_browser` itself -- see the note on :func:`launch_sync`.
    """
    require_browser()
    from camoufox.utils import launch_options

    return await p.firefox.launch(**launch_options(headless=True, main_world_eval=True))


def launch_sync(p):
    """Sync-API counterpart of :func:`launch`.

    Drop-in for ``p.chromium.launch(headless=True)`` under ``sync_playwright()``.
    Two suites (wall-canvas drag, the live-widgets diagnostic) use the sync API.

    The guard lives HERE, not only at each call site. R66 asked all 15 e2e
    modules to call ``require_browser()``; 13 did. The two that did not were
    exactly the two sync-API ones, so on a machine with no browser they ERRORED
    (``CamoufoxNotInstalled`` at fixture setup) while the other 13 skipped --
    CI run 32654312489, 6 errors. A guard you have to remember to call is not a
    guard, so getting a browser now requires passing it by construction.
    """
    require_browser()
    from camoufox.utils import launch_options

    return p.firefox.launch(**launch_options(headless=True, main_world_eval=True))


# ── Reaching the page's main world ────────────────────────────────────────────

#: camoufox's opt-in prefix for running a script in the page's main world.
MAIN_WORLD_PREFIX = "mw:"

#: How often :func:`wait_js` re-evaluates its condition.
#:
#: ``wait_for_function`` used the browser's own scheduler; polling is the price
#: of it having no main-world path. 50ms is well under any UI transition these
#: suites assert on, and the cost is bounded by the timeout, not the interval.
POLL_INTERVAL_MS = 50


def main_world(script: str) -> str:
    """Prefix ``script`` so camoufox evaluates it in the page's main world.

    Idempotent, so a caller that has already prefixed does not end up with
    ``mw:mw:``. Leading whitespace is stripped because the suites pass
    triple-quoted scripts that begin with a newline, and the prefix has to be
    the first thing camoufox sees.
    """
    stripped = script.lstrip()
    if stripped.startswith(MAIN_WORLD_PREFIX):
        return stripped
    return MAIN_WORLD_PREFIX + stripped


def eval_js(page, script: str, *args):
    """``page.evaluate`` against the page's MAIN world.

    Returns whatever ``page.evaluate`` returns, so this is a drop-in under both
    playwright APIs: awaitable under the async one, a plain value under the sync
    one. That is deliberate -- a suite does ``return page.evaluate(...)`` from an
    async helper without awaiting, and a version that awaited internally would
    silently change its meaning.

    Without the main world the app's globals are invisible and every assertion
    reads ``None``, which looks exactly like a broken feature rather than a
    browser that changed under the suite.
    """
    return page.evaluate(main_world(script), *args)


class MainWorldTimeout(AssertionError):
    """A :func:`wait_js` condition never became truthy.

    An ``AssertionError`` rather than a playwright ``TimeoutError`` because that
    is what it is: the suite asserted a condition would eventually hold, and it
    did not. The message carries the script, so a failure names the condition
    instead of only a line number.
    """


async def wait_js(page, script: str, *, timeout: int | None = None):
    """Main-world replacement for ``page.wait_for_function`` (async API).

    ``timeout`` is in milliseconds, matching playwright's own signature, and
    defaults to :data:`UI_TIMEOUT_MS`.

    Polls :func:`eval_js` because camoufox's ``mw:`` prefix is implemented for
    ``evaluate`` only -- ``wait_for_function`` stays in the isolated world no
    matter what is prefixed or which launch flags are set (probed 2026-08-30).

    Evaluation errors are swallowed while waiting, on purpose: a condition that
    reads ``window.Foo.bar`` legitimately throws until ``Foo`` exists, and that
    is the normal case this function is for. A condition that throws forever
    still fails, via the timeout, with the last error in its message.

    Async only. All 62 waits in the suite are in async tests; the two sync
    suites wait on selectors, which the isolated world sees perfectly well. A
    sync counterpart is the same loop with ``page.wait_for_timeout``, and is not
    written until something needs it -- an untested helper kept "just in case"
    is where the next surprise hides.
    """
    import asyncio

    budget_ms = UI_TIMEOUT_MS if timeout is None else timeout
    deadline = time.monotonic() + budget_ms / 1000
    last_error: Exception | None = None
    while True:
        try:
            value = await eval_js(page, script)
            if value:
                return value
            last_error = None
        except Exception as exc:  # not ready yet -- see docstring
            last_error = exc
        if time.monotonic() >= deadline:
            raise MainWorldTimeout(_timeout_message(script, budget_ms, last_error))
        await asyncio.sleep(POLL_INTERVAL_MS / 1000)


# ── Waiting on ONE toast ─────────────────────────────────────────────────────

#: The id of the app's one toast element (``index.html:603``).
TOAST_ELEMENT_ID = "toast"

#: Records every toast the app raises, from ``document_start``, with what the
#: element held immediately afterwards.
#:
#: ``showToast`` (``divoom_gui/web_ui/app_globals.js:30``) takes ``(message,
#: type, transport)`` and writes ONE element every time — ``className = "toast
#: <type> show"``, ``innerHTML = message + <span class="toast-transport">``,
#: then a 3s timer drops ``show``. It has no id, no history, and no queue, and
#: it is the only writer of that element in the whole app. So a toast's identity
#: is its rendered text plus its kind class plus its transport marker, and
#: nothing about "a toast exists" identifies one: ``app_init.js:281`` raises
#: "Startup: Auto-scanning screens..." about a second after load and the scan
#: behind it answers with its own failure, on timers no test controls, in every
#: e2e page.
#:
#: A ``defineProperty`` trap rather than a spy assignment, because it is in place
#: BEFORE ``app_globals.js`` defines the real function: a spy installed after
#: load is invisible to any code that captured ``window.showToast`` into a local
#: first, which is not a hypothetical (that is how ``.catch(showToast)``-shaped
#: code behaves).
#:
#: Each entry snapshots the element AFTER the app wrote it, so the record is what
#: the user saw rather than what the caller asked for — a call with no ``#toast``
#: to render into records ``rendered: null`` and can never satisfy a wait.
TOAST_RECORDER_JS = """
(() => {
  const history = [];
  let real = null;
  const mark = (fn) => { try { fn.__divoomToastRecorder = true; } catch (e) {} };
  const snapshot = () => {
    const el = document.getElementById(%(element)s);
    if (!el) return null;
    const span = el.querySelector('.toast-transport');
    return {
      text: el.textContent || '',
      className: el.className || '',
      transport: span ? (span.textContent || '').trim() : '',
    };
  };
  Object.defineProperty(window, 'showToast', {
    configurable: true,
    get() { return real; },
    set(fn) {
      mark(fn);
      real = function (...args) {
        const out = fn.apply(this, args);
        history.push({
          message: args.length ? String(args[0]) : '',
          type: args.length > 1 && args[1] !== undefined ? String(args[1]) : 'success',
          transport: args.length > 2 && args[2] != null ? String(args[2]).trim() : '',
          rendered: snapshot(),
        });
        return out;
      };
      mark(real);
    },
  });
  window.__divoomToasts = history;
})();
""" % {"element": json.dumps(TOAST_ELEMENT_ID)}


class ToastRecorderMissing(AssertionError):
    """A toast wait ran on a page with no recorder installed.

    An ``AssertionError`` like :class:`MainWorldTimeout`: the test asked for
    something the harness was not in a position to see. Named rather than left
    to time out, because "condition never became true" for a wait whose
    recorder does not exist is a 60s lie about a one-line omission.
    """


async def install_toast_recorder(page):
    """Record this page's toasts. Call BEFORE ``page.goto``.

    The recorder has to exist before the app's scripts run, so this is an init
    script (main world, via :func:`add_init_js`) rather than an assignment made
    after load — see :data:`TOAST_RECORDER_JS`. Idempotent in the sense that
    matters: it must be called once per page, before navigation.
    """
    await add_init_js(page, TOAST_RECORDER_JS)


def toast_condition(
    needle: str,
    *,
    kind: str | None = None,
    transport: str | None = None,
) -> str:
    """The main-world script :func:`wait_toast` polls, as source text.

    Split out from the wait so the CONDITION can be asserted on without a
    browser (``test_main_world_bridge.py``): the failure being fixed here is a
    wrong condition, and a wrong condition is only catchable if something can
    read it.

    Matches on the RECORDED, RENDERED toast — its text, its kind class, its
    transport marker — and never on how many toasts there are. Returns the
    matching entry (truthy, so :func:`wait_js` hands it straight back and the
    caller asserts on the same thing the wait matched) or ``null``.
    """
    parts = [
        "() => {",
        "  const h = window.__divoomToasts;",
        "  if (!Array.isArray(h)) return null;",
        f"  const needle = {json.dumps(needle)};",
        "  const hit = h.find(t => t.rendered",
        "    && t.rendered.text.indexOf(needle) >= 0",
    ]
    if kind is not None:
        parts += [
            "    && String(t.rendered.className).split(/\\s+/)",
            f"        .indexOf({json.dumps(kind)}) >= 0",
        ]
    if transport is not None:
        parts.append(f"    && t.rendered.transport === {json.dumps(transport)}")
    parts += ["  );", "  return hit || null;", "}"]
    return "".join(parts)


async def wait_toast(
    page,
    needle: str,
    *,
    kind: str | None = None,
    transport: str | None = None,
    timeout: int | None = None,
):
    """Wait for THIS test's toast, and return its record.

    ``needle`` is a substring the awaited toast's RENDERED text must carry, so a
    toast this test did not create cannot satisfy the wait; ``kind`` and
    ``transport`` narrow it further where the claim is about those. ``kind`` is
    one of the classes ``showToast`` writes — ``success`` (its default),
    ``error``, ``warning``.

    Returns ``{message, type, transport, rendered}`` where ``rendered`` is
    ``{text, className, transport}`` — the element as the user saw it the moment
    this toast fired, captured inside the call rather than sampled afterwards.

    Why not wait on the live element: it is one element reused for every toast,
    so a later toast overwrites it. Polling it is a SAMPLING race — the toast
    being waited for can arrive and be replaced inside one poll interval, and the
    wait then times out on a toast that was genuinely shown. Measured 2026-10-04,
    the app's own scan toasts land 1.0-2.9s after load while the awaited one
    lands 0-50ms after its click, so that window is routinely inside the span
    where a test's click happens.

    Why not count them, or wait for the ``show`` class: both are satisfied by the
    toasts the app raises on its own, which is what made these waits
    order-dependent — green in isolation, red in a full run.

    Requires :func:`install_toast_recorder` on the page; without it this raises
    :class:`ToastRecorderMissing` naming the omission rather than timing out.
    """
    if await eval_js(page, "() => Array.isArray(window.__divoomToasts)") is not True:
        raise ToastRecorderMissing(
            "no toast recorder on this page — call "
            "await install_toast_recorder(page) before page.goto() "
            "(tests.support.browser)")
    return await wait_js(
        page, toast_condition(needle, kind=kind, transport=transport), timeout=timeout
    )


def _timeout_message(script: str, budget_ms: int, last_error: Exception | None) -> str:
    condition = " ".join(script.split())
    if len(condition) > 200:
        condition = condition[:197] + "..."
    tail = ""
    if last_error is not None:
        tail = f"; last evaluation raised {type(last_error).__name__}: {last_error}"
    return f"condition never became true within {budget_ms}ms: {condition}{tail}"


def main_world_bootstrap(source: str) -> str:
    """Wrap ``source`` so an init script installs it in the page's MAIN world.

    The way through is the one userscripts have always used for
    ``@run-at document-start``: the isolated world shares the DOM, and a
    ``<script>`` element appended to the document executes in the MAIN world.
    So the init script (isolated) builds a ``<script>`` carrying ``source`` and
    inserts it; the browser runs it in the page's own world.

    ``document.documentElement`` does not necessarily exist yet at
    document_start, hence the MutationObserver fallback -- without it this
    silently does nothing on whichever page happens to parse slightly
    differently, and a mock that silently fails to install is indistinguishable
    from a feature that is broken.

    Ordering is what makes it correct, and it holds: probed 2026-08-30 on a page
    whose own ``<head>`` script appends to a marker array, the result is
    ``['mock', 'app']`` -- the injected source ran first.
    """
    literal = json.dumps(source)
    return (
        "(() => {"
        "  const s = document.createElement('script');"
        f" s.textContent = {literal};"
        "  const install = (root) => { root.insertBefore(s, root.firstChild); s.remove(); };"
        "  const root = document.documentElement;"
        "  if (root) { install(root); return; }"
        "  new MutationObserver((_, obs) => {"
        "    const r = document.documentElement;"
        "    if (r) { obs.disconnect(); install(r); }"
        "  }).observe(document, {childList: true, subtree: true});"
        "})();"
    )


def add_init_js(page, source: str):
    """``page.add_init_script`` that the PAGE can actually see.

    Drop-in for ``page.add_init_script(source)``: returns whatever playwright
    returns, so it awaits under the async API and does not under the sync one.
    """
    return page.add_init_script(main_world_bootstrap(source))
