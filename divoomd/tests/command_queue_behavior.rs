//! Behavioral parity for the command queue, mirroring the archived Python daemon's
//! `tests/test_command_queue.py` (+ the R53.x `acquire_now` steal-reject test).

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use divoomd::command_queue::{AcquireError, CommandQueue};

fn log() -> Arc<Mutex<Vec<String>>> {
    Arc::new(Mutex::new(Vec::new()))
}

#[tokio::test(flavor = "multi_thread")]
async fn fifo_ordering() {
    let q = CommandQueue::new(None, None);
    let l = log();
    let mut rxs = Vec::new();
    for n in 1..=3u32 {
        let l = l.clone();
        rxs.push(q.submit(None, async move {
            l.lock().unwrap().push(format!("{n}"));
            n
        }));
    }
    for rx in rxs {
        rx.await.unwrap();
    }
    assert_eq!(*l.lock().unwrap(), vec!["1", "2", "3"]);
}

#[tokio::test(flavor = "multi_thread")]
async fn exclusive_defers_non_matching_until_release() {
    let q = CommandQueue::new(Some(Duration::from_secs(30)), None);
    let l = log();
    q.acquire_now("X").unwrap();

    let (l1, l2, l3) = (l.clone(), l.clone(), l.clone());
    let o1 = q.submit(Some("X".into()), async move {
        l1.lock().unwrap().push("x1".into());
    });
    let none = q.submit(None, async move {
        l2.lock().unwrap().push("none".into());
    });
    let o2 = q.submit(Some("X".into()), async move {
        l3.lock().unwrap().push("x2".into());
    });

    o1.await.unwrap();
    o2.await.unwrap();
    // the tokenless item is gated behind the exclusive owner — must not have run yet
    assert_eq!(*l.lock().unwrap(), vec!["x1", "x2"]);

    q.release("X");
    none.await.unwrap();
    assert_eq!(*l.lock().unwrap(), vec!["x1", "x2", "none"]);
}

#[tokio::test(flavor = "multi_thread")]
async fn acquire_now_rejects_steal_immediately() {
    let q = CommandQueue::new(Some(Duration::from_secs(30)), None);
    assert!(q.acquire_now("A").is_ok());

    let t0 = Instant::now();
    assert_eq!(q.acquire_now("B"), Err(AcquireError::HeldByAnother));
    assert!(
        t0.elapsed() < Duration::from_millis(100),
        "steal-reject must be immediate"
    );
    assert_eq!(q.owner().as_deref(), Some("A"), "slot must NOT be stolen");

    // same-token re-acquire is idempotent
    assert!(q.acquire_now("A").is_ok());
    assert_eq!(q.owner().as_deref(), Some("A"));
}

#[tokio::test(flavor = "multi_thread")]
async fn orphaned_exclusive_auto_releases() {
    // G3: an owner that acquires then goes idle past exclusive_timeout is
    // force-released so the rest of the queue drains.
    let q = CommandQueue::new(Some(Duration::from_millis(150)), None);
    let l = log();
    q.acquire_now("A").unwrap(); // A holds but never submits

    let l2 = l.clone();
    let rx = q.submit(None, async move {
        l2.lock().unwrap().push("free".into());
    });

    let res = tokio::time::timeout(Duration::from_secs(2), rx).await;
    assert!(
        res.is_ok() && res.unwrap().is_ok(),
        "tokenless item should run after force-release"
    );
    assert_eq!(*l.lock().unwrap(), vec!["free"]);
    assert_eq!(q.owner(), None, "owner must be force-released");
}

#[tokio::test(flavor = "multi_thread")]
async fn item_timeout_rejects_waiting_item() {
    let q = CommandQueue::new(None, Some(Duration::from_millis(80)));
    // The first job holds the worker ~300ms; the second waits behind it and
    // exceeds its 80ms item timeout before it can be dispatched.
    let slow = q.submit(None, async {
        tokio::time::sleep(Duration::from_millis(300)).await;
        1u32
    });
    let waiter = q.submit(None, async { 2u32 });

    assert_eq!(slow.await.unwrap(), 1);
    assert!(
        waiter.await.is_err(),
        "an item waiting past item_timeout must be rejected"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_leased_hold_is_not_reaped_when_idle() {
    // P4.6: a screen lease draws once and then holds the screen for its TTL;
    // the G3 idle auto-release (above) must not end it after 150 ms of quiet,
    // even with another caller's item waiting -- which is exactly when G3
    // reaps. Only the lease's own end, `release`, frees it.
    let q = CommandQueue::new(Some(Duration::from_millis(150)), None);
    q.hold("L").unwrap();
    assert!(matches!(q.hold("M"), Err(AcquireError::HeldByAnother)));
    assert!(matches!(
        q.acquire_now("M"),
        Err(AcquireError::HeldByAnother)
    ));
    let l = log();
    let l2 = l.clone();
    let mut waiting = q.submit(None, async move {
        l2.lock().unwrap().push("free".into());
    });
    // The holder's own exclusive_start on it does not re-arm the reaper.
    q.acquire_now("L").unwrap();
    let early = tokio::time::timeout(Duration::from_millis(450), &mut waiting).await;
    assert!(early.is_err(), "the waiting item ran: the lease was reaped");
    assert_eq!(
        q.owner().as_deref(),
        Some("L"),
        "a lease outlives the idle timeout"
    );
    q.release("L");
    let ran = tokio::time::timeout(Duration::from_secs(2), waiting).await;
    assert!(
        ran.is_ok_and(|r| r.is_ok()),
        "released, the waiting item runs"
    );
    assert_eq!(*l.lock().unwrap(), vec!["free"]);
    // ...and a plain exclusive owner after it IS reaped again: release
    // resets the hold.
    q.acquire_now("A").unwrap();
    let after = q.submit(None, async {});
    assert!(tokio::time::timeout(Duration::from_secs(2), after)
        .await
        .is_ok());
    assert_eq!(q.owner(), None, "release resets the hold");
}
