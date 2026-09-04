//! Launching the Python GUI + quit lifecycle. The menubar is spawned BY the GUI,
//! which passes its own launch command via env (`DIVOOM_GUI_PYTHON` +
//! `DIVOOM_GUI_SCRIPT`) so the menubar can relaunch the dashboard exactly the way
//! the pyobjc menubar did (`subprocess.Popen([python, gui_main.py, ...])`). Quit
//! respects `keep_daemon_alive` from the shared config.ini (parity with
//! `lifecycle_config`): shared lifecycle → ask the daemon to shut down.

use std::path::PathBuf;
use std::process::{Command, Stdio};

use crate::daemon;

/// Launch the pywebview dashboard. `extra` appends args (e.g. the notifications
/// deep-link `--tab data-sources --card notifications`). The GUI's own
/// single-instance guard prevents duplicate windows.
pub fn dashboard(extra: &[&str]) {
    let Some(python) = std::env::var_os("DIVOOM_GUI_PYTHON") else {
        eprintln!("divoom-menubar: DIVOOM_GUI_PYTHON not set — can't launch the dashboard");
        return;
    };
    let mut cmd = Command::new(python);
    // A non-empty DIVOOM_GUI_SCRIPT means a source/py2app launch (python <script>);
    // an empty/unset one means a frozen PyInstaller .app where DIVOOM_GUI_PYTHON is
    // itself the GUI launcher, so we run it directly with just the deep-link args.
    match std::env::var_os("DIVOOM_GUI_SCRIPT") {
        Some(s) if !s.is_empty() => {
            cmd.arg(s).args(extra);
        }
        _ => {
            cmd.args(extra);
        }
    }
    cmd.stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    let _ = cmd.spawn();
}

pub fn open_dashboard() {
    dashboard(&[]);
}

pub fn open_notifications() {
    dashboard(&["--tab", "data-sources", "--card", "notifications"]);
}

/// Quit: on shared lifecycle (the default) ask the daemon to shut down so the GUI
/// follows it down; on keep-alive just leave the daemon running. Either way the
/// caller exits the menubar afterwards.
pub fn quit() {
    if !keep_daemon_alive() {
        daemon::shutdown();
    }
}

/// Read `[gui] keep_daemon_alive` from `~/.config/divoom-control/config.ini`
/// (default false → shared lifecycle). Minimal hand-parse — no ini crate.
fn keep_daemon_alive() -> bool {
    let Some(path) = config_path() else {
        return false;
    };
    let Ok(text) = std::fs::read_to_string(path) else {
        return false;
    };
    let mut in_gui = false;
    for raw in text.lines() {
        let line = raw.trim();
        if line.starts_with('[') && line.ends_with(']') {
            in_gui = line.eq_ignore_ascii_case("[gui]");
            continue;
        }
        if !in_gui {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            if k.trim().eq_ignore_ascii_case("keep_daemon_alive") {
                return matches!(
                    v.trim().to_ascii_lowercase().as_str(),
                    "1" | "true" | "yes" | "on"
                );
            }
        }
    }
    false
}

fn config_path() -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    Some(PathBuf::from(home).join(".config/divoom-control/config.ini"))
}
