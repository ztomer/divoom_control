//! The socket's access rule is set by the daemon, not inherited from the umask.
//!
//! The unix socket path carries no token check (`require_auth=false`), so the
//! file mode IS the access control: whoever can `connect()` can drive the
//! panels. Before P2.1 the daemon never set a mode and was owner-only only
//! because the umask happened to be 022; a daemon started under umask 000
//! accepted every local user.
//!
//! Its own test binary on purpose: the umask is process-wide, and widening it
//! inside the main test binary would leak into every test that creates a file
//! while this one runs.

use std::os::unix::fs::PermissionsExt;

/// Restores the previous umask however the test exits.
struct Umask(libc::mode_t);

impl Umask {
    fn set(mask: libc::mode_t) -> Self {
        // SAFETY: umask has no preconditions; it swaps one process-wide value.
        Self(unsafe { libc::umask(mask) })
    }
}

impl Drop for Umask {
    fn drop(&mut self) {
        // SAFETY: as above.
        unsafe { libc::umask(self.0) };
    }
}

#[test]
fn the_socket_is_owner_only_under_a_wide_open_umask() {
    let path = std::env::temp_dir()
        .join(format!("divoomd_mode_{}.sock", std::process::id()))
        .to_string_lossy()
        .into_owned();
    let clean = |p: &str| {
        let _ = std::fs::remove_file(p);
        let _ = std::fs::remove_file(divoomd::socket_bind::lock_path(p));
        let _ = std::fs::remove_file(divoomd::socket_bind::failure_path(p));
    };
    clean(&path);

    let acquired = {
        let _wide = Umask::set(0);
        divoomd::socket_bind::acquire(&path).expect("free path must bind")
    };
    let mode = std::fs::metadata(&path)
        .expect("socket exists")
        .permissions()
        .mode()
        & 0o777;
    drop(acquired);
    clean(&path);

    assert_eq!(
        mode, 0o600,
        "socket mode {mode:o} under umask 000: anyone who can connect can drive the panels"
    );
}
