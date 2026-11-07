//! Shared helpers for `live_jobs_stress.rs`: a daemon with a mock panel, the
//! mock's command count, the panel's queue, and the waits that order a
//! scenario by EVENT rather than by a clock gap (D.LINKDROP).
use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

pub async fn daemon_with_mock(mac: &str) -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": mac})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true), "mock connect: {conn}");
    // No encoder precondition any more: the encoder is Rust inside this binary,
    // so "is it available" is not a question about the machine any more. The
    // assertion it guarded (build the dylib first) has no subject left.
    d
}

/// Number of commands the mock behind `mac` has received so far.
pub async fn sent_count(d: &Daemon, mac: &str) -> usize {
    let t = d
        .fleet
        .get(mac)
        .await
        .expect("device known")
        .transport()
        .await
        .expect("device connected");
    match &*t {
        DeviceTransport::Mock(m) => m.sent_commands.lock().unwrap().len(),
        _ => panic!("expected a mock transport"),
    }
}

/// The queue every command to `mac` goes through right now.
pub async fn queue_of(d: &Daemon, mac: &str) -> divoomd::command_queue::CommandQueue {
    d.fleet
        .get(mac)
        .await
        .expect("device known")
        .link()
        .await
        .expect("device connected")
        .queue
        .clone()
}

pub async fn start_job(d: &Daemon, mac: &str, kind: &str) -> serde_json::Value {
    d.handle(make_request(
        "live_job_start",
        Some(json!({"kind": kind, "mac": mac, "params": {"size": 16}})),
        None,
    ))
    .await
}

pub async fn stop_job(d: &Daemon, mac: &str, kind: &str) -> serde_json::Value {
    d.handle(make_request(
        "live_job_stop",
        Some(json!({"kind": kind, "mac": mac})),
        None,
    ))
    .await
}

/// Poll until `cond` holds, or give up; true when it held.
pub async fn wait_until(budget: Duration, cond: impl Fn() -> bool) -> bool {
    let deadline = tokio::time::Instant::now() + budget;
    loop {
        if cond() {
            return true;
        }
        if tokio::time::Instant::now() >= deadline {
            return false;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

/// The CI runner's stall, made deterministic: block this runtime's ONE
/// thread from just before a 5 s job tick falls due until well after it,
/// so the tick and whatever the test body waits on come due in the same
/// turn. A scenario whose order rests on a clock gap between two deadlines
/// goes red under this every time; one ordered by an event does not.
pub fn runtime_stall_across_the_next_tick() -> tokio::task::JoinHandle<()> {
    tokio::spawn(async {
        tokio::time::sleep(Duration::from_millis(4900)).await;
        std::thread::sleep(Duration::from_millis(600));
    })
}

/// Poll until the mock has received at least `n` commands, or give up.
pub async fn wait_for_sent(d: &Daemon, mac: &str, n: usize, budget: Duration) -> usize {
    let deadline = tokio::time::Instant::now() + budget;
    loop {
        let c = sent_count(d, mac).await;
        if c >= n || tokio::time::Instant::now() >= deadline {
            return c;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

pub async fn daemon_with_mock_on(d: &Daemon, mac: &str) -> serde_json::Value {
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": mac})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true), "mock reconnect: {conn}");
    conn
}
