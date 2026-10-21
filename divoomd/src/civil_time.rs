//! Unix seconds → a calendar date, without a date-time crate.
//!
//! The hot-channel loop has to write down WHEN it fetched a gallery and WHEN
//! each of the gallery's files was made, because the open question — is the
//! "monthly best" category a sliding window? — is answered by diffing two
//! dated snapshots, not by a belief. The crate has no time dependency and the
//! estate does not want one added for a date string, so the conversion is
//! here: Howard Hinnant's `civil_from_days`, which is exact for the whole
//! proleptic Gregorian range we care about.

use std::time::{SystemTime, UNIX_EPOCH};

/// Now, in unix seconds.
#[must_use]
pub fn unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

/// The date part of a unix timestamp: `YYYY-MM-DD` (UTC).
#[must_use]
pub fn iso_date(unix_secs: u64) -> String {
    let (year, month, day) = civil_from_days(days_from_civil_epoch(unix_secs));
    format!("{year:04}-{month:02}-{day:02}")
}

/// A whole timestamp: `YYYY-MM-DDTHH:MM:SSZ` (UTC).
#[must_use]
pub fn iso_timestamp(unix_secs: u64) -> String {
    let (year, month, day) = civil_from_days(days_from_civil_epoch(unix_secs));
    let rest = unix_secs % 86_400;
    let (hour, minute, second) = (rest / 3600, (rest % 3600) / 60, rest % 60);
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// The day number (days since 1970-01-01) a unix timestamp falls on.
fn days_from_civil_epoch(unix_secs: u64) -> i64 {
    let days = unix_secs / 86_400;
    i64::try_from(days).unwrap_or(i64::MAX)
}

/// Days since the epoch → (year, month, day).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097).cast_unsigned(); // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = i64::try_from(yoe).unwrap_or(0) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let year = if m <= 2 { y + 1 } else { y };
    (
        year,
        u32::try_from(m).unwrap_or(1),
        u32::try_from(d).unwrap_or(1),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_epoch_is_the_epoch() {
        assert_eq!(iso_date(0), "1970-01-01");
        assert_eq!(iso_timestamp(0), "1970-01-01T00:00:00Z");
    }

    #[test]
    fn a_known_date_is_the_date_the_calendar_says() {
        // 2026-02-16T07:04:56Z
        assert_eq!(iso_timestamp(1_771_225_496), "2026-02-16T07:04:56Z");
    }

    #[test]
    fn a_leap_day_is_a_leap_day() {
        // 2024-02-29T00:00:00Z
        assert_eq!(iso_date(1_709_164_800), "2024-02-29");
    }
}
