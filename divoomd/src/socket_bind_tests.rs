//! Tests for socket acquisition.
//!
//! Every branch here corresponds to a way the old three-line `bind()` failed
//! opaquely, so each asserts on the DISTINCTION as well as the outcome: an
//! error the user cannot act on is the defect being fixed, not a detail.

use super::*;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// Unique per test — no clock or RNG here, so the test name is the uniqueness.
fn tmp_path(tag: &str) -> String {
    std::env::temp_dir()
        .join(format!("divoomd_bind_{tag}.sock"))
        .to_string_lossy()
        .into_owned()
}

/// Remove the socket and both sidecars.
fn cleanup(p: &str) {
    let _ = std::fs::remove_file(p);
    let _ = std::fs::remove_file(lock_path(p));
    let _ = std::fs::remove_file(failure_path(p));
    let _ = std::fs::remove_dir_all(p);
}

/// A listener that answers like divoomd (or not), on a background thread.
struct Fake {
    stop: Arc<AtomicBool>,
    handle: Option<std::thread::JoinHandle<()>>,
}

impl Fake {
    fn start(path: &str, greet: Option<&'static str>) -> Self {
        let listener = UnixListener::bind(path).expect("fake bind");
        listener.set_nonblocking(true).expect("nonblocking");
        let stop = Arc::new(AtomicBool::new(false));
        let s = stop.clone();
        let handle = std::thread::spawn(move || {
            while !s.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((mut conn, _)) => {
                        if let Some(g) = greet {
                            let _ = conn.write_all(g.as_bytes());
                            let _ = conn.flush();
                        }
                        // Hold the connection briefly so the prober can read.
                        std::thread::sleep(Duration::from_millis(50));
                    }
                    Err(_) => std::thread::sleep(Duration::from_millis(10)),
                }
            }
        });
        Fake {
            stop,
            handle: Some(handle),
        }
    }
}

