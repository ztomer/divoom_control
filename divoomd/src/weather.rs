//! Weather: one WMO mapping, one fetch, one place.
//!
//! # Why this module exists (R67, class C2)
//!
//! Weather was implemented twice — `divoom_lib/weather_provider.py` for the
//! GUI's preview card and an inline block in the daemon's live job for the
//! device push. Same class as the now-playing duplication: what the user sees
//! and what reaches the panel came from different code that could disagree.
//!
//! Unlike now-playing, this pair had NOT yet drifted: the two WMO tables were
//! diffed on 2026-08-29 and agree on all 48 codes. So the risk here is latent,
//! not active, and the fix is proportionate — extract the mapping into DATA
//! that a gate can compare against Python's (`tools/check_weather_parity.py`),
//! rather than rewrite a working fetch on both sides.
//!
//! Source is wttr.in's `?format=j1`, whose `weatherCode` values are WWO codes
//! (not raw WMO); the table below is keyed on exactly what that API returns.

use crate::packets::WeatherType;

/// WWO/wttr weather code -> Divoom icon.
///
/// DATA, not a `match`, so `tools/check_weather_parity.py` can read it and
/// compare against `divoom_lib/weather_provider.WEATHER_CODE_TO_DIVOOM`. A
/// `match` arm is invisible to any checker and is how the two halves would
/// eventually drift apart unnoticed.
///
/// Keep sorted by code — the gate reports differences by code, and a sorted
/// table makes a diff readable.
pub const WEATHER_CODE_TO_DIVOOM: &[(i32, WeatherType)] = &[
    (113, WeatherType::Clear),
    (116, WeatherType::CloudySky),
    (119, WeatherType::CloudySky),
    (122, WeatherType::CloudySky),
    (143, WeatherType::Fog),
    (176, WeatherType::Rain),
    (179, WeatherType::Snow),
    (182, WeatherType::Snow),
    (185, WeatherType::Fog),
    (200, WeatherType::Thunderstorm),
    (227, WeatherType::Snow),
    (230, WeatherType::Snow),
    (248, WeatherType::Fog),
    (260, WeatherType::Fog),
    (263, WeatherType::Rain),
    (266, WeatherType::Rain),
    (281, WeatherType::Rain),
    (284, WeatherType::Rain),
    (293, WeatherType::Rain),
    (296, WeatherType::Rain),
    (299, WeatherType::Rain),
    (302, WeatherType::Rain),
    (305, WeatherType::Rain),
    (308, WeatherType::Rain),
    (311, WeatherType::Rain),
    (314, WeatherType::Rain),
    (317, WeatherType::Snow),
    (320, WeatherType::Snow),
    (323, WeatherType::Snow),
    (326, WeatherType::Snow),
    (329, WeatherType::Snow),
    (332, WeatherType::Snow),
    (335, WeatherType::Snow),
    (338, WeatherType::Snow),
    (350, WeatherType::Snow),
    (353, WeatherType::Rain),
    (356, WeatherType::Rain),
    (359, WeatherType::Rain),
    (362, WeatherType::Snow),
    (365, WeatherType::Snow),
    (368, WeatherType::Snow),
    (371, WeatherType::Snow),
    (374, WeatherType::Snow),
    (377, WeatherType::Snow),
    (386, WeatherType::Thunderstorm),
    (389, WeatherType::Thunderstorm),
    (392, WeatherType::Thunderstorm),
    (395, WeatherType::Thunderstorm),
];

/// Map a weather code to an icon.
///
/// Unknown codes fall back to `Clear`: it is the neutral icon, and showing a
/// thunderstorm for a code we do not recognise would be worse than showing
/// nothing interesting.
#[must_use]
pub fn code_to_type(code: i32) -> WeatherType {
    WEATHER_CODE_TO_DIVOOM
        .iter()
        .find(|(c, _)| *c == code)
        .map_or(WeatherType::Clear, |(_, t)| *t)
}

/// A weather reading.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WeatherInfo {
    pub temperature_c: i8,
    pub weather: WeatherType,
    /// The city wttr.in resolved — from `nearest_area`, NOT the request.
    /// Empty only when the response carries no area (or a caller built the
    /// struct by hand). The GUI used to render a hardcoded "here" whenever
    /// the daemon echoed the request's (empty) location back; that fallback
    /// chain ends here instead.
    pub location: String,
}

