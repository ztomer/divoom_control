//! The ONE place the daemon reads HOME (P5.15).
//!
//! Every state file the daemon keeps (`~/.config/divoom-control/...`), the
//! estate's secrets file and the notification database derive from HOME, and
//! each used to read it on its own. A test run therefore saw the developer's
//! home: the reply-code sweep drove `get_topology`, whose migration REWRITES
//! the owner's `topology.json`. Redirecting each file is a rule every new
//! state file would have to remember, so the one root is replaced instead.
//!
//! Inside a cargo test harness -- a unit- or integration-test binary, which
//! cargo always writes as `<profile>/deps/<crate>-<16 hex>` -- a HOME that is
//! not under the temp directory is the developer's, and is replaced by a
//! throwaway home for the process (HOME itself is moved there, so every
//! child the test spawns inherits it). A HOME a test points at a temp
//! directory of its own is honoured. A shipped or dev binary never sits in a
//! `deps` directory under that name, so this never fires outside a test.
//! `home_isolation_tests.rs` holds this.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

/// The home directory every daemon path derives from.
#[must_use]
pub fn home() -> Option<PathBuf> {
    let home = PathBuf::from(std::env::var_os("HOME")?);
    if !under_test_harness() || home.starts_with(std::env::temp_dir()) {
        return Some(home);
    }
    let fake = throwaway_home().clone();
    std::env::set_var("HOME", &fake);
    Some(fake)
}

/// Whether this process is a cargo test binary.
fn under_test_harness() -> bool {
    static IS: OnceLock<bool> = OnceLock::new();
    *IS.get_or_init(|| std::env::current_exe().is_ok_and(|exe| is_cargo_test_binary(&exe)))
}

/// `<anything>/deps/<name>-<16 lowercase hex>`, cargo's test-binary layout.
#[must_use]
pub fn is_cargo_test_binary(exe: &Path) -> bool {
    let in_deps = exe
        .parent()
        .and_then(Path::file_name)
        .is_some_and(|d| d == "deps");
    let hashed = exe
        .file_name()
        .and_then(|n| n.to_str())
        .and_then(|n| n.rsplit_once('-'))
        .is_some_and(|(stem, hash)| {
            !stem.is_empty()
                && hash.len() == 16
                && hash
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        });
    in_deps && hashed
}

fn throwaway_home() -> &'static PathBuf {
    static HOME: OnceLock<PathBuf> = OnceLock::new();
    HOME.get_or_init(|| {
        let dir = std::env::temp_dir().join(format!("divoomd-test-home-{}", std::process::id()));
        // A stale one from a recycled pid holds another run's state.
        std::fs::remove_dir_all(&dir).ok();
        std::fs::create_dir_all(&dir).ok();
        dir
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cargo_test_binaries_are_recognised_and_shipped_ones_are_not() {
        let yes = Path::new("/x/debug/deps/divoomd-0123456789abcdef");
        assert!(is_cargo_test_binary(yes));
        assert!(is_cargo_test_binary(Path::new(
            "/x/debug/deps/mcp_stdio-fedcba9876543210"
        )));
        for no in [
            "/x/debug/divoomd",
            "/Applications/Divoom Control.app/Contents/MacOS/divoomd",
            "/x/debug/deps/divoomd",
            "/x/debug/deps/divoomd-0123456789ABCDEF",
            "/x/debug/deps/divoomd-0123",
            "/x/debug/bin/divoomd-0123456789abcdef",
        ] {
            assert!(!is_cargo_test_binary(Path::new(no)), "{no}");
        }
    }

    /// The integration tests that spawn the daemon binary hand it the
    /// isolated home: the child is not a test binary, so it would otherwise
    /// inherit the developer's HOME if no `home()` call had moved it yet.
    #[test]
    fn every_spawned_daemon_is_handed_the_isolated_home() {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests");
        let mut bare = Vec::new();
        let mut spawns = 0;
        for entry in std::fs::read_dir(&dir).expect("divoomd/tests").flatten() {
            let path = entry.path();
            if path.extension().is_none_or(|e| e != "rs") {
                continue;
            }
            let src = std::fs::read_to_string(&path).expect("read a test file");
            for (at, _) in src.match_indices("Command::new(env!(\"CARGO_BIN_EXE_") {
                spawns += 1;
                let chain = &src[at..];
                let chain = &chain[..chain.find(".spawn()").unwrap_or(chain.len())];
                // Whitespace-blind: rustfmt breaks a long `.env(` across lines.
                let flat: String = chain.split_whitespace().collect();
                if !flat.contains(".env(\"HOME\",") {
                    bare.push(path.display().to_string());
                }
            }
        }
        assert!(spawns > 0, "the scan found no daemon spawn to check");
        assert!(bare.is_empty(), "a spawned daemon inherits HOME: {bare:?}");
    }

    #[test]
    fn this_process_is_a_test_harness() {
        assert!(under_test_harness());
    }
}
