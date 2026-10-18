//! What each slot of the wall did with one command (P6.3).
//!
//! The wall's command methods used to return one `bool` for every slot, so a
//! write that failed on one linked panel reached the client as "the wall
//! failed" with no panel named: `degraded` listed only slots with no panel.
//! A wall command now yields a [`WallOutcome`], one entry per slot, and the
//! only way to turn it into an answer is [`WallOutcome::reply`], which names
//! every slot that did not take the command and says why. There is no `bool`
//! view to collapse it into.

use super::{DeviceSlot, DivoomWall};
use crate::daemon::DeviceTransport;
use crate::protocol::{err_with, ErrorCode};
use serde_json::{json, Map, Value};
use std::future::Future;
use std::sync::Arc;

/// What one slot did with a wall command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SlotOutcome {
    /// The panel took the write.
    Accepted,
    /// The slot has no linked panel, so nothing was sent to it.
    Unlinked,
    /// The panel is linked and the write failed, for this reason.
    Failed(String),
}

/// A wall command's result: one `(slot mac, outcome)` per slot, in wall order.
#[must_use]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WallOutcome(Vec<(String, SlotOutcome)>);

impl WallOutcome {
    /// The command's reply: success only when every slot took it. Otherwise
    /// `device_failed`, with `failed` mapping each linked slot whose write
    /// failed to its reason and `degraded` listing each slot with no panel,
    /// and the message naming both.
    #[must_use]
    pub fn reply(&self) -> Value {
        let mut failed = Map::new();
        let mut degraded = Vec::new();
        let mut said = Vec::new();
        for (mac, outcome) in &self.0 {
            match outcome {
                SlotOutcome::Accepted => {}
                SlotOutcome::Unlinked => {
                    said.push(format!("{mac} has no panel linked"));
                    degraded.push(mac.clone());
                }
                SlotOutcome::Failed(why) => {
                    said.push(format!("{mac} did not take it ({why})"));
                    failed.insert(mac.clone(), json!(why));
                }
            }
        }
        if said.is_empty() {
            return json!({"success": true, "result": true});
        }
        err_with(
            ErrorCode::DeviceFailed,
            &format!("wall: {}", said.join("; ")),
            json!({"result": false, "failed": failed, "degraded": degraded}),
        )
    }
}

impl DivoomWall {
    /// Run `write` on every linked slot at once and record what each did. A
    /// slot with no panel is [`SlotOutcome::Unlinked`] without a write.
    pub(super) async fn each_slot<F, Fut>(&self, write: F) -> WallOutcome
    where
        F: Fn(&DeviceSlot, Arc<DeviceTransport>) -> Fut,
        Fut: Future<Output = Result<(), String>> + Send + 'static,
    {
        let pending: Vec<_> = self
            .devices
            .iter()
            .map(|slot| {
                let task = slot
                    .device
                    .clone()
                    .map(|dev| tokio::spawn(write(slot, dev)));
                (slot.mac.clone(), task)
            })
            .collect();
        let mut out = Vec::with_capacity(pending.len());
        for (mac, task) in pending {
            let outcome = match task {
                None => SlotOutcome::Unlinked,
                Some(task) => match task.await {
                    Ok(Ok(())) => SlotOutcome::Accepted,
                    Ok(Err(why)) => SlotOutcome::Failed(why),
                    Err(e) => SlotOutcome::Failed(format!("the write task died: {e}")),
                },
            };
            out.push((mac, outcome));
        }
        WallOutcome(out)
    }
}
