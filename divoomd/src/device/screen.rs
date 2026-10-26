//! What a panel's screen shows, as the daemon last put it there (WG.5a).
//!
//! State only -- one record per [`Device`]. The record is written by the code
//! that WROTE to the panel, at the moment the write landed, and it holds the
//! frames that code encoded and streamed: the same pixels, never a second
//! rendering of the source (`crate::preview_url` turns them into a `data:`
//! URL). A write the daemon holds no pixels for -- a channel the panel draws
//! itself, a pre-encoded blob, a gallery page -- replaces the record with a
//! state that says so, so an older frame can never be shown as the current
//! one. The reply that reads it is `crate::screen_previews`.

use std::sync::{Mutex, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use super::Device;
use crate::image_proc::Frame;

/// What the screen shows.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Shown {
    /// Frames the daemon encoded and streamed, as a `data:` URL (a PNG for
    /// one frame, a looping GIF for several) and the frames' own size.
    Frame {
        data_url: String,
        width: i32,
        height: i32,
        frames: usize,
    },
    /// The panel draws this itself from a command (a clock, a light, text, a
    /// stored design or gallery page): the daemon has no pixels for it.
    DeviceRendered,
    /// The daemon streamed bytes it did not decode (a pre-encoded animation),
    /// so it cannot say which pixels they are.
    Undecoded,
}

/// The last thing the daemon put on a panel, by whom, and when.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Screen {
    pub shown: Shown,
    /// What wrote it: a live job's kind or a `device_call` method.
    pub source: String,
    /// Milliseconds since the Unix epoch.
    pub at_ms: u64,
}

/// Milliseconds since the Unix epoch, now.
#[must_use]
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX))
}

impl Screen {
    /// A record of `frames` as `source` streamed them; [`Shown::Undecoded`]
    /// when there are none or they cannot be encoded, because a record that
    /// claims a frame must carry one.
    #[must_use]
    pub fn of_frames(source: &str, frames: &[Frame]) -> Self {
        let shown = match (frames.first(), crate::preview_url::data_url(frames)) {
            (Some((_, w, h, _)), Some(data_url)) => Shown::Frame {
                data_url,
                width: *w,
                height: *h,
                frames: frames.len(),
            },
            _ => Shown::Undecoded,
        };
        Self::new(source, shown)
    }

    /// A record of `data_url`, already encoded from the frames that landed.
    #[must_use]
    pub fn of_url(source: &str, data_url: Option<String>, width: i32, height: i32) -> Self {
        let shown = data_url.map_or(Shown::Undecoded, |data_url| Shown::Frame {
            data_url,
            width,
            height,
            frames: 1,
        });
        Self::new(source, shown)
    }

    #[must_use]
    pub fn new(source: &str, shown: Shown) -> Self {
        Self {
            shown,
            source: source.to_string(),
            at_ms: now_ms(),
        }
    }
}

/// Where a `device_call` handler leaves the frames it streamed, for the
/// caller to record once the call has succeeded.
#[derive(Debug, Default)]
pub struct Sink(Mutex<Option<Vec<Frame>>>);

impl Sink {
    /// These frames reached the panel.
    pub fn put(&self, frames: Vec<Frame>) {
        *self.0.lock().unwrap_or_else(PoisonError::into_inner) = Some(frames);
    }

    /// The frames a handler left, if any.
    #[must_use]
    pub fn take(&self) -> Option<Vec<Frame>> {
        self.0.lock().unwrap_or_else(PoisonError::into_inner).take()
    }
}

impl Device {
    fn screen_cell(&self) -> std::sync::MutexGuard<'_, Option<Screen>> {
        self.screen.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The panel now shows `screen`.
    pub(crate) fn record_screen(&self, screen: Screen) {
        *self.screen_cell() = Some(screen);
    }

    /// Nothing the daemon sent is known to be on the screen any more (a new
    /// link: the panel may have been power-cycled or used by the vendor app).
    pub(crate) fn clear_screen(&self) {
        *self.screen_cell() = None;
    }

    /// The last record, if the daemon has put anything on the screen.
    #[must_use]
    pub fn screen(&self) -> Option<Screen> {
        self.screen_cell().clone()
    }
}
