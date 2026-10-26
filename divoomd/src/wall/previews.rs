//! What each wall slot last took, as the GUI draws it on the bench (P6.5).
//!
//! The GUI asks the wall for `get_last_previews` after an image push. The
//! Python wall kept each slot's cut for it; the Rust port dropped the call,
//! so it was refused `unsupported` and the bench's previews were always
//! empty. A preview here is the frames the slicer produced for that slot,
//! encoded (`crate::preview_url`), kept only once the panel took them: a
//! slot whose write failed has no preview rather than one of an image it is
//! not showing.

use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

use serde_json::{json, Value};

/// Each slot's preview of the last image the wall pushed, by slot mac.
#[derive(Debug, Default)]
pub struct Previews(Mutex<BTreeMap<String, String>>);

impl Previews {
    fn slots(&self) -> std::sync::MutexGuard<'_, BTreeMap<String, String>> {
        self.0.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Forget every slot's preview: a new push is starting.
    pub fn clear(&self) {
        self.slots().clear();
    }

    /// `mac` took the frames `url` shows.
    pub fn record(&self, mac: &str, url: String) {
        self.slots().insert(mac.to_string(), url);
    }

    /// The `data:` URL `mac` took in the last push, if it took it.
    #[must_use]
    pub fn get(&self, mac: &str) -> Option<String> {
        self.slots().get(mac).cloned()
    }

    /// `get_last_previews`' reply: `result` maps each slot that took the
    /// last push to a `data:` URL of what it was sent.
    #[must_use]
    pub fn reply(&self) -> Value {
        json!({"success": true, "result": *self.slots()})
    }
}
