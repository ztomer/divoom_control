//! Notify/response correlation behavior, pinning the two load-bearing rules from
//! this session's hardware fixes (generic-ACK scalar clear; listen-set priority).

use std::time::Duration;

use divoomd::response::{
    route_notification, wait_for_any_response, wait_for_response, Frame, HandlerAction,
};
use tokio::sync::mpsc;

// ── routing decision (the handler side) ─────────────────────────────────────

#[test]
fn route_exact_expected_clears_scalar() {
    assert_eq!(
        route_notification(0x46, Some(0x46), &[]),
        HandlerAction::QueueAndClear
    );
}

#[test]
fn route_generic_ack_for_genericack_command_clears_scalar() {
    // 0x46 IS a generic-ACK command, so a 0x33 reply while expecting 0x46 clears the
    // scalar. This is load-bearing for the 0x46 protocol autoprobe (the iOS-LE revert).
    assert_eq!(
        route_notification(0x33, Some(0x46), &[]),
        HandlerAction::QueueAndClear
    );
}

#[test]
fn route_generic_ack_for_non_genericack_command_drops() {
    // 0x74 is NOT a generic-ACK command, so a bare 0x33 is not its ack -> dropped.
    assert_eq!(
        route_notification(0x33, Some(0x74), &[]),
        HandlerAction::Drop
    );
}

#[test]
fn route_unexpected_with_no_expectation_drops() {
    assert_eq!(route_notification(0x46, None, &[]), HandlerAction::Drop);
}

#[test]
fn route_listened_queues_without_clearing_even_when_expected() {
    // 0x8B in the listen set queues WITHOUT clearing the scalar, even if it's also
    // the expected command — this is what lets 0x8B retransmit frames survive the
    // chunk loop (the animation dead-path fix). Listen is checked first.
    assert_eq!(
        route_notification(0x8B, None, &[0x8B]),
        HandlerAction::Queue
    );
    assert_eq!(
        route_notification(0x8B, Some(0x8B), &[0x8B]),
        HandlerAction::Queue
    );
}

// ── wait_for_response ───────────────────────────────────────────────────────

#[tokio::test]
async fn wait_resolves_on_exact_command() {
    let (tx, mut rx) = mpsc::channel(8);
    tx.send(Frame {
        command_id: 0x46,
        payload: vec![0x01, 0x02],
    })
    .await
    .unwrap();
    let got = wait_for_response(&mut rx, 0x46, Duration::from_secs(1)).await;
    assert_eq!(got, Some(vec![0x01, 0x02]));
}

#[tokio::test]
async fn wait_skips_generic_ack_then_resolves() {
    let (tx, mut rx) = mpsc::channel(8);
    // intermediate 0x33 generic-ACK, then the real 0x46 data frame
    tx.send(Frame {
        command_id: 0x33,
        payload: vec![],
    })
    .await
    .unwrap();
    tx.send(Frame {
        command_id: 0x46,
        payload: vec![0xAB],
    })
    .await
    .unwrap();
    let got = wait_for_response(&mut rx, 0x46, Duration::from_secs(1)).await;
    assert_eq!(got, Some(vec![0xAB]), "0x33 must be skipped, 0x46 resolves");
}

#[tokio::test]
async fn wait_discards_unexpected_then_times_out() {
    let (tx, mut rx) = mpsc::channel(8);
    tx.send(Frame {
        command_id: 0x99,
        payload: vec![1],
    })
    .await
    .unwrap();
    // nothing matching 0x46 arrives -> timeout
    let got = wait_for_response(&mut rx, 0x46, Duration::from_millis(120)).await;
    assert_eq!(got, None);
}

#[tokio::test]
async fn wait_times_out_on_silence() {
    let (_tx, mut rx) = mpsc::channel::<Frame>(8);
    let got = wait_for_response(&mut rx, 0x46, Duration::from_millis(80)).await;
    assert_eq!(got, None);
}

// ── wait_for_any_response ───────────────────────────────────────────────────

#[tokio::test]
async fn wait_any_resolves_on_first_wanted() {
    let (tx, mut rx) = mpsc::channel(8);
    tx.send(Frame {
        command_id: 0x10,
        payload: vec![],
    })
    .await
    .unwrap(); // ignored
    tx.send(Frame {
        command_id: 0x9E,
        payload: vec![0x07],
    })
    .await
    .unwrap();
    let got = wait_for_any_response(&mut rx, &[0x8B, 0x9E], Duration::from_secs(1)).await;
    assert_eq!(got, Some((0x9E, vec![0x07])));
}
