//! A panel's screen lease and the frame it hands back (P4.6).
//!
//! State only -- one lease and one saved frame per [`Device`], as the
//! per-device rule asks. Acquiring, renewing and ending a lease, and what the
//! queue does about it, live in `crate::lease`.

use std::sync::atomic::Ordering;
use std::time::Instant;

use super::Device;

/// One holder's claim on a panel's screen.
#[derive(Clone, Debug)]
pub struct Lease {
    /// The bearer token every leased call carries.
    pub token: String,
    /// Who asked, for the refusal another caller sees.
    pub holder: String,
    /// When it ends unless renewed.
    pub expires: Instant,
    /// Distinguishes this lease from a later one with the same token slot,
    /// so a stale expiry watcher can never end its successor.
    pub generation: u64,
}

/// A frame as the live job rendered it, kept to repaint the screen with.
#[derive(Clone, Debug)]
pub struct SavedFrame {
    pub rgb: Vec<u8>,
    pub w: i32,
    pub h: i32,
    pub time_ms: u16,
}

fn lock<T>(m: &std::sync::Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
}

impl Device {
    /// The current lease, if one is held.
    #[must_use]
    pub fn lease(&self) -> Option<Lease> {
        lock(&self.lease).clone()
    }

    /// Whether `token` is this panel's lease.
    #[must_use]
    pub fn leased_to(&self, token: &str) -> bool {
        lock(&self.lease).as_ref().is_some_and(|l| l.token == token)
    }

    pub(crate) fn set_lease(&self, lease: Lease) {
        *lock(&self.lease) = Some(lease);
    }

    /// Move the lease's end, if `token` still holds it.
    pub(crate) fn extend_lease(&self, token: &str, expires: Instant) -> bool {
        let mut g = lock(&self.lease);
        match g.as_mut() {
            Some(l) if l.token == token => {
                l.expires = expires;
                true
            }
            _ => false,
        }
    }

    /// Take the lease if it is still generation `generation`.
    pub(crate) fn take_lease(&self, generation: u64) -> Option<Lease> {
        let mut g = lock(&self.lease);
        if g.as_ref().is_some_and(|l| l.generation == generation) {
            g.take()
        } else {
            None
        }
    }

    pub(crate) fn save_job_frame(&self, frame: SavedFrame) {
        *lock(&self.job_frame) = Some(frame);
    }

    pub(crate) fn clear_job_frame(&self) {
        *lock(&self.job_frame) = None;
    }

    #[must_use]
    pub fn job_frame(&self) -> Option<SavedFrame> {
        lock(&self.job_frame).clone()
    }

    /// Claim the next frame-push slot; the returned number is this push's.
    pub(crate) fn next_frame_gen(&self) -> u64 {
        self.frame_gen.fetch_add(1, Ordering::SeqCst) + 1
    }

    /// Whether push `gen` is still the newest one.
    #[must_use]
    pub fn is_newest_frame(&self, gen: u64) -> bool {
        self.frame_gen.load(Ordering::SeqCst) == gen
    }
}
