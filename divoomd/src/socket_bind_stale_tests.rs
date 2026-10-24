//! Stale-socket tests, split from `socket_bind_tests.rs` at the file-length cap.

use super::tests::{cleanup, tmp_path, wait_until_refused};
use super::*;

/// Leave a socket file at `p` that nothing listens on, and return only once the
/// kernel agrees: `connect` is refused. Dropping the listener is not enough. A
/// `fork` in another test thread copies every open descriptor until its `exec`,
/// so the "dead" listener can stay alive for the length of that gap and accept
/// the probe's connection into a backlog nobody reads (`UnresponsiveListener`,
/// 1 run in 40 under parallel tests). A test that says "stale" must first make
/// the file stale. `lingering_copy` holds a second reference for that long,
/// which is the forked child made deterministic.
fn leave_stale_socket(p: &str, lingering_copy: Option<std::time::Duration>) {
    let dead = UnixListener::bind(p).expect("bind");
    let copy = dead.try_clone().expect("clone the listener");
    drop(dead);
    std::thread::spawn(move || {
        std::thread::sleep(lingering_copy.unwrap_or_default());
        drop(copy);
    });
    wait_until_refused(p);
    assert!(std::path::Path::new(p).exists(), "stale file remains");
}

#[test]
fn clears_a_stale_socket() {
    // THE common case: the daemon died without unlinking. Dropping a
    // UnixListener does not remove the file, so this is exactly what is left
    // behind by a kill -9.
    let p = tmp_path("stale");
    cleanup(&p);
    leave_stale_socket(&p, None);

    let got = acquire(&p).expect("a stale socket must be cleared, not fatal");
    drop(got);
    cleanup(&p);
}

#[test]
fn clears_a_stale_socket_whose_last_descriptor_is_still_closing() {
    // The window the flake lived in, made deterministic: a copy of the listener
    // outlives the owner by 150 ms, as a forked child's does until it execs.
    let p = tmp_path("stale_closing");
    cleanup(&p);
    leave_stale_socket(&p, Some(std::time::Duration::from_millis(150)));

    let got = acquire(&p).expect("a stale socket must be cleared, not fatal");
    drop(got);
    cleanup(&p);
}
