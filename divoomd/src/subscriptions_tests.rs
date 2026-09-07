//! Unit tests for the LRU subscription registry.
//!
//! Time is driven by tokio's paused clock, so the eviction window is exercised
//! exactly rather than slept through.

use super::*;

fn reg(capacity: usize, secs: u64) -> Arc<Registry> {
    Registry::new(capacity, Duration::from_secs(secs))
}

#[tokio::test(start_paused = true)]
async fn admits_up_to_capacity() {
    let r = reg(3, 60);
    let leases: Vec<_> = (0..3).map(|_| r.admit().expect("under capacity")).collect();
    assert_eq!(r.len(), 3);
    drop(leases);
    assert_eq!(r.len(), 0, "dropping a lease must free the slot");
}

#[tokio::test(start_paused = true)]
async fn a_full_registry_of_active_subscriptions_refuses() {
    // The guard against eviction churn: if everyone is recently active, a
    // newcomer is told no rather than being allowed to displace a live client.
    let r = reg(2, 60);
    let _a = r.admit().unwrap();
    let _b = r.admit().unwrap();
    assert!(r.admit().is_none(), "must not evict a recently active peer");
}

#[tokio::test(start_paused = true)]
async fn a_stale_subscription_is_evicted_for_a_newcomer() {
    let r = reg(1, 60);
    let stale = r.admit().unwrap();
    let evicted = stale.evict.clone();

    tokio::time::advance(Duration::from_secs(61)).await;

    let _fresh = r.admit().expect("a stale slot must be reclaimable");
    assert_eq!(r.len(), 1, "the registry stays bounded");

    // The evicted task is told, so it can announce the renegotiation.
    tokio::time::timeout(Duration::from_millis(50), evicted.notified())
        .await
        .expect("the evicted subscription must be notified, not silently dropped");
}

#[tokio::test(start_paused = true)]
async fn activity_defends_a_slot_and_the_quiet_one_loses_it() {
    // THE POINT OF THE WHOLE MODULE. Two subscriptions age together; one client
    // speaks. The one that spoke is kept, the silent one is renegotiated.
    let r = reg(2, 60);
    let quiet = r.admit().unwrap();
    let busy = r.admit().unwrap();
    let quiet_evict = quiet.evict.clone();
    let busy_evict = busy.evict.clone();

    tokio::time::advance(Duration::from_secs(50)).await;
    r.touch(busy.id); // the busy client says something
    tokio::time::advance(Duration::from_secs(50)).await;

    // Both are now older than the window, but only one has proven itself.
    let _newcomer = r.admit().expect("the stale slot is reclaimable");

    tokio::time::timeout(Duration::from_millis(50), quiet_evict.notified())
        .await
        .expect("the SILENT subscription is the one that should be renegotiated");
    assert!(
        tokio::time::timeout(Duration::from_millis(50), busy_evict.notified())
            .await
            .is_err(),
        "a subscription whose client spoke inside the window must be left alone"
    );
}

#[tokio::test(start_paused = true)]
async fn touching_an_unknown_id_is_harmless() {
    let r = reg(1, 60);
    r.touch(9999);
    assert_eq!(r.len(), 0);
}

#[tokio::test(start_paused = true)]
async fn an_evicted_lease_drop_does_not_free_someone_elses_slot() {
    // The evicted entry is removed at eviction time, so its Lease drop must be a
    // no-op. If it removed by position, or matched loosely, it would free the
    // NEWCOMER's slot and the registry would leak capacity.
    let r = reg(1, 60);
    let stale = r.admit().unwrap();
    tokio::time::advance(Duration::from_secs(61)).await;
    let fresh = r.admit().unwrap();
    assert_eq!(r.len(), 1);

    drop(stale); // the evicted one winds up afterwards, as it would in practice
    assert_eq!(r.len(), 1, "the newcomer must still hold its slot");
    assert_eq!(fresh.id, 2);

    drop(fresh);
    assert_eq!(r.len(), 0);
}

#[tokio::test(start_paused = true)]
async fn capacity_is_never_zero() {
    let r = reg(0, 60);
    assert_eq!(r.capacity(), 1);
    assert!(
        r.admit().is_some(),
        "a zero budget would refuse every client"
    );
}
