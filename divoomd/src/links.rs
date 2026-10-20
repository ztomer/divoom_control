//! What this daemon holds, remembered across a restart (P2.7's remainder).
//!
//! Traced on 2026-10-18 (Pixoo-1, v0.41.2): with the GUI running, three
//! SIGTERMs of the daemon each had the GUI respawn a new one and nothing
//! else — no `connect` for 60 s, `device_status` `devices: []`, and the panel
//! stayed dark until the user clicked it. The cause was that a daemon starts
//! with an empty fleet and the only thing that knew which panels to link was
//! a CLIENT: the GUI, which remembered its own panels and asked for them
//! back (`divoom_gui/panel_relink.py`).
//!
//! That fixes the GUI's panels and nothing else. A panel a CLI or an MCP
//! client linked had no client left holding the memory, and a wall's slots
//! were never a link at all (`MatrixWall` connect links nothing itself), so
//! both stayed dark after a restart until a human clicked.
//!
//! So the daemon remembers what it holds. Every link it adopts is written
//! down — the id and the connect request that made it — and every link the
//! user drops is forgotten. On startup the daemon replays that list, one
//! panel at a time (BLE refuses a second concurrent connect), and then
//! restores the wall. The GUI's own relink stays: it is the client's path,
//! it works when this file was lost, and the two agree because the daemon
//! skips a panel it already holds.
//!
//! WHERE THE LIST LIVES. `~/.config/divoom-control/links.json`, or the file
//! `DIVOOM_LINKS_PATH` names. It is a plain record of what was connected —
//! not a secret, not a cache of anything derivable — and it is written
//! atomically (temp file + rename) so a crash mid-write cannot leave a
//! half-written list that reads as "no panels" and silently drops the user's
//! panels on the next start.
//!
//! WHO WRITES IT. Only a daemon that was given a path writes one: the
//! PROCESS (`main.rs`) decides, a `Daemon` value built by a test does not.
//! Without that rule every test that connects a panel would write the
//! developer's real list, and a test that disconnects everything would
//! ERASE it.
//!
//! A MOCK panel is a test double, not a panel: the daemon's default list
//! belongs to the user's panels, and a mock written into it would send every
//! later start looking for a device called `MOCK_MAC` on the radio. So a
//! mock is written down only when the list was NAMED (`DIVOOM_LINKS_PATH`) —
//! which is exactly what a test does when it wants a mock remembered.

use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::path::PathBuf;

use crate::daemon::Daemon;
use crate::protocol::{make_request, ErrorCode};

/// How long the daemon waits before it starts restoring, so the client that
/// started it gets the radio first.
///
/// The GUI connects its saved panel the moment the daemon answers, and BLE
/// allows one connect at a time: a restore that grabbed the radio first
/// would answer the GUI's connect with `busy`, and the GUI's startup connect
/// would fail. The restore is the BACKSTOP (it covers the CLI, the MCP
/// server and the wall, which have no client-side memory), so it waits.
const RESTORE_DELAY: std::time::Duration = std::time::Duration::from_secs(2);

/// How long to wait before retrying a link whose connect was refused because
/// the radio was busy. A client mid-connect is a few seconds at most.
const BUSY_RETRY_DELAY: std::time::Duration = std::time::Duration::from_millis(750);

/// How many times to retry a busy connect before giving the panel up. The
/// panel stays in the saved list either way, so the next daemon start tries
/// again.
const BUSY_RETRIES: usize = 8;

/// One panel this daemon holds, and the connect request that made it.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WantedLink {
    /// The id the fleet knows it by: a mac, or `LAN:<ip>`.
    pub id: String,
    /// The `connect` arguments that produced the link, replayed verbatim.
    pub args: Value,
}

/// The wall this daemon holds: its slots and the cell size they were laid
/// out with.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WantedWall {
    pub slots: Map<String, Value>,
    pub cell_size: i64,
}

/// The saved list, as it is on disk.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct State {
    #[serde(default)]
    pub links: Vec<WantedLink>,
    #[serde(default)]
    pub wall: Option<WantedWall>,
}