impl Drop for Fake {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

#[test]
fn binds_a_free_path() {
    let p = tmp_path("free");
    cleanup(&p);
    let got = acquire(&p).expect("free path must bind");
    assert!(std::path::Path::new(&p).exists(), "socket must exist");
    drop(got);
    cleanup(&p);
}

#[test]
fn clears_a_stale_socket() {
    // THE common case: the daemon died without unlinking. Dropping a
    // UnixListener does not remove the file, so this is exactly what is left
    // behind by a kill -9.
    let p = tmp_path("stale");
    cleanup(&p);
    let dead = UnixListener::bind(&p).expect("bind");
    drop(dead);
    assert!(std::path::Path::new(&p).exists(), "stale file remains");

    let got = acquire(&p).expect("a stale socket must be cleared, not fatal");
    drop(got);
    cleanup(&p);
}

#[test]
fn refuses_a_live_divoomd_without_deleting_it() {
    let p = tmp_path("live");
    cleanup(&p);
    let _fake = Fake::start(&p, Some("{\"type\":\"status\",\"connected\":false}\n"));

    match acquire(&p) {
        Err(BindFailure::LiveInstance) => {}
        other => panic!("expected LiveInstance, got {other:?}"),
    }
    assert!(
        std::path::Path::new(&p).exists(),
        "a live daemon's socket must survive our refusal"
    );
    drop(_fake);
    cleanup(&p);
}

#[test]
fn refuses_a_foreign_listener_instead_of_stealing_it() {
    // Something is listening but is not divoomd. The old code treated any
    // successful connect as "a healthy divoomd" and exited claiming so.
    let p = tmp_path("foreign");
    cleanup(&p);
    let _fake = Fake::start(&p, None); // accepts, says nothing

    match acquire(&p) {
        Err(BindFailure::ForeignListener) => {}
        other => panic!("expected ForeignListener, got {other:?}"),
    }
    assert!(std::path::Path::new(&p).exists(), "must not be removed");
    drop(_fake);
    cleanup(&p);
}

#[test]
fn never_deletes_a_regular_file() {
    // A file here is someone's data. Guessing wrong is unrecoverable, so this
    // is reported and left alone.
    let p = tmp_path("regular");
    cleanup(&p);
    std::fs::write(&p, b"precious").expect("write");

    match acquire(&p) {
        Err(BindFailure::NotASocket { kind }) => assert_eq!(kind, "regular file"),
        other => panic!("expected NotASocket, got {other:?}"),
    }
    assert_eq!(
        std::fs::read(&p).expect("still there"),
        b"precious",
        "a regular file must never be auto-removed"
    );
    cleanup(&p);
}

#[test]
fn reports_a_directory_in_the_way() {
    let p = tmp_path("dir");
    cleanup(&p);
    std::fs::create_dir_all(&p).expect("mkdir");

    match acquire(&p) {
        Err(BindFailure::NotASocket { kind }) => assert_eq!(kind, "directory"),
        other => panic!("expected NotASocket(directory), got {other:?}"),
    }
    assert!(std::path::Path::new(&p).is_dir(), "must be left alone");
    cleanup(&p);
}

#[test]
fn rejects_an_over_long_path_with_the_limit() {
    // The kernel's own answer is EINVAL / "Invalid argument", which reads like
    // a bug in the daemon rather than a limit on the path.
    let p = format!("/tmp/{}.sock", "x".repeat(MAX_SOCKET_PATH + 10));
    match acquire(&p) {
        Err(BindFailure::PathTooLong { len, max }) => {
            assert_eq!(len, p.len());
            assert_eq!(max, MAX_SOCKET_PATH);
        }
        other => panic!("expected PathTooLong, got {other:?}"),
    }
}

#[test]
fn creates_a_missing_parent_directory() {
    let dir = std::env::temp_dir().join("divoomd_bind_parent_test");
    let _ = std::fs::remove_dir_all(&dir);
    let p = dir.join("d.sock").to_string_lossy().into_owned();

    let got = acquire(&p).expect("a missing parent directory must be created");
    assert!(dir.is_dir(), "parent must exist now");
    drop(got);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn second_startup_is_refused_while_the_lock_is_held() {
    // The race the old code lost: two daemons both saw an empty path, both
    // unlinked, both bound, and the loser was orphaned on an unlinked inode.
    // The lock makes inspect-and-bind atomic, so the second is TOLD.
    let p = tmp_path("lockrace");
    cleanup(&p);
    let first = acquire(&p).expect("first acquires");

    match acquire(&p) {
        // Either answer is correct and both are actionable: the lock may be
        // seen first, or the first daemon's live socket may be.
        Err(BindFailure::StartupInProgress) | Err(BindFailure::LiveInstance) => {}
        other => panic!("second startup must be refused, got {other:?}"),
    }
    drop(first);
    cleanup(&p);
}

#[test]
fn releasing_the_lock_lets_the_next_daemon_start() {
    // The mirror of the test above: the guard must not be a one-way door.
    let p = tmp_path("lockfree");
    cleanup(&p);
    let first = acquire(&p).expect("first");
    drop(first);
    let _ = std::fs::remove_file(&p); // as a clean shutdown would

    let second = acquire(&p).expect("a released lock must be re-acquirable");
    drop(second);
    cleanup(&p);
}

#[test]
fn every_failure_says_what_to_do() {
    // A reason with no remedy is how "it will not start" becomes unactionable.
    let p = "/tmp/x.sock";
    let cases = [
        BindFailure::LiveInstance,
        BindFailure::ForeignListener,
        BindFailure::NotASocket {
            kind: "regular file",
        },
        BindFailure::StartupInProgress,
        BindFailure::ParentMissing {
            parent: "/nope".into(),
            err: "e".into(),
        },
        BindFailure::PermissionDenied { err: "e".into() },
        BindFailure::PathTooLong { len: 200, max: 103 },
        BindFailure::Io { err: "e".into() },
    ];
    for c in cases {
        assert!(!c.reason(p).is_empty(), "reason must not be empty");
        assert!(c.remedy().len() > 20, "remedy must be actionable: {c:?}");
    }
}

#[test]
fn a_live_instance_is_not_a_configuration_error() {
    // Distinct exit codes let a supervisor tell "already running" from a real
    // problem without parsing English.
    assert_eq!(BindFailure::LiveInstance.exit_code(), 3);
    assert_eq!(BindFailure::StartupInProgress.exit_code(), 4);
    assert_eq!(BindFailure::PathTooLong { len: 1, max: 1 }.exit_code(), 1);
}

#[test]
fn failure_is_written_where_the_client_can_read_it() {
    let p = tmp_path("failfile");
    cleanup(&p);
    write_failure(&p, &BindFailure::NotASocket { kind: "directory" });

    let body = std::fs::read_to_string(failure_path(&p)).expect("report written");
    assert!(body.contains("reason: "), "must carry a reason");
    assert!(body.contains("remedy: "), "must carry a remedy");
    assert!(body.contains("not a socket"), "reason must be specific");
    cleanup(&p);
}

#[test]
fn a_successful_bind_clears_a_previous_failure() {
    // A stale report is worse than none: it explains a problem that is over.
    let p = tmp_path("failclear");
    cleanup(&p);
    write_failure(&p, &BindFailure::ForeignListener);
    assert!(std::path::Path::new(&failure_path(&p)).exists());

    let got = acquire(&p).expect("bind");
    assert!(
        !std::path::Path::new(&failure_path(&p)).exists(),
        "a stale failure report must not outlive the failure"
    );
    drop(got);
    cleanup(&p);
}

/// A lost single-instance race must not leave a "reason" behind for clients.
///
/// The sidecar answers "why can I not reach a daemon?". `LiveInstance` says the
/// opposite — a healthy daemon owns the path — so reporting it there made the
/// file explain a client's error with "the running daemon is healthy". Found in
/// the wild on 2026-08-30: a live daemon on /tmp/divoom.sock alongside a
/// /tmp/divoom.sock.failure describing the attempt that lost to it.
#[test]
fn live_instance_is_not_a_fact_about_the_socket() {
    assert!(
        !BindFailure::LiveInstance.describes_the_socket(),
        "losing the single-instance race says nothing about the socket's health"
    );
    // Everything else does describe it, and must keep reporting.
    for f in [
        BindFailure::ForeignListener,
        BindFailure::NotASocket { kind: "directory" },
        BindFailure::StartupInProgress,
        BindFailure::PermissionDenied {
            err: "denied".into(),
        },
        BindFailure::Io { err: "boom".into() },
    ] {
        assert!(f.describes_the_socket(), "{f:?} must still be reported");
    }
}

/// Clearing is what the LOSER can do for the winner: the healthy daemon never
/// re-enters `acquire`, so it can never clear a sidecar written after it
/// started. Whoever loses the race is the one holding the knowledge that the
/// old reason is obsolete.
#[test]
fn clear_failure_removes_a_stale_report() {
    let dir = tempfile::tempdir().unwrap();
    let p = dir.path().join("s.sock").to_string_lossy().to_string();
    write_failure(&p, &BindFailure::ForeignListener);
    assert!(std::path::Path::new(&failure_path(&p)).exists());

    clear_failure(&p);
    assert!(
        !std::path::Path::new(&failure_path(&p)).exists(),
        "a stale reason outliving its condition is worse than no reason"
    );
}
