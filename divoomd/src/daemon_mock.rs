//! Mock-transport-only command handlers. Split from `daemon_connect.rs` to keep
//! that file under the 500-LOC ground rule (R61 follow-up).

use serde_json::{json, Value};

use crate::daemon::{Daemon, DeviceTransport};
use crate::daemon_connect::{owned_devices_payload, status_payload};
use crate::protocol::{err_code, ErrorCode, Request};

/// Simulate a mid-session BLE/LAN drop (unexpected — not a clean user
/// disconnect) on the daemon's mock transport, for hardware-free e2e tests of
/// the degraded/disconnected UI feedback path. Walks the exact same two
/// broadcasts a real drop goes through (`cmd_device_call`'s failed-op
/// "degraded" push, then the device-teardown `cmd_disconnect` already does),
/// only tagging the final state `"disconnected"` (not `cmd_disconnect`'s
/// default `"idle"`) so the UI/tests can tell an unexpected drop from a clean
/// disconnect. Optional `{"reason": "..."}` (default `"dropped"`, mirroring
/// the Python reference's `FailureReason.DROPPED`) is echoed on both
/// broadcasts and the reply for the e2e assertion.
pub(crate) async fn cmd_mock_simulate_drop(daemon: &Daemon, req: &Request) -> Value {
    let current = daemon
        .fleet
        .resolve_target(req.args.get("mac").and_then(|v| v.as_str()))
        .await
        .ok();
    let transport = match current {
        Some(ref d) => d.transport().await,
        None => None,
    };
    let is_mock = matches!(transport.as_deref(), Some(DeviceTransport::Mock(_)));
    if !is_mock {
        return err_code(
            ErrorCode::NoDevice,
            "mock_simulate_drop requires an active mock connection",
        );
    }

    let reason = req
        .args
        .get("reason")
        .and_then(|v| v.as_str())
        .unwrap_or("dropped")
        .to_string();
    let id = current.map(|d| d.id.clone());

    // Step 1: link goes unhealthy — still owned, dot flips amber (mirrors the
    // R59 degraded push on a failed device_call op).
    let mut degraded_evt = status_payload(true, id.as_deref(), Some("degraded"));
    if let Some(o) = degraded_evt.as_object_mut() {
        o.insert("reason".into(), json!(reason));
    }
    let _ = daemon.tx.send(degraded_evt);

    // Step 2: the link is actually gone — tear the device down the same way
    // cmd_disconnect does, but tag "disconnected" (not "idle") so this reads
    // as an unexpected drop, not a clean user-initiated disconnect.
    // A dropped LINK: the device keeps its identity and its live job (which
    // reports waiting_for_device until a reconnect adopts a new link).
    if let Some(ref i) = id {
        daemon.fleet.detach(i).await;
    }
    let mut disconnected_evt = status_payload(false, None, Some("disconnected"));
    if let Some(o) = disconnected_evt.as_object_mut() {
        o.insert("reason".into(), json!(reason.clone()));
    }
    let _ = daemon.tx.send(disconnected_evt);
    let _ = daemon.tx.send(owned_devices_payload(daemon).await);

    json!({"success": true, "connection_state": "disconnected", "reason": reason})
}

