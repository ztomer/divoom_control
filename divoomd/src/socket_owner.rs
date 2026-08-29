//! Socket-file ownership: only unlink the socket we actually bound.
//!
//! # The bug this exists to prevent (R67, class C5)
//!
//! Shutdown used to call `remove_file(&socket_path)` unconditionally. Nothing
//! checked that this process still owned the path, and that turns two daemons
//! into a self-sustaining outage:
//!
//! 1. Daemon A is listening on `/tmp/divoom.sock`.
//! 2. Daemon B starts. The bind guard only refuses when something is *listening*
//!    at that instant; otherwise it unlinks the path and binds its own. So B can
//!    end up owning the path while A is still running.
//! 3. Whichever one exits first unlinks the path — including when it is no
//!    longer that daemon's file.
//! 4. The survivor keeps running with an unlinked listening socket: reachable by
//!    nobody, invisible to every UI, and still holding the single-owner
//!    CoreBluetooth central. The GUI sees no daemon and spawns another. Repeat.
//!
//! This was not theoretical. On the dev machine an orphan from step 4 had been
//! up for 34 hours while the GUI talked to a different daemon, and killing it
//! deleted the live daemon's socket — reproducing the whole cycle in one step.
//!
//! A path is not an identity; `(dev, inode)` is. Recording that pair at bind
//! time lets shutdown distinguish "our socket" from "a socket that replaced
//! ours", and only remove the former.

/// Identity of the socket file a process bound.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SocketOwnership {
    dev: u64,
    ino: u64,
}

impl SocketOwnership {
    /// Capture the identity of the file currently at `path`.
    ///
    /// `None` when the path does not exist or cannot be stat'ed — in which case
    /// we never claim ownership, so we never unlink.
    pub fn of(path: &str) -> Option<Self> {
        use std::os::unix::fs::MetadataExt;
        let md = std::fs::metadata(path).ok()?;
        Some(Self {
            dev: md.dev(),
            ino: md.ino(),
        })
    }

    /// True only when `path` still names the exact file this identity describes.
    ///
    /// A replaced path (different inode) or a vanished one is NOT ours.
    pub fn still_owns(&self, path: &str) -> bool {
        Self::of(path).is_some_and(|now| now == *self)
    }
}

/// Remove the socket file, but only when we still own it.
///
/// Returns true when the file was removed. The `Some(_)` arm prints rather than
/// staying silent: a daemon discovering that its socket was replaced is the
/// visible symptom of a duplicate-instance problem, and silence is how the
/// original bug survived.
pub fn release_socket(socket_path: &str, owned: Option<SocketOwnership>) -> bool {
    match owned {
        Some(o) if o.still_owns(socket_path) => {
            let _ = std::fs::remove_file(socket_path);
            true
        }
        Some(_) => {
            eprintln!("divoomd: {socket_path} was replaced by another instance — leaving it alone");
            false
        }
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// A unique temp path per test — `Date`/random are unavailable here, so the
    /// test name provides the uniqueness.
    fn tmp_path(tag: &str) -> String {
        let dir = std::env::temp_dir();
        dir.join(format!("divoomd_sockowner_{tag}"))
            .to_string_lossy()
            .into_owned()
    }

    fn touch(path: &str) {
        let mut f = std::fs::File::create(path).expect("create");
        let _ = f.write_all(b"x");
    }

    #[test]
    fn owns_the_file_it_captured() {
        let p = tmp_path("owns");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        let owned = SocketOwnership::of(&p).expect("stat");
        assert!(owned.still_owns(&p));
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn does_not_own_a_replaced_file() {
        // THE bug: another daemon unlinked our socket and bound its own at the
        // same path. Same path, different inode — not ours.
        let p = tmp_path("replaced");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        let owned = SocketOwnership::of(&p).expect("stat");

        std::fs::remove_file(&p).expect("unlink");
        touch(&p); // a different file, same path

        assert!(
            !owned.still_owns(&p),
            "a replaced path must not be treated as ours"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn does_not_own_a_vanished_file() {
        let p = tmp_path("vanished");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        let owned = SocketOwnership::of(&p).expect("stat");
        std::fs::remove_file(&p).expect("unlink");
        assert!(!owned.still_owns(&p));
    }

    #[test]
    fn of_returns_none_for_a_missing_path() {
        let p = tmp_path("missing");
        let _ = std::fs::remove_file(&p);
        assert!(SocketOwnership::of(&p).is_none());
    }

    #[test]
    fn release_removes_our_own_socket() {
        let p = tmp_path("release_own");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        let owned = SocketOwnership::of(&p);
        assert!(
            release_socket(&p, owned),
            "our own socket is ours to remove"
        );
        assert!(!std::path::Path::new(&p).exists());
    }

    #[test]
    fn release_leaves_a_replaced_socket_alone() {
        // The regression that matters: killing daemon A must not delete the
        // socket daemon B is currently listening on.
        let p = tmp_path("release_replaced");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        let owned = SocketOwnership::of(&p);

        std::fs::remove_file(&p).expect("unlink");
        touch(&p); // B's socket now lives here

        assert!(!release_socket(&p, owned), "must not claim someone else's");
        assert!(
            std::path::Path::new(&p).exists(),
            "B's socket must survive A's shutdown — this is the 34-hour-orphan bug"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn release_is_a_no_op_without_recorded_ownership() {
        let p = tmp_path("release_none");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        assert!(!release_socket(&p, None));
        assert!(
            std::path::Path::new(&p).exists(),
            "never unlink a path we never claimed"
        );
        let _ = std::fs::remove_file(&p);
    }
}
