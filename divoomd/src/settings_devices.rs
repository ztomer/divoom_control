//! The devices the app's OWN settings register, and the gallery each one wants.
//!
//! # One home for the fact
//!
//! The hot-channel loop used to carry its own list of devices
//! (`hotchannel.json` → `targets`) and its own per-device gallery
//! (`device_galleries`). That list was EMPTY: the loop was enabled, it was
//! scheduled, and it fetched nothing and pushed nothing, for 36 days, with
//! nothing in the log to say so. Meanwhile the app's settings already knew
//! the devices — `config.ini`'s `[gallery]` table is keyed by device address
//! and holds the gallery classify that device wants.
//!
//! So the fact lives in ONE place: the settings table. The loop reads it, the
//! GUI writes it, and there is no second list to fill and no second list to
//! drift. `hotchannel.json` keeps what is genuinely the LOOP's own — whether
//! it runs, and how often.
//!
//! # The table's shape
//!
//! ```ini
//! [gallery]
//! f90d2cc9-420e-65f9-9e06-f9554470fced = 18
//! a9fccb71-3d3d-4de3-c381-0de382cdc4aa = 17
//! gallery_sort = 1
//! gallery_file_size = 1
//! ```
//!
//! A key that is a device address is a device. `RESERVED_KEYS` are the
//! table's own settings, not devices. Anything else is a FINDING: the
//! settings name something the loop cannot resolve, and the loop says so
//! rather than skipping it in silence — a device whose name is wrong must be
//! a failure, not a no-op.

use std::path::PathBuf;

/// The gallery the loop falls back to when the settings name none for a
/// device: the cloud's own default ("Recommend", classify 18).
pub const DEFAULT_CLASSIFY: i64 = crate::cloud::DEFAULT_GALLERY_CLASSIFY;

/// The `[gallery]` table's own keys — settings, NOT devices.
///
/// `default` is the fallback classify for devices with no entry of their own;
/// the other two are the gallery view's sort order and file-size filter. They
/// live in the same table because they are the same subject (how the gallery
/// is browsed), and they are listed here so the loop does not try to CONNECT
/// to them.
pub const RESERVED_KEYS: &[&str] = &["default", "gallery_sort", "gallery_file_size"];

/// A device the app's settings register, with the gallery it wants.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegisteredDevice {
    /// The device address the daemon connects to — what the table is keyed by.
    pub address: String,
    /// The cloud gallery classify this device wants (18 = the cloud's own
    /// "Recommend" gallery, which is what the owner calls "monthly best").
    pub classify: i64,
}

/// What the settings table said.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GallerySettings {
    /// The devices the settings register, in the order the table lists them.
    pub devices: Vec<RegisteredDevice>,
    /// Entries that are neither a device nor a known setting: the key and the
    /// raw value. These are findings, not noise — the loop fails on them.
    pub broken: Vec<(String, String)>,
}

impl GallerySettings {
    /// The devices, and nothing else.
    #[must_use]
    pub fn addresses(&self) -> Vec<String> {
        self.devices.iter().map(|d| d.address.clone()).collect()
    }
}

/// `config.ini`, where the app's settings live.
#[must_use]
pub fn config_ini_path() -> Option<PathBuf> {
    Some(crate::cloud::config_dir()?.join("config.ini"))
}

/// The devices the app's settings register, read from `config.ini`.
///
/// A missing or unreadable file is an EMPTY table, not an error: the caller
/// (the loop) turns "no devices" into a loud failure, which is the truth the
/// owner needs — a settings file that cannot be read must not look like a
/// settings file that registers nothing.
#[must_use]
pub fn registered_devices() -> GallerySettings {
    let Some(path) = config_ini_path() else {
        return GallerySettings::default();
    };
    let Ok(text) = std::fs::read_to_string(&path) else {
        return GallerySettings::default();
    };
    parse_gallery_table(&text)
}

/// Parse the `[gallery]` table out of an INI document.
///
/// Pure: the file is read by the caller, so this can be pinned by tests
/// without a home directory.
#[must_use]
pub fn parse_gallery_table(text: &str) -> GallerySettings {
    let mut entries: Vec<(String, String)> = Vec::new();
    let mut in_gallery = false;

    for raw_line in text.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
            continue;
        }
        if let Some(name) = section_name(line) {
            in_gallery = name.eq_ignore_ascii_case("gallery");
            continue;
        }
        if !in_gallery {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() {
            continue;
        }
        entries.push((key.to_string(), value.trim().to_string()));
    }

    let fallback = entries
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case("default"))
        .and_then(|(_, value)| value.parse::<i64>().ok())
        .unwrap_or(DEFAULT_CLASSIFY);

    let mut devices = Vec::new();
    let mut broken = Vec::new();
    for (key, value) in entries {
        if RESERVED_KEYS
            .iter()
            .any(|reserved| reserved.eq_ignore_ascii_case(&key))
        {
            continue;
        }
        if !looks_like_address(&key) {
            broken.push((key, value));
            continue;
        }
        let classify = match value.parse::<i64>() {
            Ok(c) if c > 0 => c,
            _ => fallback,
        };
        devices.push(RegisteredDevice {
            address: key,
            classify,
        });
    }

    GallerySettings { devices, broken }
}

