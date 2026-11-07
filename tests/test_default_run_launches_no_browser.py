"""The default run (no --run-browser) launches no browser, not even camoufox's GPU probe (D.REV3).

camoufox 0.5.9's ``launch_options`` LAUNCHES A BROWSER to read the host GPU
(``camoufox/host_rendering.py`` ``_host_gpu``) whenever the drawn OS is the
host's, which the seam always asks for. The default run reads launch options
without launching anything (the offline proxy, the window draw, the fpgen
shim), and each such read started a whole camoufox tree: sampled 2026-11-07,
two probe browsers and seven camoufox processes during
``tests/test_fpgen_compat.py`` + ``tests/test_e2e_offline_browser.py``, in a run
that never asked for a browser.
"""

from __future__ import annotations

import pytest

pytest.importorskip("camoufox.utils")


def test_reading_the_options_launches_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    import camoufox.host_rendering as hr

    from tests.support.browser_options import launch_options_for

    probes = []
    monkeypatch.setattr(hr, "_host_gpu", lambda *a: probes.append(a))
    launch_options_for(network=False, launching=False)
    assert probes == [], "reading the launch options launched camoufox's GPU-probe browser"


def test_launching_options_do_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction: options a launch is about to use keep camoufox's probe,
    so the identity claims the GPU the pixels come from."""
    import camoufox.host_rendering as hr

    from tests.support.browser_options import launch_options_for

    probes = []
    monkeypatch.setattr(hr, "_host_gpu", lambda *a: probes.append(a))
    launch_options_for(network=False, launching=True)
    assert len(probes) == 1


def test_the_seam_says_whether_it_launches() -> None:
    """No default: a caller that forgets is a TypeError, never a silent probe."""
    from tests.support.browser_options import launch_options_for

    with pytest.raises(TypeError):
        launch_options_for(network=False)  # type: ignore[call-arg]


def test_the_default_run_refuses_any_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The class, not the instance: whatever launches a browser in a run without
    --run-browser (a library's probe included) is refused before it starts."""
    from tests.support import browser_reaper as R

    started = []
    launch = R._wrap(lambda self, *a, **k: started.append(1))
    monkeypatch.setattr(R, "LAUNCH_ALLOWED", False)
    with pytest.raises(R.BrowserLaunchRefused):
        launch(None)
    assert started == []
    monkeypatch.setattr(R, "LAUNCH_ALLOWED", None)  # a script, outside pytest
    monkeypatch.setattr(R, "register_launched", lambda: [])
    launch(None)
    assert started == [1]


def test_this_session_enforces_its_opt_in(pytestconfig: pytest.Config) -> None:
    from tests.support import browser_reaper as R

    assert R.LAUNCH_ALLOWED is bool(pytestconfig.getoption("--run-browser"))
