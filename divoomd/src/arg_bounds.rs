//! Every bounded integer argument, stated once (P4.5).
//!
//! A tool's range lived in up to four places: the MCP schema (`int(0, 15)`),
//! the tool's own check (`need_int(a, "level", 0, 15)`), the CLI verb that
//! shares the tool, and the daemon handler that finally narrows the value to a
//! byte. The verbs' comment said "the bounds come from the MCP tool, not from
//! here" while restating them literally. A [`Bound`] is the one statement: the
//! schema is generated from it, the check reads it, and the daemon handler
//! that receives the value refuses outside it rather than wrapping.

use serde_json::{json, Value};

/// One integer argument: its key and inclusive range.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Bound {
    pub key: &'static str,
    pub lo: i64,
    pub hi: i64,
}

impl Bound {
    const fn new(key: &'static str, lo: i64, hi: i64) -> Self {
        Self { key, lo, hi }
    }

    /// The JSON-schema property for this argument.
    #[must_use]
    pub fn schema(&self) -> Value {
        json!({ "type": "integer", "minimum": self.lo, "maximum": self.hi })
    }

    /// `v`, when it is in range.
    ///
    /// # Errors
    ///
    /// Outside the range; the message names the key and the range.
    pub fn check(&self, v: i64) -> Result<i64, String> {
        if v < self.lo || v > self.hi {
            return Err(format!(
                "{} must be in [{}..{}] (got {v})",
                self.key, self.lo, self.hi
            ));
        }
        Ok(v)
    }

    /// The argument out of a call's arguments, required.
    ///
    /// # Errors
    ///
    /// Missing, not an integer, or out of range -- each message names the key.
    pub fn read(&self, a: &Value) -> Result<i64, String> {
        let v = a
            .get(self.key)
            .and_then(Value::as_i64)
            .ok_or_else(|| format!("{} must be an integer", self.key))?;
        self.check(v)
    }

    /// The argument out of a call's arguments, `default` when absent or null.
    ///
    /// # Errors
    ///
    /// Present but not an integer, or out of range.
    pub fn read_or(&self, a: &Value, default: i64) -> Result<i64, String> {
        match a.get(self.key) {
            None | Some(Value::Null) => Ok(default),
            Some(_) => self.read(a),
        }
    }
}

/// Speaker volume.
pub const VOLUME: Bound = Bound::new("level", 0, 15);
/// Display brightness, percent.
pub const BRIGHTNESS: Bound = Bound::new("level", 0, 100);
/// FM frequency in tenths of a MHz (87.5..108.0).
pub const RADIO_FREQ_X10: Bound = Bound::new("freq_x10", 875, 1080);
/// The weather widget's temperature, whole degrees C.
pub const TEMPERATURE_C: Bound = Bound::new("temperature_c", -127, 128);
/// Which of the ten alarms.
pub const ALARM_INDEX: Bound = Bound::new("index", 0, 9);
/// Hour of day, 24h.
pub const HOUR: Bound = Bound::new("hour", 0, 23);
/// Minute of the hour.
pub const MINUTE: Bound = Bound::new("minute", 0, 59);
/// Alarm weekday bitmask, bit 0 = Sunday.
pub const WEEKDAY_MASK: Bound = Bound::new("weekday_mask", 0, 127);
/// Screen rotation, degrees (a multiple of 90, checked separately).
pub const DEGREES: Bound = Bound::new("degrees", 0, 270);
/// A beep's length.
pub const SOUND_MS: Bound = Bound::new("duration_ms", 100, 3000);
/// An image's edge when the panel's own is unknown.
pub const IMAGE_SIZE: Bound = Bound::new("size", 8, 128);
/// Scoreboard scores: three digits on the panel, as the GUI's inputs allow.
pub const RED_SCORE: Bound = Bound::new("red_score", 0, 999);
/// See [`RED_SCORE`].
pub const BLUE_SCORE: Bound = Bound::new("blue_score", 0, 999);
/// Countdown minutes: two digits on the panel, as the GUI's input allows.
pub const COUNTDOWN_MINUTES: Bound = Bound::new("minutes", 0, 99);
/// Countdown seconds.
pub const COUNTDOWN_SECONDS: Bound = Bound::new("seconds", 0, 59);
/// A screen lease's time to live, ms: mandatory, at least a second, at most
/// ten minutes -- a crashed holder gives the screen back within that.
pub const LEASE_TTL_MS: Bound = Bound::new("ttl_ms", 1_000, 600_000);
