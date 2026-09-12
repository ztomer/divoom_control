//! Stress scenarios for the live-widget pipeline (2026-09-12).
//!
//! The user-facing symptom this suite exists for is "the widget keeps coming
//! back" / frames repeating on a screen that was told to show something else.
//! Each test pins one architectural invariant of the pipeline against the
//! mock transport, which records every command the daemon sends:
//!
//! 1. `live_job_stop` is a FENCE: no frame lands after it returns.
//! 2. A mac-less `device_call` (what the GUI sends) and a live job on the same
//!    physical device are serialized on ONE queue.
//! 3. A device shows one live widget at a time: starting a second kind on a
//!    device retires the first.
//! 4. Rapid start/stop churn leaks nothing and leaves the device quiet.
//! 5. Disconnecting a device stops its jobs and nothing lands on the next
//!    transport for that mac.
//!
//! Every scenario counts FRAMES on the mock, and a frame exists only after
//! the native encoder (`divoom_lib/libdivoom_compact.{dylib,so}`, built by
//! `scripts/build_libdivoom.sh` on every platform) has encoded it. The
//! encoder assertion below is deliberate: without it every count reads zero,
//! which is the pass condition for half the scenarios.
use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

async fn daemon_with_mock(mac: &str) -> Arc<Daemon> {
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
    assert!(
        d.encoder().is_some(),
        "these scenarios need the frame encoder: run scripts/build_libdivoom.sh"
    );
    d
}

