//! No `cargo test` run reaches the developer's HOME (P5.15).
//!
//! The Python suite has run under a throwaway HOME since 2026-11-01
//! (`tests/conftest.py`), after a test daemon rewrote the owner's
//! `links.json`. `cargo test` never went through that: the reply-code sweep
//! drives `get_topology` on a `Daemon::new()`, and `load_topology` REWRITES
//! the owner's `topology.json` when it places a panel no device reported.
//!
//! This test plants an owner-like home -- outside the temp directory, where
//! a real one lives, with a `topology.json` that the migration rewrites --
//! points HOME at it, drives every command the sweep drives, and fails on
//! any change under it. It also watches the HOME the test process started
//! with, read-only, so a regression that reaches the real owner's directory
//! is reported against it by name.

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::path::{Path, PathBuf};
    use std::time::SystemTime;

    use serde_json::json;

    use crate::command_args::COMMAND_ARGS;
    use crate::protocol::make_request;
    use crate::reply_code_sweep_tests::tests::{daemon, variants, with_panel, NOT_DRIVEN};
    use crate::socket_server::Handler;

    type Snapshot = BTreeMap<PathBuf, (Option<SystemTime>, Vec<u8>)>;

    /// Every entry under `dir` with its mtime and (for files) its bytes.
    fn snapshot(dir: &Path) -> Snapshot {
        let mut out = Snapshot::new();
        let mut stack = vec![dir.to_path_buf()];
        while let Some(d) = stack.pop() {
            let Ok(meta) = std::fs::metadata(&d) else {
                continue;
            };
            let bytes = if meta.is_file() {
                std::fs::read(&d).unwrap_or_default()
            } else {
                Vec::new()
            };
            out.insert(d.clone(), (meta.modified().ok(), bytes));
            if meta.is_dir() {
                if let Ok(rd) = std::fs::read_dir(&d) {
                    stack.extend(rd.flatten().map(|e| e.path()));
                }
            }
        }
        out
    }

    /// A home where a real one lives: NOT under the temp directory (the test
    /// binary's own build directory), holding a layout the topology
    /// migration rewrites on read.
    fn owner_like_home() -> PathBuf {
        let exe = std::env::current_exe().expect("the test binary has a path");
        let home = exe
            .parent()
            .expect("the test binary sits in a directory")
            .join(format!("owner-like-home-{}", std::process::id()));
        let conf = home.join(".config").join("divoom-control");
        std::fs::create_dir_all(&conf).expect("plant the owner's config");
        let layout = json!({
            "devices": {"AA:BB:CC:DD:EE:01": {"x": 0, "y": 0, "room": "Desk"}},
            "wall_linked": true,
            "rooms": ["Desk"]
        });
        std::fs::write(conf.join("topology.json"), layout.to_string()).expect("plant topology");
        home
    }

    #[tokio::test]
    async fn a_sweep_of_every_command_leaves_the_owners_home_alone() {
        let _lock = crate::cloud::TEST_MUTEX
            .get_or_init(|| tokio::sync::Mutex::new(()))
            .lock()
            .await;
        let started = std::env::var_os("HOME").map(PathBuf::from);
        let real_conf = started
            .as_ref()
            .map(|h| h.join(".config").join("divoom-control"));
        let real_before = real_conf.as_deref().map(snapshot);

        let owner = owner_like_home();
        let before = snapshot(&owner);
        std::env::set_var("HOME", &owner);

        let mut sent = 0usize;
        for (command, required) in COMMAND_ARGS {
            if NOT_DRIVEN.iter().any(|(c, _)| c == command) {
                continue;
            }
            for args in variants(command, required) {
                for d in [daemon(), with_panel(false).await, with_panel(true).await] {
                    d.handle(make_request(command, Some(args.clone()), None))
                        .await;
                    sent += 1;
                }
            }
        }

        match &started {
            Some(h) => std::env::set_var("HOME", h),
            None => std::env::remove_var("HOME"),
        }
        let after = snapshot(&owner);
        let real_after = real_conf.as_deref().map(snapshot);
        std::fs::remove_dir_all(&owner).ok();

        assert!(sent > 300, "the sweep sent only {sent} requests");
        let changed: Vec<String> = before
            .keys()
            .chain(after.keys())
            .filter(|p| before.get(*p) != after.get(*p))
            .map(|p| p.display().to_string())
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect();
        assert!(
            changed.is_empty(),
            "a cargo test wrote under the owner's HOME: {changed:?}"
        );
        assert_eq!(
            real_before, real_after,
            "a cargo test changed the real {real_conf:?}"
        );
    }
}
