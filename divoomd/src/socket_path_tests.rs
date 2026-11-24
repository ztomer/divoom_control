//! Tests for `socket_path`: a deep base still yields a path `acquire` binds.

use super::*;
use crate::socket_bind::acquire;

fn len(p: &Path) -> usize {
    p.as_os_str().len()
}

/// A base deeper than `sun_path` itself: no name fits under it.
fn deep_base() -> PathBuf {
    std::env::temp_dir().join("x".repeat(MAX_SOCKET_PATH))
}

#[test]
fn a_short_base_keeps_its_own_directory() {
    let p = fitting_socket_path(Path::new("/tmp"), "a.sock");
    assert_eq!(p, Path::new("/tmp/a.sock"));
}

#[test]
fn a_deep_base_still_binds() {
    let name = format!("divoomd_path_{}_deep.sock", std::process::id());
    let p = fitting_socket_path(&deep_base(), &name);
    assert!(
        len(&p) <= MAX_SOCKET_PATH,
        "{} bytes: {}",
        len(&p),
        p.display()
    );
    let s = p.to_string_lossy().into_owned();
    let _ = std::fs::remove_file(&s);
    let got = acquire(&s).expect("a fitting path binds");
    drop(got);
    let _ = std::fs::remove_file(&s);
}

#[test]
fn an_over_long_name_is_hashed_and_stays_unique() {
    let long = "n".repeat(MAX_SOCKET_PATH);
    let a = fitting_socket_path(&deep_base(), &format!("{long}a.sock"));
    let b = fitting_socket_path(&deep_base(), &format!("{long}b.sock"));
    assert!(len(&a) <= MAX_SOCKET_PATH, "{}", a.display());
    assert_ne!(a, b, "two names must not collide on one hashed path");
    assert_eq!(
        a,
        fitting_socket_path(&deep_base(), &format!("{long}a.sock")),
        "stable"
    );
}

#[test]
fn the_scratch_path_fits_whatever_tmpdir_is() {
    let p = scratch_socket_path("divoomd_scratch_probe.sock");
    assert!(len(&p) <= MAX_SOCKET_PATH, "{}", p.display());
}

#[test]
fn a_socket_dir_under_a_deep_base_leaves_room_for_its_socket() {
    let dir = fitting_socket_dir(&deep_base(), &format!("divoomd_dir_{}", std::process::id()));
    assert_ne!(dir, Path::new(SHORT_BASE), "never the shared /tmp itself");
    let sock = dir.join("fifteen_bytes.s");
    assert_eq!(
        sock.file_name().map(|n| n.len() + 1),
        Some(SOCKET_NAME_ROOM)
    );
    assert!(len(&sock) <= MAX_SOCKET_PATH, "{}", sock.display());
    let _ = std::fs::remove_dir_all(&dir);
    let got = acquire(&sock.to_string_lossy()).expect("a socket in a fitting dir binds");
    drop(got);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn an_over_long_dir_name_is_hashed_and_is_never_tmp() {
    let long = "d".repeat(MAX_SOCKET_PATH);
    let a = fitting_socket_dir(&deep_base(), &long);
    assert!(
        len(&a) + SOCKET_NAME_ROOM <= MAX_SOCKET_PATH,
        "{}",
        a.display()
    );
    assert_ne!(a, Path::new(SHORT_BASE));
    assert_eq!(
        fitting_socket_dir(Path::new("/tmp"), "x"),
        Path::new("/tmp/x")
    );
    assert!(len(&scratch_socket_dir("probe")) + SOCKET_NAME_ROOM <= MAX_SOCKET_PATH);
}