/// Number of commands the mock behind `mac` has received so far.
async fn sent_count(d: &Daemon, mac: &str) -> usize {
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
async fn queue_of(d: &Daemon, mac: &str) -> divoomd::command_queue::CommandQueue {
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

async fn start_job(d: &Daemon, mac: &str, kind: &str) -> serde_json::Value {
    d.handle(make_request(
        "live_job_start",
        Some(json!({"kind": kind, "mac": mac, "params": {"size": 16}})),
        None,
    ))
    .await
}

async fn stop_job(d: &Daemon, mac: &str, kind: &str) -> serde_json::Value {
    d.handle(make_request(
        "live_job_stop",
        Some(json!({"kind": kind, "mac": mac})),
        None,
    ))
    .await
}

/// Poll until the mock has received at least `n` commands, or give up.
async fn wait_for_sent(d: &Daemon, mac: &str, n: usize, budget: Duration) -> usize {
    let deadline = tokio::time::Instant::now() + budget;
    loop {
        let c = sent_count(d, mac).await;
        if c >= n || tokio::time::Instant::now() >= deadline {
            return c;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

#[tokio::test]
async fn stop_is_a_fence_even_for_a_frame_already_queued() {
    // The failure mode: the job's push is already sitting in the device
    // queue (behind a busy device) when the job is stopped. Aborting the
    // job task cancels the job's AWAIT of the push, not the push itself, so
    // the frame lands after "stop" returned -- one more widget frame on a
    // screen the user just told to show a clock.
    let d = daemon_with_mock("DEV_A").await;
    let queue = queue_of(&d, "DEV_A").await;
    let permit = queue.acquire(None).await.expect("hold the device");

    assert_eq!(
        start_job(&d, "DEV_A", "sysmon").await["success"],
        json!(true)
    );
    // Let the job compute its first frame and enqueue the push behind us.
    tokio::time::sleep(Duration::from_millis(400)).await;
    assert_eq!(
        sent_count(&d, "DEV_A").await,
        0,
        "device is held; nothing may land yet"
    );

    assert_eq!(
        stop_job(&d, "DEV_A", "sysmon").await["stopped"],
        json!(true)
    );
    drop(permit);
    tokio::time::sleep(Duration::from_millis(500)).await;

    assert_eq!(
        sent_count(&d, "DEV_A").await,
        0,
        "a frame queued by a job that has since been stopped must not reach the device"
    );
}

#[tokio::test]
async fn a_macless_device_call_shares_the_live_jobs_queue() {
    // The GUI's device_call carries no mac. If it rides a different queue
    // from the live job pushing to the same physical device, the two
    // interleave packets on one BLE link. Holding the per-device queue must
    // therefore block a mac-less call for that device.
    let d = daemon_with_mock("DEV_A").await;
    let queue = queue_of(&d, "DEV_A").await;
    let _permit = queue.acquire(None).await.expect("hold the device");

    let call = d.handle(make_request(
        "device_call",
        Some(json!({"method": "display.switch_channel", "kwargs": {"channel": "clock"}})),
        None,
    ));
    let outcome = tokio::time::timeout(Duration::from_millis(400), call).await;
    assert!(
        outcome.is_err(),
        "a mac-less device_call ran while the device's queue was held: {outcome:?}"
    );
    assert_eq!(sent_count(&d, "DEV_A").await, 0);
}

#[tokio::test]
async fn one_live_widget_per_screen() {
    // A screen can show one thing. Two kinds for one mac would alternate
    // frames every interval -- the "repeating" the user reported.
    let d = daemon_with_mock("DEV_A").await;
    assert_eq!(
        start_job(&d, "DEV_A", "sysmon").await["success"],
        json!(true)
    );
    assert_eq!(
        start_job(&d, "DEV_A", "stocks").await["success"],
        json!(true)
    );
    let jobs = d.live_jobs.list(Some("DEV_A")).await;
    let kinds: Vec<_> = jobs
        .iter()
        .map(|j| j["kind"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(
        kinds,
        vec!["stocks"],
        "starting stocks must retire sysmon on the same device"
    );
    stop_job(&d, "DEV_A", "stocks").await;
}

#[tokio::test]
async fn start_stop_churn_leaks_nothing_and_leaves_the_device_quiet() {
    let d = daemon_with_mock("DEV_A").await;
    for _ in 0..25 {
        assert_eq!(
            start_job(&d, "DEV_A", "sysmon").await["success"],
            json!(true)
        );
        assert_eq!(
            stop_job(&d, "DEV_A", "sysmon").await["success"],
            json!(true)
        );
    }
    assert!(d.live_jobs.list(Some("DEV_A")).await.is_empty());
    // Whatever landed during the churn is done; from here the device must
    // stay silent.
    tokio::time::sleep(Duration::from_millis(300)).await;
    let settled = sent_count(&d, "DEV_A").await;
    tokio::time::sleep(Duration::from_millis(1200)).await;
    assert_eq!(
        sent_count(&d, "DEV_A").await,
        settled,
        "frames kept landing after every job was stopped"
    );
}

#[tokio::test]
async fn disconnect_stops_jobs_and_a_reconnect_gets_no_ghost_frame() {
    let d = daemon_with_mock("DEV_A").await;
    assert_eq!(
        start_job(&d, "DEV_A", "sysmon").await["success"],
        json!(true)
    );
    let first = wait_for_sent(&d, "DEV_A", 1, Duration::from_secs(3)).await;
    assert!(first >= 1, "the job never pushed a frame");

    // Hold the queue so the NEXT frame is queued, then disconnect underneath it.
    let queue = queue_of(&d, "DEV_A").await;
    let permit = queue.acquire(None).await.expect("hold the device");
    tokio::time::sleep(Duration::from_millis(5200)).await; // one job interval
    let disc = d.handle(make_request("disconnect", None, None)).await;
    assert_eq!(disc["success"], json!(true), "{disc}");
    assert!(d.live_jobs.list(Some("DEV_A")).await.is_empty());
    drop(permit);

    // Reconnect: a fresh mock with an empty command log.
    let _ = daemon_with_mock_on(&d, "DEV_A").await;
    tokio::time::sleep(Duration::from_millis(800)).await;
    assert_eq!(
        sent_count(&d, "DEV_A").await,
        0,
        "a frame from the pre-disconnect job landed on the reconnected device"
    );
}

async fn daemon_with_mock_on(d: &Daemon, mac: &str) -> serde_json::Value {
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

#[tokio::test]
async fn a_link_drop_keeps_the_widget_and_a_reconnect_resumes_it_cleanly() {
    // The identity/connection split: a BLE blip must not lose the user's
    // widget, but nothing queued on the dead link may land on the new one.
    let d = daemon_with_mock("DEV_A").await;
    assert_eq!(
        start_job(&d, "DEV_A", "sysmon").await["success"],
        json!(true)
    );
    assert!(wait_for_sent(&d, "DEV_A", 1, Duration::from_secs(3)).await >= 1);

    // Hold the link so the next frame queues on it, then drop the link.
    let old_queue = queue_of(&d, "DEV_A").await;
    let permit = old_queue.acquire(None).await.expect("hold the device");
    tokio::time::sleep(Duration::from_millis(5200)).await; // one job interval
    let drop_res = d
        .handle(make_request("mock_simulate_drop", None, None))
        .await;
    assert_eq!(drop_res["success"], json!(true), "{drop_res}");
    drop(permit);

    // The job is still installed and honest about the missing panel.
    let jobs = d.live_jobs.list(Some("DEV_A")).await;
    assert_eq!(
        jobs.len(),
        1,
        "the widget must survive a link drop: {jobs:?}"
    );
    let dev = d.fleet.get("DEV_A").await.expect("identity kept");
    assert!(!dev.is_connected().await);

    // Reconnect: a fresh link, a fresh command log.
    daemon_with_mock_on(&d, "DEV_A").await;
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(
        sent_count(&d, "DEV_A").await,
        0,
        "a frame queued on the dropped link landed on the new one"
    );
    // ...and the SAME job resumes pushing on the new link within its interval.
    let resumed = wait_for_sent(&d, "DEV_A", 1, Duration::from_secs(8)).await;
    assert!(
        resumed >= 1,
        "the widget did not resume after the reconnect"
    );
    assert_eq!(d.live_jobs.list(Some("DEV_A")).await.len(), 1);
    stop_job(&d, "DEV_A", "sysmon").await;
}

#[tokio::test]
async fn owned_devices_lists_the_whole_fleet_not_just_the_newcomer() {
    // The GUI re-marks daemon ownership from this list on every event, so a
    // list carrying only the newcomer un-owned every other panel on connect.
    let d = daemon_with_mock("DEV_A").await;
    let mut rx = d.subscribe().expect("daemon broadcasts");
    daemon_with_mock_on(&d, "DEV_B").await;
    let mut owned = None;
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("owned_devices") {
            owned = Some(ev);
        }
    }
    let owned = owned.expect("owned_devices broadcast after the second connect");
    let mut ids: Vec<String> = owned["devices"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v["address"].as_str().unwrap().to_string())
        .collect();
    ids.sort();
    assert_eq!(ids, vec!["DEV_A", "DEV_B"]);
}

#[tokio::test]
async fn disconnecting_one_panel_leaves_the_others_streaming() {
    let d = daemon_with_mock("DEV_A").await;
    daemon_with_mock_on(&d, "DEV_B").await;
    assert_eq!(
        start_job(&d, "DEV_A", "sysmon").await["success"],
        json!(true)
    );
    assert_eq!(
        start_job(&d, "DEV_B", "sysmon").await["success"],
        json!(true)
    );
    assert!(wait_for_sent(&d, "DEV_B", 1, Duration::from_secs(3)).await >= 1);

    let r = d
        .handle(make_request(
            "disconnect",
            Some(json!({"mac": "dev_a"})),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert!(d.fleet.get("DEV_A").await.is_none(), "DEV_A forgotten");
    assert!(
        d.fleet.connected("DEV_B").await.is_some(),
        "DEV_B untouched"
    );
    let kinds: Vec<_> = d
        .live_jobs
        .list(None)
        .await
        .iter()
        .map(|j| j["mac"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(kinds, vec!["DEV_B"], "only DEV_B's job survives");

    // Per-device status: the proxy bound to DEV_B asks about DEV_B even
    // though nothing is "current" any more.
    let st = d
        .handle(make_request(
            "device_status",
            Some(json!({"mac": "DEV_B"})),
            None,
        ))
        .await;
    assert_eq!(st["connected"], json!(true));
    assert_eq!(st["mac"], json!("DEV_B"));
    let st_a = d
        .handle(make_request(
            "device_status",
            Some(json!({"mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(st_a["connected"], json!(false));

    let before = sent_count(&d, "DEV_B").await;
    tokio::time::sleep(Duration::from_millis(5500)).await;
    assert!(
        sent_count(&d, "DEV_B").await > before,
        "DEV_B kept streaming"
    );
    stop_job(&d, "DEV_B", "sysmon").await;
}

#[tokio::test]
async fn owned_devices_never_invents_a_name() {
    // The GUI overwrites its scan name with whatever this carries, so a
    // placeholder here renamed three real panels "Divoom" on screen.
    let d = daemon_with_mock("DEV_A").await;
    let mut rx = d.subscribe().expect("daemon broadcasts");
    d.live_jobs
        .set_device_activity("DEV_A".into(), "clock".into(), None, None)
        .await;
    daemon_with_mock_on(&d, "DEV_B").await;
    let mut owned = None;
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("owned_devices") {
            owned = Some(ev);
        }
    }
    let owned = owned.expect("owned_devices broadcast");
    for dev in owned["devices"].as_array().unwrap() {
        let name = dev["name"].as_str().unwrap();
        assert_ne!(name, "Divoom", "placeholder leaked as a name: {dev}");
    }
}

#[tokio::test]
async fn every_pushed_live_frame_is_broadcast_with_its_pixels() {
    // The bench kept the old cover while the device had the new one,
    // because only a tab's poll refreshed the preview. A frame that
    // reached the panel is announced on the bus with a PNG of itself.
    let d = daemon_with_mock("DEV_A").await;
    let mut rx = d.subscribe().expect("daemon broadcasts");
    assert_eq!(
        start_job(&d, "DEV_A", "sysmon").await["success"],
        json!(true)
    );
    assert!(wait_for_sent(&d, "DEV_A", 1, Duration::from_secs(3)).await >= 1);
    let mut frame_event = None;
    let deadline = tokio::time::Instant::now() + Duration::from_secs(2);
    while tokio::time::Instant::now() < deadline {
        if let Ok(ev) = rx.try_recv() {
            if ev["type"] == json!("activity")
                && ev["kind"] == json!("sysmon")
                && ev["preview"].is_string()
            {
                frame_event = Some(ev);
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let ev = frame_event.expect("an activity event carrying the frame");
    assert_eq!(ev["mac"], json!("DEV_A"));
    assert!(ev["preview"]
        .as_str()
        .unwrap()
        .starts_with("data:image/png;base64,"));
    // ...and the activity record keeps it for a late subscriber.
    let act = d.live_jobs.get_device_activity().await;
    assert!(act["activity"]["DEV_A"]["preview"]
        .as_str()
        .unwrap()
        .starts_with("data:image/png"));
    stop_job(&d, "DEV_A", "sysmon").await;
}