/// Parse wttr.in's `?format=j1` response.
///
/// Split from the HTTP call so the response shape is testable without a
/// network — including the detail that wttr returns its numbers as STRINGS.
#[must_use]
pub fn parse_wttr(body: &serde_json::Value) -> Option<WeatherInfo> {
    let current = body
        .get("current_condition")
        .and_then(|c| c.as_array())
        .and_then(|a| a.first())?;
    // Both fields are strings in this API, not numbers.
    let temp_c = current
        .get("temp_C")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<i8>().ok())?;
    let code = current
        .get("weatherCode")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<i32>().ok())
        .unwrap_or(113);
    // The resolved city: wttr.in geolocates an empty request by IP and
    // reports what it picked here. Absent (a hand-built fixture, an odd
    // provider response) means unknown, never a placeholder.
    let location = body
        .get("nearest_area")
        .and_then(|a| a.as_array())
        .and_then(|a| a.first())
        .and_then(|area| area.get("areaName"))
        .and_then(|n| n.as_array())
        .and_then(|n| n.first())
        .and_then(|n| n.get("value"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    Some(WeatherInfo {
        temperature_c: temp_c,
        weather: code_to_type(code),
        location,
    })
}

/// Fetch the current weather. Empty `location` lets wttr.in geolocate by IP.
///
/// # Errors
///
/// When the weather service cannot be reached, returns a non-2xx status, or
/// answers a body with no current condition in it.
pub async fn fetch(client: &reqwest::Client, location: &str) -> Result<WeatherInfo, String> {
    let mut url = "https://wttr.in/".to_string();
    url.push_str(location);
    let resp = client
        .get(&url)
        .query(&[("format", "j1")])
        .timeout(std::time::Duration::from_secs(8))
        .send()
        .await
        .map_err(|e| format!("wttr.in request failed: {e}"))?;
    if resp.status() != 200 {
        return Err(format!("wttr.in returned {}", resp.status()));
    }
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("wttr.in returned unparseable JSON: {e}"))?;
    parse_wttr(&body).ok_or_else(|| "wttr.in response had no current_condition".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_a_wttr_response() {
        // wttr returns NUMBERS AS STRINGS; parsing them as numbers yields None
        // and the whole reading silently disappears.
        let body = json!({"current_condition": [{"temp_C": "21", "weatherCode": "296"}]});
        let info = parse_wttr(&body).expect("a reading");
        assert_eq!(info.temperature_c, 21);
        assert_eq!(info.weather, WeatherType::Rain);
    }

    #[test]
    fn parses_the_resolved_city_from_nearest_area() {
        // The GUI rendered a hardcoded "here" because the daemon echoed the
        // request's (empty) location instead of the city wttr.in resolved.
        // An explicit area wins at the caller; the parse reports the rest.
        let body = json!({
            "current_condition": [{"temp_C": "21", "weatherCode": "113"}],
            "nearest_area": [{"areaName": [{"value": "Tel Aviv"}]}],
        });
        let info = parse_wttr(&body).expect("a reading");
        assert_eq!(info.location, "Tel Aviv");
    }

    #[test]
    fn a_missing_area_is_unknown_not_a_placeholder() {
        let body = json!({"current_condition": [{"temp_C": "21", "weatherCode": "113"}]});
        let info = parse_wttr(&body).expect("a reading");
        assert_eq!(info.location, "");
    }

    #[test]
    fn parses_a_negative_temperature() {
        let body = json!({"current_condition": [{"temp_C": "-7", "weatherCode": "338"}]});
        let info = parse_wttr(&body).expect("a reading");
        assert_eq!(info.temperature_c, -7);
        assert_eq!(info.weather, WeatherType::Snow);
    }

    #[test]
    fn an_unknown_code_falls_back_to_clear_not_to_nothing() {
        let body = json!({"current_condition": [{"temp_C": "10", "weatherCode": "9999"}]});
        assert_eq!(parse_wttr(&body).unwrap().weather, WeatherType::Clear);
    }

    #[test]
    fn a_missing_code_still_yields_a_reading() {
        // Temperature is the useful half; losing it because the icon is absent
        // would be the wrong trade.
        let body = json!({"current_condition": [{"temp_C": "3"}]});
        let info = parse_wttr(&body).expect("a reading");
        assert_eq!(info.temperature_c, 3);
        assert_eq!(info.weather, WeatherType::Clear);
    }

    #[test]
    fn a_missing_temperature_is_no_reading() {
        let body = json!({"current_condition": [{"weatherCode": "113"}]});
        assert!(parse_wttr(&body).is_none());
    }

    #[test]
    fn garbage_never_panics() {
        for body in [
            json!(null),
            json!({}),
            json!({"current_condition": []}),
            json!({"current_condition": "nope"}),
        ] {
            assert!(parse_wttr(&body).is_none());
        }
    }

    #[test]
    fn the_table_is_sorted_and_has_no_duplicates() {
        // The parity gate diffs by code; an unsorted or duplicated table makes
        // its output unreadable and its lookup ambiguous.
        let codes: Vec<i32> = WEATHER_CODE_TO_DIVOOM.iter().map(|(c, _)| *c).collect();
        let mut sorted = codes.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(
            codes, sorted,
            "table must be sorted with no duplicate codes"
        );
    }

    #[test]
    fn every_documented_code_maps() {
        assert_eq!(
            WEATHER_CODE_TO_DIVOOM.len(),
            48,
            "48 codes, matching Python"
        );
    }
}
