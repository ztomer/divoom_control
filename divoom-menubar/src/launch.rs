//! Launching the Python GUI + quit lifecycle. The menubar is spawned BY the GUI,
//! which passes its own launch command via env (`DIVOOM_GUI_PYTHON` +
//! `DIVOOM_GUI_SCRIPT`) so the menubar can relaunch the dashboard exactly the way
//! the pyobjc menubar did (`subprocess.Popen([python, gui_main.py, ...])`). Quit
//! respects `keep_daemon_alive` from the shared config.ini (parity with
//! `lifecycle_config`): shared lifecycle → ask the daemon to shut down.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::daemon;

/// The command that opens the dashboard: `(program, args)`.
///
/// A frozen app (`DIVOOM_GUI_PYTHON` is `<X>.app/Contents/MacOS/<exe>` with no
/// script) is opened THROUGH Launch Services, `open -a <X>.app --args ...`.
/// Exec'ing the bundle's executable from here made the GUI this agent's
/// CHILD: it ran in this agent's coalition, so when the GUI quit,
/// Launch Services kept its record alive under the live agent (the D.CFXSBX
/// failure, P1.18), and the dead child sat as a zombie (pid 30134 on
/// 2026-11-02, defunct under agent 42068). Through `open` it is an app of its
/// own. A source launch (`python gui_main.py`) has no bundle to open, so it
/// is still exec'd -- and reaped (see [`dashboard`]).
fn dashboard_command(
    python: &std::ffi::OsStr,
    script: Option<&std::ffi::OsStr>,
    extra: &[&str],
) -> (PathBuf, Vec<std::ffi::OsString>) {
    let mut args: Vec<std::ffi::OsString> = Vec::new();
    if let Some(s) = script.filter(|s| !s.is_empty()) {
        args.push(s.to_os_string());
        args.extend(extra.iter().map(std::ffi::OsString::from));
        return (PathBuf::from(python), args);
    }
    let exe = PathBuf::from(python);
    let bundle = exe
        .parent()
        .filter(|macos| macos.file_name().is_some_and(|n| n == "MacOS"))
        .and_then(Path::parent)
        .filter(|contents| contents.file_name().is_some_and(|n| n == "Contents"))
        .and_then(Path::parent)
        .filter(|app| app.extension().is_some_and(|e| e == "app"));
    if let Some(app) = bundle {
        args.push("-a".into());
        args.push(app.as_os_str().to_os_string());
        if !extra.is_empty() {
            args.push("--args".into());
            args.extend(extra.iter().map(std::ffi::OsString::from));
        }
        return (PathBuf::from("/usr/bin/open"), args);
    }
    args.extend(extra.iter().map(std::ffi::OsString::from));
    (exe, args)
}

/// Launch the pywebview dashboard. `extra` appends args (e.g. the notifications
/// deep-link `--tab data-sources --card notifications`). The GUI's own
/// single-instance guard prevents duplicate windows.
///
/// The child is always WAITED for, on a thread of its own: a child nobody
/// waits for is a zombie for the rest of this agent's life.
pub fn dashboard(extra: &[&str]) {
    let Some(python) = std::env::var_os("DIVOOM_GUI_PYTHON") else {
        eprintln!("divoom-menubar: DIVOOM_GUI_PYTHON not set — can't launch the dashboard");
        return;
    };
    let script = std::env::var_os("DIVOOM_GUI_SCRIPT");
    let (program, args) = dashboard_command(&python, script.as_deref(), extra);
    let mut cmd = Command::new(program);
    cmd.args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Ok(mut child) = cmd.spawn() {
        std::thread::spawn(move || {
            let _ = child.wait();
        });
    }
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

#[cfg(test)]
mod tests {
    use super::dashboard_command;
    use std::ffi::{OsStr, OsString};
    use std::path::PathBuf;

    fn strs(v: &[OsString]) -> Vec<&str> {
        v.iter().map(|a| a.to_str().expect("utf8")).collect()
    }

    /// The frozen app is opened through Launch Services, never exec'd as this
    /// agent's child (D.HELPER, P1.18).
    #[test]
    fn a_frozen_app_is_opened_through_launchservices() {
        let (prog, args) = dashboard_command(
            OsStr::new("/Applications/Divoom.app/Contents/MacOS/Divoom"),
            Some(OsStr::new("")),
            &["--tab", "data-sources"],
        );
        assert_eq!(prog, PathBuf::from("/usr/bin/open"));
        assert_eq!(
            strs(&args),
            [
                "-a",
                "/Applications/Divoom.app",
                "--args",
                "--tab",
                "data-sources"
            ]
        );
        let (_, plain) = dashboard_command(
            OsStr::new("/Applications/Divoom.app/Contents/MacOS/Divoom"),
            None,
            &[],
        );
        assert_eq!(strs(&plain), ["-a", "/Applications/Divoom.app"]);
    }

    /// A source launch has no bundle: python runs the script with the args.
    #[test]
    fn a_source_launch_runs_the_script() {
        let (prog, args) = dashboard_command(
            OsStr::new("/usr/bin/python3"),
            Some(OsStr::new("/repo/divoom_gui/gui_main.py")),
            &["--tab", "x"],
        );
        assert_eq!(prog, PathBuf::from("/usr/bin/python3"));
        assert_eq!(strs(&args), ["/repo/divoom_gui/gui_main.py", "--tab", "x"]);
    }

    /// An executable that is not inside a bundle is run directly.
    #[test]
    fn a_bare_launcher_is_run_directly() {
        let (prog, args) = dashboard_command(OsStr::new("/opt/bin/divoom-gui"), None, &["-v"]);
        assert_eq!(prog, PathBuf::from("/opt/bin/divoom-gui"));
        assert_eq!(strs(&args), ["-v"]);
    }
}