/// The section a header line names, if the line is a header.
fn section_name(line: &str) -> Option<&str> {
    let inner = line.strip_prefix('[')?.strip_suffix(']')?;
    Some(inner.trim())
}

/// Whether a `[gallery]` key names a device the daemon can connect to.
///
/// The settings' table is keyed by device address: the UUID-shaped id the
/// iOS-LE protocol uses (what the daemon's scan reports), a MAC, or a `LAN:`
/// address. Anything else is not a device — it is a setting the loop cannot
/// use, and the loop says so instead of skipping it in silence.
///
/// The shape: hex digits and separators only, with at least one separator
/// (every address this estate has carries one — dashes in the UUID form,
/// colons in the MAC form) and at least four hex digits. `gallery_sort` and
/// `gallery_file_size` fail on the characters alone.
#[must_use]
pub fn looks_like_address(key: &str) -> bool {
    if key.is_empty() || key.chars().any(char::is_whitespace) {
        return false;
    }
    if let Some(ip) = key.strip_prefix("LAN:") {
        // A dotted quad: four groups of digits.
        let groups: Vec<&str> = ip.split('.').collect();
        return groups.len() == 4
            && groups
                .iter()
                .all(|g| !g.is_empty() && g.chars().all(|c| c.is_ascii_digit()));
    }
    let hex_digits = key.chars().filter(char::is_ascii_hexdigit).count();
    let separators = key.chars().filter(|c| *c == '-' || *c == ':').count();
    hex_digits >= 4 && separators >= 1 && hex_digits + separators == key.len() && key.len() <= 38
}

#[cfg(test)]
mod tests {
    use super::*;

    const SETTINGS: &str = "\
[gui]
timeout = 120

[gallery]
f90d2cc9-420e-65f9-9e06-f9554470fced = 18
e9a41e1e-9a96-974f-ce44-54f16d616f28 = 18
2b471aee-a9bd-24ab-7d5f-4afd88c16eeb = 18
a9fccb71-3d3d-4de3-c381-0de382cdc4aa = 17
gallery_sort = 1
gallery_file_size = 1
";

    #[test]
    fn the_settings_table_names_the_devices_and_their_gallery() {
        let settings = parse_gallery_table(SETTINGS);
        assert_eq!(
            settings.addresses(),
            vec![
                "f90d2cc9-420e-65f9-9e06-f9554470fced",
                "e9a41e1e-9a96-974f-ce44-54f16d616f28",
                "2b471aee-a9bd-24ab-7d5f-4afd88c16eeb",
                "a9fccb71-3d3d-4de3-c381-0de382cdc4aa",
            ]
        );
        assert_eq!(settings.devices[3].classify, 17);
        assert_eq!(settings.devices[0].classify, 18);
        assert_eq!(settings.broken.len(), 0);
    }

    #[test]
    fn the_tables_own_settings_are_not_devices() {
        let settings = parse_gallery_table(SETTINGS);
        // gallery_sort and gallery_file_size would be pushed to as devices if
        // the reserved set were not honoured.
        assert!(!settings.addresses().iter().any(|a| a.contains("gallery_")));
    }

    #[test]
    fn a_key_the_loop_cannot_resolve_is_a_finding_not_a_skip() {
        let settings = parse_gallery_table("[gallery]\nTimoo-light-4 = 18\n");
        assert_eq!(settings.devices.len(), 0);
        assert_eq!(
            settings.broken,
            vec![("Timoo-light-4".to_string(), "18".to_string())]
        );
    }

    #[test]
    fn a_device_without_a_usable_gallery_falls_back_to_the_default() {
        let settings = parse_gallery_table(
            "[gallery]\ndefault = 17\na9fccb71-3d3d-4de3-c381-0de382cdc4aa = oops\n",
        );
        assert_eq!(settings.devices.len(), 1);
        assert_eq!(settings.devices[0].classify, 17);
    }

    #[test]
    fn the_table_outside_the_gallery_section_is_not_read() {
        let settings = parse_gallery_table(
            "[gui]\nlast_connected_device = a9fccb71-3d3d-4de3-c381-0de382cdc4aa\n",
        );
        assert_eq!(settings.devices.len(), 0);
    }

    #[test]
    fn a_lan_address_is_a_device() {
        assert!(looks_like_address("LAN:192.168.1.50"));
        assert!(!looks_like_address("LAN:"));
        assert!(!looks_like_address("gallery_sort"));
    }

    /// The same cases the Python side pins (`tests/test_settings_devices.py`):
    /// two readers of one table, so the table's cases live in both.
    #[test]
    fn the_address_rule_is_the_same_case_for_case() {
        let cases = [
            ("f90d2cc9-420e-65f9-9e06-f9554470fced", true),
            ("AA:BB:CC:DD:EE:FF", true),
            ("AA:00:00:00:00:01", true),
            ("LAN:192.168.1.50", true),
            ("gallery_sort", false),
            ("gallery_file_size", false),
            ("default", false),
            ("Timoo-light-4", false),
            ("", false),
            ("AA BB", false),
        ];
        for (key, expected) in cases {
            assert_eq!(looks_like_address(key), expected, "address rule: {key}");
        }
    }
}
