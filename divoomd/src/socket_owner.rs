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
//!
//! # Required invariant: the socket stays open until after the ownership check
//!
//! `(dev, ino)` identifies a file only while that inode CANNOT BE REUSED. An
//! inode is freed once its link count and open count both reach zero, and Linux
//! hands freed inode numbers straight back out; macOS/APFS rarely does, which is
//! exactly why this was invisible here and caught by Linux CI.
//!
//! A bound `AF_UNIX` listener is what keeps the inode alive. Note it does NOT do
//! so through the descriptor's own inode: `fstat` on a bound socket fd reports a
//! *sockfs* inode, unrelated to the filesystem entry (probed 2026-08-30 on this
//! machine: `fstat` dev/ino and `stat(path)` dev/ino differ entirely). What pins
//! the filesystem inode is the path reference the kernel takes at `bind` and
//! holds until the socket is released. The practical rule is the same either
//! way — do not close the listener before the check — but it is why ownership
//! must be captured from the PATH and cannot be read back off the descriptor.
//!
//! `main` originally closed it too early: `serve` consumed the listener and
//! `tokio::select!` dropped that future on shutdown, closing the socket well
//! before `release_socket` ran. In that window a daemon B could unlink, rebind,
//! and be handed our exact `(dev, ino)` — and A would then delete B's live
//! socket, recreating the outage described above.
//!
//! # Why [`HeldSocket`] exists
//!
//! That fix was first made by having `serve` BORROW the listener, which is a
//! rule three comments had to keep restating and which nothing enforced —
//! and the borrow was not even the real constraint, it was a proxy for one.
//! It also forced `Box::leak(Box::new(listener))` at every `tokio::spawn` call
//! site in the tests, which is the shape a lifetime takes when it is being used
//! to express something other than a lifetime.
//!
//! [`HeldSocket`] makes it structural instead. One value owns the listener, the
//! startup lock and the recorded identity, and its `Drop` performs the
//! ownership-checked unlink. Rust runs a `Drop` body BEFORE dropping the
//! struct's fields, so the listener is necessarily still open when the check
//! runs. The invariant is now a consequence of drop order rather than of anyone
//! remembering to read a comment.

use std::sync::Arc;

use crate::socket_bind::StartupLock;

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

/// A socket this process bound and is responsible for releasing.
///
/// Bundles the three things whose lifetimes were previously coupled only by a
/// comment: the listener (whose open socket pins the inode), the startup lock
/// (whose release re-opens the two-daemon race), and the identity recorded at
/// bind time. Dropping this — however the daemon exits — runs the
/// ownership-checked unlink first and releases the lock afterwards.
///
/// Generic over the listener so the type is not welded to one runtime's socket:
/// `main` holds a `tokio::net::UnixListener`, tests hold whatever is convenient.
/// Nothing here inspects the listener; it only has to stay alive.
#[derive(Debug)]
pub struct HeldSocket<L> {
    path: String,
    /// An `Arc` so `serve` can hold a clone: the accept loop needs a `'static`
    /// listener, and handing it a borrow was the wart this type replaces.
    listener: Arc<L>,
    /// Dropped AFTER the unlink, since releasing it re-admits a competing
    /// daemon. Only `Option` so `release` can take it before `Drop` runs.
    lock: Option<StartupLock>,
    owned: Option<SocketOwnership>,
    released: bool,
}

impl<L> HeldSocket<L> {
    /// Take responsibility for a bound socket.
    ///
    /// `owned` comes from [`crate::socket_bind::acquire`], which captures it
    /// under the startup lock immediately after `bind`. It is deliberately NOT
    /// re-derived here: a second `stat` of the path would be another
    /// check-then-act, and this type exists to delete those.
    pub fn new(
        path: String,
        listener: L,
        lock: StartupLock,
        owned: Option<SocketOwnership>,
    ) -> Self {
        Self {
            path,
            listener: Arc::new(listener),
            lock: Some(lock),
            owned,
            released: false,
        }
    }

    /// The socket path this owns.
    pub fn path(&self) -> &str {
        &self.path
    }

    /// A handle to the listener for the accept loop.
    ///
    /// The clone keeps the socket open independently of this value, which is
    /// harmless: what must not happen is the socket closing EARLY, and an extra
    /// reference can only delay that.
    pub fn listener(&self) -> Arc<L> {
        self.listener.clone()
    }

    /// Release the socket now: unlink it if it is still ours, then drop the lock.
    ///
    /// Returns whether the file was removed. Calling this is optional — `Drop`
    /// does the same thing — but an explicit call at the end of `main` says the
    /// shutdown is deliberate rather than incidental.
    pub fn release(mut self) -> bool {
        self.release_now()
    }

    /// True once the unlink has been attempted; further attempts are no-ops.
    fn release_now(&mut self) -> bool {
        if self.released {
            return false;
        }
        self.released = true;
        let removed = release_socket(&self.path, self.owned);
        // Explicit, and ordered: the lock must outlive the unlink, or a daemon
        // waiting on it could bind between the two and have its socket deleted.
        self.lock = None;
        removed
    }
}

