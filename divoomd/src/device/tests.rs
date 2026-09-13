//! Unit tests for the device aggregate.

use super::*;
use crate::device::Fleet;
use crate::mock_transport::MockTransport;
use serde_json::json;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

fn mock() -> Arc<DeviceTransport> {
    Arc::new(DeviceTransport::Mock(MockTransport::new()))
}

#[tokio::test]
async fn a_single_linked_panel_answers_a_macless_request_and_lookup_ignores_case() {
    let f = Fleet::default();
    f.adopt("aa:bb:CC", mock()).await;
    assert!(f.get("AA:BB:cc").await.is_some());
    assert_eq!(f.resolve_target(None).await.unwrap().id, "aa:bb:CC");
    assert!(f.resolve_target(Some("nope")).await.is_err());
    assert_eq!(f.linked().await.len(), 1);
}

#[tokio::test]
async fn the_selected_panel_takes_macless_requests_and_none_selected_refuses_with_the_count() {
    // "Whichever connected last" put a push on the wrong panel. The active
    // panel is a visible, stable choice instead: the first to link until the
    // user selects another; a later link never steals it.
    let f = Fleet::default();
    f.adopt("A", mock()).await;
    f.adopt("B", mock()).await;
    assert_eq!(f.selected_id().as_deref(), Some("A"));
    assert_eq!(f.resolve_target(None).await.unwrap().id, "A");
    assert!(f.select("b"), "a change");
    assert!(!f.select("B"), "same panel, case-insensitively: no change");
    assert_eq!(f.resolve_target(None).await.unwrap().id, "B");
    assert_eq!(f.resolve_target(Some("a")).await.unwrap().id, "A");
    // A link drop keeps the selection (the panel may come back) but a
    // mac-less request cannot wait for it: it goes to the single linked one.
    f.detach("B").await;
    assert!(f.is_selected("B"));
    assert_eq!(f.resolve_target(None).await.unwrap().id, "A");
    assert!(
        f.resolve_target(Some("B")).await.is_err(),
        "unlinked is not connected"
    );
    // Forgetting the active panel hands the slot to a linked one.
    f.remove("B").await;
    assert_eq!(f.selected_id().as_deref(), Some("A"));
    // An active panel that is NOT linked cannot take a mac-less request,
    // and with several others linked the caller is told which is which.
    f.adopt("C", mock()).await;
    f.select("Z");
    let err = f.resolve_target(None).await.err().expect("refused");
    assert!(
        err.starts_with("the active panel 'Z' is not connected and 2 others are"),
        "{err}"
    );
    assert!(err.contains('A') && err.contains('C'), "{err}");
}

#[tokio::test]
async fn re_adopting_an_id_keeps_the_device_but_retires_its_old_link() {
    let f = Fleet::default();
    let dev = f.adopt("DEV", mock()).await;
    let old = dev.link().await.unwrap();
    let ran = Arc::new(AtomicBool::new(false));
    let permit = old.queue.acquire(None).await.expect("hold");
    let ran2 = ran.clone();
    let old2 = old.clone();
    let waiter = tokio::spawn(async move {
        old2.run(None, async move {
            ran2.store(true, Ordering::SeqCst);
        })
        .await
    });
    tokio::task::yield_now().await;
    let same = f.adopt("dev", mock()).await;
    assert!(
        Arc::ptr_eq(&dev, &same),
        "identity must survive a reconnect"
    );
    let new = same.link().await.unwrap();
    assert!(old.is_retired());
    assert!(!new.is_retired());
    drop(permit);
    assert_eq!(
        waiter.await.unwrap(),
        None,
        "queued work must report 'did not run'"
    );
    assert!(
        !ran.load(Ordering::SeqCst),
        "retired link executed queued work"
    );
    assert_eq!(new.run(None, async { 7 }).await, Some(7));
}

#[tokio::test]
async fn detach_keeps_identity_and_only_that_panel_goes_unlinked() {
    let f = Fleet::default();
    f.adopt("A", mock()).await;
    f.adopt("B", mock()).await;
    f.detach("A").await;
    assert!(f.get("A").await.is_some(), "identity survives");
    assert!(f.connected("A").await.is_none());
    assert!(f.connected("B").await.is_some());
    f.detach("b").await;
    assert!(f.linked().await.is_empty());
    assert_eq!(f.status_now(), (false, None));
}

#[tokio::test]
async fn drain_retires_links_and_forgets_devices() {
    let f = Fleet::default();
    let a = f.adopt("A", mock()).await;
    let link = a.link().await.unwrap();
    let drained = f.drain().await;
    assert_eq!(drained.len(), 1);
    assert!(link.is_retired());
    assert!(f.resolve_target(None).await.is_err());
    assert!(f.get("A").await.is_none());
    assert_eq!(link.run(None, async { 1 }).await, None);
}

#[tokio::test]
async fn a_second_live_job_retires_the_first_and_stop_is_reported() {
    let f = Fleet::default();
    let d = f.adopt("A", mock()).await;
    let a1 = Arc::new(AtomicBool::new(true));
    let h1 = tokio::spawn(std::future::pending::<()>());
    d.install_live_job("sysmon", json!({}), a1.clone(), h1)
        .await;
    let a2 = Arc::new(AtomicBool::new(true));
    let h2 = tokio::spawn(std::future::pending::<()>());
    d.install_live_job("stocks", json!({}), a2.clone(), h2)
        .await;
    assert!(!a1.load(Ordering::SeqCst), "first job's alive flag cleared");
    assert_eq!(d.live_kind().await.as_deref(), Some("stocks"));
    assert!(
        !d.stop_live_job(Some("sysmon")).await,
        "wrong kind is not a stop"
    );
    assert!(d.stop_live_job(Some("stocks")).await);
    assert!(!a2.load(Ordering::SeqCst));
    assert!(d.live_kind().await.is_none());
    assert_eq!(d.activity().await.unwrap().kind, "idle");
}