/// Where the list lives, and whether that path was NAMED by the operator
/// (`DIVOOM_LINKS_PATH`) rather than derived from the config directory.
#[derive(Clone, Debug)]
pub struct Location {
    pub path: PathBuf,
    /// Named, not derived: a mock panel may be written into a named list.
    pub named: bool,
}

/// The list's location: the file the operator named, or the one in the
/// config directory.
#[must_use]
pub fn resolve_location() -> Option<Location> {
    if let Ok(p) = std::env::var("DIVOOM_LINKS_PATH") {
        if !p.is_empty() {
            return Some(Location {
                path: PathBuf::from(p),
                named: true,
            });
        }
    }
    let mut dir = crate::cloud::config_dir()?;
    dir.push("links.json");
    Some(Location {
        path: dir,
        named: false,
    })
}

/// Read the saved list from `path`.
///
/// A file that is missing, unreadable or not the shape this daemon writes
/// reads as "nothing saved": the daemon starts with an empty fleet either
/// way, and a corrupt file must not keep it from starting.
#[must_use]
pub fn load_from(path: &std::path::Path) -> State {
    let Ok(text) = std::fs::read_to_string(path) else {
        return State::default();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

/// Write the saved list to `path`, atomically: a temp file beside it, then a
/// rename.
///
/// A half-written list would read as "no panels" and silently drop the
/// user's panels on the next start.
///
/// # Errors
///
/// When the list cannot be written: no directory to write it in, or the
/// filesystem refused the write.
pub fn save_to(path: &std::path::Path, state: &State) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let text = serde_json::to_string_pretty(state).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, text).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

/// The daemon's saved list, and the only writer of it.
pub struct Wanted {
    inner: tokio::sync::Mutex<State>,
    /// Where the list is written. `None` = this daemon keeps no list.
    path: Option<PathBuf>,
    /// The path was named by the operator, so a mock may be written into it.
    named: bool,
}

impl Default for Wanted {
    fn default() -> Self {
        Self::none()
    }
}

impl Wanted {
    /// A daemon that keeps no list: nothing is written, nothing is restored.
    #[must_use]
    pub fn none() -> Self {
        Self {
            inner: tokio::sync::Mutex::new(State::default()),
            path: None,
            named: false,
        }
    }

    /// A daemon that keeps its list in `path`, reading what is already there.
    #[must_use]
    pub fn at(location: Location) -> Self {
        let state = load_from(&location.path);
        Self {
            inner: tokio::sync::Mutex::new(state),
            path: Some(location.path),
            named: location.named,
        }
    }

    /// Is this link written down?
    ///
    /// A mock panel is a test double: it belongs in a list that was NAMED,
    /// never in the user's default one.
    fn is_written_down(&self, args: &Value) -> bool {
        let is_mock = args.get("mock").and_then(Value::as_bool).unwrap_or(false);
        !is_mock || self.named
    }

    /// Write the list down, if this daemon keeps one.
    fn persist(&self, state: &State) {
        let Some(path) = self.path.as_ref() else {
            return;
        };
        if let Err(e) = save_to(path, state) {
            eprintln!("divoomd: cannot save the linked panels: {e}");
        }
    }

    /// Remember a link the daemon just took.
    pub async fn remember_link(&self, id: &str, args: Value) {
        if !self.is_written_down(&args) {
            return;
        }
        let mut state = self.inner.lock().await;
        if let Some(existing) = state
            .links
            .iter_mut()
            .find(|l| l.id.eq_ignore_ascii_case(id))
        {
            existing.args = args;
        } else {
            state.links.push(WantedLink {
                id: id.to_string(),
                args,
            });
        }
        let snapshot = state.clone();
        drop(state);
        self.persist(&snapshot);
    }

    /// Forget one link: the user dropped that panel.
    pub async fn forget_link(&self, id: &str) {
        let mut state = self.inner.lock().await;
        let before = state.links.len();
        state.links.retain(|l| !l.id.eq_ignore_ascii_case(id));
        if state.links.len() == before {
            return;
        }
        let snapshot = state.clone();
        drop(state);
        self.persist(&snapshot);
    }

    /// Forget every link: the user dropped them all.
    pub async fn forget_all_links(&self) {
        let mut state = self.inner.lock().await;
        if state.links.is_empty() {
            return;
        }
        state.links.clear();
        let snapshot = state.clone();
        drop(state);
        self.persist(&snapshot);
    }

    /// Remember the wall's slots.
    pub async fn remember_wall(&self, slots: Map<String, Value>, cell_size: i64) {
        let mut state = self.inner.lock().await;
        state.wall = Some(WantedWall { slots, cell_size });
        let snapshot = state.clone();
        drop(state);
        self.persist(&snapshot);
    }

    /// Forget the wall: it was torn down.
    pub async fn forget_wall(&self) {
        let mut state = self.inner.lock().await;
        if state.wall.is_none() {
            return;
        }
        state.wall = None;
        let snapshot = state.clone();
        drop(state);
        self.persist(&snapshot);
    }

    /// The saved list, as it is right now.
    pub async fn snapshot(&self) -> State {
        self.inner.lock().await.clone()
    }
}

impl Daemon {
    /// Keep the linked panels in `location`, so they come back after a
    /// restart (P2.7's remainder).
    ///
    /// Only the PROCESS asks for this. A `Daemon` built by a test keeps no
    /// list, so a test that connects a panel cannot write the developer's
    /// real one — and a test that disconnects everything cannot erase it.
    pub fn persist_links(&mut self, location: Location) {
        self.links = Wanted::at(location);
    }
}

/// Bring back what this daemon held before it restarted.
///
/// The order is the wall LAST: a wall reuses the transports of the panels it
/// shares with the fleet, so the panels have to be linked first.
pub async fn restore(daemon: &Daemon) {
    let saved = daemon.links.snapshot().await;
    if saved.links.is_empty() && saved.wall.is_none() {
        return;
    }
    tokio::time::sleep(RESTORE_DELAY).await;
    for link in &saved.links {
        if daemon.fleet.connected(&link.id).await.is_some() {
            continue; // a client got there first
        }
        let reply = connect_with_retry(daemon, &link.id, &link.args).await;
        let ok = reply
            .get("success")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        eprintln!(
            "divoomd: restoring {}: {}",
            link.id,
            if ok { "linked" } else { "failed" }
        );
    }
    if let Some(wall) = saved.wall {
        let args = json!({"slots": wall.slots, "cell_size": wall.cell_size});
        let req = make_request("wall_configure", Some(args), None);
        let reply = crate::wall::cmd_wall_configure(daemon, &req).await;
        let ok = reply
            .get("success")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        eprintln!(
            "divoomd: restoring the wall: {}",
            if ok { "configured" } else { "failed" }
        );
    }
}

/// Connect one panel, retrying while the radio is busy.
///
/// `busy` is the daemon's own answer to a second concurrent connect, and the
/// one this restore is most likely to meet: the client that started the
/// daemon is connecting its own panel at the same moment.
async fn connect_with_retry(daemon: &Daemon, id: &str, args: &Value) -> Value {
    let mut reply = Value::Null;
    for attempt in 0..=BUSY_RETRIES {
        // A client may have linked it while we waited: that is the same
        // outcome, and a second connect on a linked panel is not free.
        if daemon.fleet.connected(id).await.is_some() {
            return json!({"success": true});
        }
        let req = make_request("connect", Some(args.clone()), None);
        reply = crate::daemon_connect::cmd_connect(daemon, &req).await;
        let busy = reply.get("code").and_then(Value::as_str) == Some(ErrorCode::Busy.as_str());
        if !busy {
            return reply;
        }
        if attempt == BUSY_RETRIES {
            break;
        }
        tokio::time::sleep(BUSY_RETRY_DELAY).await;
    }
    reply
}