impl<L> Drop for HeldSocket<L> {
    fn drop(&mut self) {
        // Runs BEFORE `self.listener` is dropped, so the socket is still open
        // and `(dev, ino)` still identifies the file we bound. That ordering is
        // the whole point of this type.
        self.release_now();
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

    /// Create the file and KEEP IT OPEN, the way the daemon keeps its bound
    /// listener open.
    ///
    /// This is not test decoration: an open fd is what pins the inode. Both
    /// replacement tests below originally unlinked and recreated with nothing
    /// held open, so on ext4 the freed inode was handed straight back and the
    /// "replacement" was indistinguishable from the original. They passed on
    /// APFS and failed on Linux CI -- and they were RIGHT to fail: at the time,
    /// `main` really did close the listener before calling `release_socket`.
    fn touch_held(path: &str) -> std::fs::File {
        let mut f = std::fs::File::create(path).expect("create");
        let _ = f.write_all(b"x");
        f
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
        let held = touch_held(&p); // as the daemon holds its listener
        let owned = SocketOwnership::of(&p).expect("stat");

        std::fs::remove_file(&p).expect("unlink");
        touch(&p); // a different file, same path

        assert!(
            !owned.still_owns(&p),
            "a replaced path must not be treated as ours"
        );
        drop(held);
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
        let held = touch_held(&p); // A holds its listener open, as main does
        let owned = SocketOwnership::of(&p);

        std::fs::remove_file(&p).expect("unlink");
        touch(&p); // B's socket now lives here

        assert!(!release_socket(&p, owned), "must not claim someone else's");
        assert!(
            std::path::Path::new(&p).exists(),
            "B's socket must survive A's shutdown — this is the 34-hour-orphan bug"
        );
        drop(held);
        let _ = std::fs::remove_file(&p);
    }

    /// A stand-in listener that records, at the moment it is closed, whether the
    /// socket file still existed.
    ///
    /// This is the instrument for the ordering invariant. `HeldSocket` must
    /// unlink while the listener is still open; if the fields were dropped
    /// first, this would observe the file still present.
    struct ClosureProbe {
        path: String,
        existed_at_close: Arc<std::sync::Mutex<Option<bool>>>,
    }

    impl Drop for ClosureProbe {
        fn drop(&mut self) {
            let existed = std::path::Path::new(&self.path).exists();
            *self.existed_at_close.lock().expect("probe lock") = Some(existed);
        }
    }

    /// A real `flock`ed file, so the `HeldSocket` under test holds the same kind
    /// of lock the daemon does.
    fn test_lock(tag: &str) -> StartupLock {
        let p = tmp_path(&format!("lock_{tag}"));
        StartupLock::hold(std::fs::File::create(p).expect("lock file"))
    }

    #[test]
    fn held_socket_unlinks_its_own_socket_on_drop() {
        let p = tmp_path("held_drop");
        let _ = std::fs::remove_file(&p);
        let listener = touch_held(&p);
        let owned = SocketOwnership::of(&p);

        drop(HeldSocket::new(
            p.clone(),
            listener,
            test_lock("held_drop"),
            owned,
        ));

        assert!(
            !std::path::Path::new(&p).exists(),
            "an exiting daemon must clean up its own socket even when nothing calls release()"
        );
    }

    #[test]
    fn held_socket_leaves_a_replaced_socket_alone() {
        // R67/C5 through the type that now owns the rule: A must not delete the
        // socket B is listening on.
        let p = tmp_path("held_replaced");
        let _ = std::fs::remove_file(&p);
        let listener = touch_held(&p);
        let owned = SocketOwnership::of(&p);

        std::fs::remove_file(&p).expect("unlink");
        touch(&p); // B's socket now lives here

        let held = HeldSocket::new(p.clone(), listener, test_lock("held_replaced"), owned);
        assert!(!held.release(), "must not claim someone else's socket");
        assert!(
            std::path::Path::new(&p).exists(),
            "B's socket must survive A's shutdown"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn held_socket_unlinks_while_the_listener_is_still_open() {
        // THE structural invariant. `(dev, ino)` only identifies our socket
        // while the socket is open, so the unlink must happen before the
        // listener is dropped -- not after, and not "usually before".
        let p = tmp_path("held_ordering");
        let _ = std::fs::remove_file(&p);
        touch(&p);
        let owned = SocketOwnership::of(&p);

        let existed_at_close = Arc::new(std::sync::Mutex::new(None));
        let probe = ClosureProbe {
            path: p.clone(),
            existed_at_close: existed_at_close.clone(),
        };

        drop(HeldSocket::new(
            p.clone(),
            probe,
            test_lock("held_ordering"),
            owned,
        ));

        assert_eq!(
            *existed_at_close.lock().expect("probe lock"),
            Some(false),
            "the socket file must already be unlinked by the time the listener closes; \
             if it still exists here, the fields were dropped before the release ran"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn held_socket_releases_once_even_though_drop_also_runs() {
        // release() consumes self, so Drop runs immediately afterwards. A second
        // unlink there would delete whatever took the path in between -- the
        // same class of bug, one layer down.
        let p = tmp_path("held_once");
        let _ = std::fs::remove_file(&p);
        let listener = touch_held(&p);
        let owned = SocketOwnership::of(&p);

        let held = HeldSocket::new(p.clone(), listener, test_lock("held_once"), owned);
        assert_eq!(held.path(), p, "path() reports the socket it holds");
        assert!(held.release(), "our own socket is ours to remove");

        // Someone else's file arrives at the freed path before Drop completes.
        touch(&p);
        assert!(
            std::path::Path::new(&p).exists(),
            "the second release must be a no-op, not a delete"
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
