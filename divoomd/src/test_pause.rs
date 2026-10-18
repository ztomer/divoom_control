//! A place a test can park production code, to force one interleaving
//! instead of hoping a scheduler produces it (P5.9).
//!
//! The code under test calls [`PausePoint::wait_if_armed`] at the point a
//! race lives; it is a no-op unless a test armed it. [`PausePoint::arm`]
//! hands the test two ends: one that resolves when the code has parked, one
//! that lets it go on.

use tokio::sync::oneshot;

struct Pause {
    reached: oneshot::Sender<()>,
    resume: oneshot::Receiver<()>,
}

#[derive(Default)]
pub struct PausePoint(std::sync::Mutex<Option<Pause>>);

impl PausePoint {
    pub const fn new() -> Self {
        Self(std::sync::Mutex::new(None))
    }

    /// Park the next pass through this point. Returns (parked, resume).
    pub fn arm(&self) -> (oneshot::Receiver<()>, oneshot::Sender<()>) {
        let (reached, parked) = oneshot::channel();
        let (go, resume) = oneshot::channel();
        *self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(Pause { reached, resume });
        (parked, go)
    }

    pub async fn wait_if_armed(&self) {
        let pause = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        if let Some(p) = pause {
            let _ = p.reached.send(());
            let _ = p.resume.await;
        }
    }
}