/// Every command a linked mock panel was asked to send, oldest first, as
/// `[[command id, [arg bytes]], ...]` (P6.6).
///
/// The wire of a panel with no radio. A wall write's reply is the daemon's
/// own account of what each slot did; an end-to-end test that must see a
/// write ARRIVE at each panel reads it here instead. Only a mock answers --
/// a real panel's wire is `DIVOOMD_BLE_DEBUG`'s.
pub(crate) async fn cmd_mock_sent(daemon: &Daemon, req: &Request) -> Value {
    let mac = req.args.get("mac").and_then(Value::as_str).unwrap_or("");
    let transport = match daemon.fleet.get(mac).await {
        Some(dev) => dev.transport().await,
        None => None,
    };
    let Some(DeviceTransport::Mock(mock)) = transport.as_deref() else {
        return err_code(
            ErrorCode::NoDevice,
            &format!("mock_sent: {mac} is not a linked mock panel"),
        );
    };
    let sent: Vec<Value> = mock
        .sent_commands
        .lock()
        .map(|c| c.iter().map(|(id, args)| json!([id, args])).collect())
        .unwrap_or_default();
    json!({"success": true, "sent": sent})
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::daemon_connect::cmd_connect;
    use crate::protocol::make_request;

    // mock_simulate_drop must walk the mock transport through the SAME two
    // broadcasts a real unexpected BLE drop needs: degraded (still owned, link
    // unhealthy) then disconnected (device torn down) — proving the daemon's
    // degraded/disconnected transition end-to-end without hardware.
    #[tokio::test]
    async fn mock_simulate_drop_broadcasts_degraded_then_disconnected() {
        let daemon = Daemon::new();
        let c = cmd_connect(
            &daemon,
            &make_request("connect", Some(json!({"mock": true})), None),
        )
        .await;
        assert_eq!(c["connection_state"], json!("connected"));

        let mut rx = daemon.tx.subscribe();

        let req = make_request(
            "mock_simulate_drop",
            Some(json!({"reason": "out_of_range"})),
            None,
        );
        let res = cmd_mock_simulate_drop(&daemon, &req).await;
        assert_eq!(res["success"], json!(true));
        assert_eq!(res["connection_state"], json!("disconnected"));
        assert_eq!(res["reason"], json!("out_of_range"));

        // The link is gone afterward, exactly like a real drop: no current
        // device, nothing connected -- but the identity is kept so a live
        // job can wait for the panel to come back.
        assert!(daemon.fleet.resolve_target(None).await.is_err());
        assert_eq!(daemon.fleet.linked().await.len(), 0);
        assert!(daemon.fleet.get("MOCK_MAC").await.is_some());

        // First broadcast: degraded, still "connected" (link unhealthy but owned).
        let degraded_evt = rx.try_recv().expect("degraded status broadcast missing");
        assert_eq!(degraded_evt["type"], json!("status"));
        assert_eq!(degraded_evt["state"], json!("degraded"));
        assert_eq!(degraded_evt["connected"], json!(true));
        assert_eq!(degraded_evt["mac"], json!("MOCK_MAC"));
        assert_eq!(degraded_evt["reason"], json!("out_of_range"));

        // Second broadcast: disconnected, no longer connected/owned.
        let disconnected_evt = rx
            .try_recv()
            .expect("disconnected status broadcast missing");
        assert_eq!(disconnected_evt["type"], json!("status"));
        assert_eq!(disconnected_evt["state"], json!("disconnected"));
        assert_eq!(disconnected_evt["connected"], json!(false));
        assert_eq!(disconnected_evt["reason"], json!("out_of_range"));

        // Third broadcast: owned_devices drops to empty.
        let owned_evt = rx.try_recv().expect("owned_devices broadcast missing");
        assert_eq!(owned_evt["type"], json!("owned_devices"));
        assert_eq!(owned_evt["devices"], json!([]));
    }

    // Default reason (no arg) must fall back to "dropped" — mirrors the Python
    // reference's FailureReason.DROPPED for an unexpected mid-session loss.
    #[tokio::test]
    async fn mock_simulate_drop_defaults_reason_to_dropped() {
        let daemon = Daemon::new();
        cmd_connect(
            &daemon,
            &make_request("connect", Some(json!({"mock": true})), None),
        )
        .await;
        let res =
            cmd_mock_simulate_drop(&daemon, &make_request("mock_simulate_drop", None, None)).await;
        assert_eq!(res["reason"], json!("dropped"));
    }

    // No device connected at all → a clean error, not a panic or silent no-op.
    #[tokio::test]
    async fn mock_simulate_drop_with_no_device_errors() {
        let daemon = Daemon::new();
        let res =
            cmd_mock_simulate_drop(&daemon, &make_request("mock_simulate_drop", None, None)).await;
        assert_eq!(res["success"], json!(false));
        assert!(res["error"].as_str().unwrap().contains("mock"));
    }

    // A non-mock (real) transport must also be rejected — this command may only
    // ever act on the mock transport, never a genuine BLE/LAN/SPP device.
    #[tokio::test]
    async fn mock_simulate_drop_with_real_transport_errors() {
        let daemon = Daemon::new();
        // Set up a LAN transport directly (no network I/O needed to construct it)
        // to stand in for "a real device is connected".
        let lan = crate::lan::LanTransport::new("127.0.0.1", 0);
        daemon
            .fleet
            .adopt(
                "LAN:127.0.0.1",
                std::sync::Arc::new(crate::daemon::DeviceTransport::Lan(lan)),
            )
            .await;

        let res =
            cmd_mock_simulate_drop(&daemon, &make_request("mock_simulate_drop", None, None)).await;
        assert_eq!(res["success"], json!(false));
        // The real (non-mock) device must be left untouched.
        assert!(
            daemon
                .fleet
                .resolve_target(None)
                .await
                .unwrap()
                .is_connected()
                .await
        );
    }

    // The mock's wire, by mac: what THAT panel was asked to send and nothing
    // another panel was (P6.6).
    #[tokio::test]
    async fn mock_sent_answers_each_mock_panels_own_commands() {
        let daemon = Daemon::new();
        for mac in ["AA:00:00:00:00:01", "BB:00:00:00:00:02"] {
            let c = cmd_connect(
                &daemon,
                &make_request("connect", Some(json!({"mock": true, "mac": mac})), None),
            )
            .await;
            assert_eq!(c["success"], json!(true), "{c}");
        }
        let set = make_request(
            "device_call",
            Some(json!({"method": "set_brightness", "args": [40], "mac": "AA:00:00:00:00:01"})),
            None,
        );
        assert_eq!(daemon.cmd_device_call(&set).await["success"], json!(true));
        let ask = |mac: &str| make_request("mock_sent", Some(json!({"mac": mac})), None);
        let a = cmd_mock_sent(&daemon, &ask("AA:00:00:00:00:01")).await;
        assert!(
            a["sent"].as_array().unwrap().contains(&json!([0x74, [40]])),
            "{a}"
        );
        let b = cmd_mock_sent(&daemon, &ask("BB:00:00:00:00:02")).await;
        assert!(
            !b["sent"].as_array().unwrap().contains(&json!([0x74, [40]])),
            "{b}"
        );
    }

    // A mac with no mock panel behind it is refused with a code, never an
    // empty list that reads as "nothing was sent".
    #[tokio::test]
    async fn mock_sent_refuses_a_mac_with_no_mock_panel() {
        let daemon = Daemon::new();
        let res = cmd_mock_sent(
            &daemon,
            &make_request("mock_sent", Some(json!({"mac": "CC:00:00:00:00:03"})), None),
        )
        .await;
        assert_eq!(res["success"], json!(false));
        assert_eq!(res["code"], json!("no_device"));
    }
}
