//! A `disconnect` racing a `live_job_start` (P5.9).
//!
//! `start` looks the panel up, spawns the job, then installs it on the
//! panel. P5.8 left those two steps unfenced against `Fleet::remove`: a
//! `disconnect` landing between them removed the panel, the install then
//! put a running job on the removed `Device`, and the reply said success --
//! a widget nobody can list or stop, on a panel the daemon has forgotten.
//!
//! The interleaving is forced, not hoped for: a `PausePoint` parks `start` after
//! the lookup and before the install, the test runs the `disconnect` in that
//! window, then lets `start` go on.

use std::sync::Arc;

use crate::daemon::Daemon;
use crate::protocol::make_request;
use crate::socket_server::Handler as _;
use serde_json::{json, Value};

const MAC: &str = "P59_RACE";

async fn ask(d: &Daemon, command: &str, args: Value) -> Value {
    d.handle(make_request(command, Some(args), None)).await
}

#[tokio::test]
async fn a_disconnect_between_lookup_and_install_leaves_no_job_running() {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    let r = ask(&d, "connect", json!({ "mock": true, "mac": MAC })).await;
    assert_eq!(r["success"], json!(true), "{r}");
    let panel = d.fleet.get(MAC).await.expect("linked");

    let (reached, resume) = d.live_jobs.pause_before_install.arm();
    let starter = tokio::spawn({
        let d = d.clone();
        async move {
            ask(
                &d,
                "live_job_start",
                json!({ "mac": MAC, "kind": "sysmon", "params": { "size": 16 } }),
            )
            .await
        }
    });
    reached
        .await
        .expect("start reached the window after its lookup");
    let gone = ask(&d, "disconnect", json!({ "mac": MAC })).await;
    assert_eq!(gone["success"], json!(true), "{gone}");
    resume.send(()).expect("start is still parked");
    let reply = starter.await.expect("start finished");

    assert_eq!(
        panel.live_kind().await,
        None,
        "a job is running on a panel the fleet removed"
    );
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(reply["code"], json!("unknown_device"), "{reply}");
    assert!(
        reply["error"].as_str().unwrap_or_default().contains(MAC),
        "the refusal names the panel: {reply}"
    );
}
