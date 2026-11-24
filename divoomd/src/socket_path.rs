//! A socket path that fits in `sockaddr_un`, wherever the temp dir is.
//!
//! `sun_path` holds 104 bytes on macOS (108 on Linux), and the temp dir is
//! whatever the caller's environment says: a push gate gives each step its own
//! `TMPDIR` under `/var/folders/.../T/goh.noindex/step.NN/` (69 bytes before a
//! name), so a test socket named under it binds on a laptop and is refused in
//! the gate (`PathTooLong { len: 106, max: 103 }`, DV.SOCKETFLAKE). Every test
//! that makes a socket under a temp dir asks this module for the path.

use std::hash::{DefaultHasher, Hash, Hasher};
use std::path::{Path, PathBuf};

use crate::socket_bind::MAX_SOCKET_PATH;

/// The short base used when `base` is too deep: always present, and short.
const SHORT_BASE: &str = "/tmp";

/// `base/name` when it fits in `sun_path`, else a shorter path.
///
/// The fallback is `/tmp/name`, then a hashed name under `/tmp` that still
/// names `base` and `name` uniquely.
#[must_use]
pub fn fitting_socket_path(base: &Path, name: &str) -> PathBuf {
    let wanted = base.join(name);
    if fits(&wanted) {
        return wanted;
    }
    let short = Path::new(SHORT_BASE).join(name);
    if fits(&short) {
        return short;
    }
    // The hash covers the whole wanted path, so two long names (or one name
    // under two bases) never meet on one file.
    Path::new(SHORT_BASE).join(format!("divoomd_{:016x}.sock", hash_of(&wanted)))
}

fn fits(p: &Path) -> bool {
    p.as_os_str().len() <= MAX_SOCKET_PATH
}

/// Room a socket inside a [`fitting_socket_dir`] may use: `/` and 15 bytes.
pub const SOCKET_NAME_ROOM: usize = 16;

/// A directory `name` for sockets named in at most [`SOCKET_NAME_ROOM`] bytes.
///
/// `base/name` when such a socket fits, else `/tmp/name`, else a hashed name
/// under `/tmp`. Never `/tmp` itself, so a caller may remove what it gets.
#[must_use]
pub fn fitting_socket_dir(base: &Path, name: &str) -> PathBuf {
    let wanted = base.join(name);
    if wanted.as_os_str().len() + SOCKET_NAME_ROOM <= MAX_SOCKET_PATH {
        return wanted;
    }
    let short = Path::new(SHORT_BASE).join(name);
    if short.as_os_str().len() + SOCKET_NAME_ROOM <= MAX_SOCKET_PATH {
        return short;
    }
    Path::new(SHORT_BASE).join(format!("divoomd_{:016x}", hash_of(&wanted)))
}

/// [`fitting_socket_dir`] under this process's temp dir.
#[must_use]
pub fn scratch_socket_dir(name: &str) -> PathBuf {
    fitting_socket_dir(&std::env::temp_dir(), name)
}

fn hash_of(p: &Path) -> u64 {
    let mut h = DefaultHasher::new();
    p.hash(&mut h);
    h.finish()
}

/// [`fitting_socket_path`] under this process's temp dir.
#[must_use]
pub fn scratch_socket_path(name: &str) -> PathBuf {
    fitting_socket_path(&std::env::temp_dir(), name)
}

#[cfg(test)]
#[path = "socket_path_tests.rs"]
mod tests;
