//! Which panel ids a REAL device has ever reported (D.DV2).
//!
//! Found 2026-10-31 in the owner's own state: four placements
//! `11:22:33:44:55:01`..`04` from an old invented fleet in `topology.json`,
//! and two test macs `AA:00:00:00:00:01`/`BB:00:00:00:00:02` as wall slots in
//! `links.json`. No radio ever answered to any of them -- on this Mac a BLE
//! panel is a `CoreBluetooth` UUID, never a mac -- yet `get_topology` and
//! `list_screens` reported them as offline panels, and every daemon start
//! replayed a wall over them.
//!
//! The class: stored state keyed by a panel id that was WRITTEN, never
//! REPORTED. Any client could put any string in, and nothing took it out.
//!
//! So the owner's stored state admits an id only when a real device has
//! reported it, by one of the two records that only a real report produces:
//!
//! * `discovered_devices.json` -- what a BLE scan found (the GUI keeps it);
//! * the daemon's own `links.json` link list -- every panel a real transport
//!   linked (a mock is never written into the default list: `links.rs`).
//!
//! A `LAN:<ip>` id is admitted when its address is an IP: the user typed it
//! and the connect probed it, and it is not a mac anyone could invent.
//!
//! Every writer of panel-keyed state in the owner's default location asks
//! [`Reported::admits`] (`topology.json`'s placements, `links.json`'s wall
//! slots, the hot-channel verdicts), and the same check runs on LOAD, so the
//! invented entries already on disk are dropped through the same path that
//! keeps new ones out. A store the operator NAMED (an env var) is a test's,
//! and a test double belongs there -- the rule `links.rs` set for mocks.

use serde_json::Value;
use std::collections::HashSet;
use std::path::Path;

/// The ids real devices have reported, lowercased.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Reported {
    ids: HashSet<String>,
}

impl Reported {
    /// Read the two records from the owner's config directory and the
    /// daemon's link list.
    #[must_use]
    pub fn load() -> Self {
        let discovered = crate::cloud::config_dir().map(|d| d.join("discovered_devices.json"));
        let links = crate::links::resolve_location().map(|l| l.path);
        Self::from_files(discovered.as_deref(), links.as_deref())
    }

    /// Read the records at explicit paths (unit-testable).
    #[must_use]
    pub fn from_files(discovered: Option<&Path>, links: Option<&Path>) -> Self {
        let mut ids = HashSet::new();
        if let Some(path) = discovered {
            let list = std::fs::read_to_string(path)
                .ok()
                .and_then(|s| serde_json::from_str::<Value>(&s).ok());
            for entry in list
                .as_ref()
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                if let Some(addr) = entry.get("address").and_then(Value::as_str) {
                    ids.insert(addr.to_ascii_lowercase());
                }
            }
        }
        if let Some(path) = links {
            for link in crate::links::load_from(path).links {
                let mock = link.args.get("mock").and_then(Value::as_bool) == Some(true);
                if !mock {
                    ids.insert(link.id.to_ascii_lowercase());
                }
            }
        }
        Self { ids }
    }

    /// Whether `id` may key the owner's stored state.
    #[must_use]
    pub fn admits(&self, id: &str) -> bool {
        if let Some(ip) = id.strip_prefix("LAN:") {
            return ip.parse::<std::net::IpAddr>().is_ok();
        }
        !id.is_empty() && self.ids.contains(&id.to_ascii_lowercase())
    }

    /// Drop every key of `map` this record does not admit; the dropped keys,
    /// in the map's order.
    pub fn retain_admitted(&self, map: &mut serde_json::Map<String, Value>) -> Vec<String> {
        let dropped: Vec<String> = map.keys().filter(|k| !self.admits(k)).cloned().collect();
        for key in &dropped {
            map.remove(key);
        }
        dropped
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn write(dir: &Path, name: &str, value: &Value) -> std::path::PathBuf {
        let path = dir.join(name);
        std::fs::write(&path, value.to_string()).expect("write");
        path
    }

    #[test]
    fn an_id_a_scan_found_or_a_real_link_made_is_admitted_and_nothing_else() {
        let tmp = tempfile::TempDir::new().unwrap();
        let discovered = write(
            tmp.path(),
            "discovered_devices.json",
            &json!([{"address": "f90d2cc9-420e-65f9-9e06-f9554470fced", "name": "Timoo"}]),
        );
        let links = write(
            tmp.path(),
            "links.json",
            &json!({"links": [
                {"id": "C0:FF:EE:00:00:01", "args": {"mac": "C0:FF:EE:00:00:01"}},
                {"id": "MOCK_A", "args": {"mock": true, "mac": "MOCK_A"}}
            ]}),
        );
        let r = Reported::from_files(Some(&discovered), Some(&links));
        // Scanned, in either case (wall slots are stored upper-cased).
        assert!(r.admits("f90d2cc9-420e-65f9-9e06-f9554470fced"));
        assert!(r.admits("F90D2CC9-420E-65F9-9E06-F9554470FCED"));
        // Linked by a real transport.
        assert!(r.admits("c0:ff:ee:00:00:01"));
        // The owner's invented fleet and test slots: never reported.
        for invented in [
            "11:22:33:44:55:01",
            "AA:00:00:00:00:01",
            "BB:00:00:00:00:02",
        ] {
            assert!(!r.admits(invented), "{invented} must not be admitted");
        }
        // A mock link is a test double, not a report; the wall is no panel.
        assert!(!r.admits("MOCK_A"));
        assert!(!r.admits("MatrixWall"));
        assert!(!r.admits(""));
        // A LAN panel is its IP.
        assert!(r.admits("LAN:192.168.1.40"));
        assert!(!r.admits("LAN:not-an-ip"));
    }

    #[test]
    fn missing_or_corrupt_records_admit_nothing() {
        let tmp = tempfile::TempDir::new().unwrap();
        let bad = tmp.path().join("discovered_devices.json");
        std::fs::write(&bad, "{not json").unwrap();
        let r = Reported::from_files(Some(&bad), Some(&tmp.path().join("absent.json")));
        assert!(!r.admits("f90d2cc9-420e-65f9-9e06-f9554470fced"));
    }

    /// The owner's `links.json` of 2026-10-31: no links (see the scheduler's
    /// fleet-wide disconnect, D.DV2c) and a wall of two test macs. The wall
    /// goes; a wall that keeps a real slot keeps it.
    #[test]
    fn the_test_macs_wall_is_dropped_from_the_owners_links() {
        let tmp = tempfile::TempDir::new().unwrap();
        let discovered = write(
            tmp.path(),
            "discovered_devices.json",
            &json!([{"address": "2b471aee-a9bd-24ab-7d5f-4afd88c16eeb"}]),
        );
        let r = Reported::from_files(Some(&discovered), None);
        let mut state: crate::links::State = serde_json::from_value(json!({
            "links": [],
            "wall": {"cell_size": 16, "slots": {
                "AA:00:00:00:00:01": {"size": 16, "x": 0, "y": 0},
                "BB:00:00:00:00:02": {"size": 16, "x": 1, "y": 0}
            }}
        }))
        .unwrap();
        let dropped = crate::links::drop_unreported_slots(&mut state, &r);
        assert_eq!(dropped.len(), 2, "{dropped:?}");
        assert!(
            state.wall.is_none(),
            "a wall of no reported panel is no wall"
        );

        let mut kept: crate::links::State = serde_json::from_value(json!({
            "wall": {"cell_size": 16, "slots": {
                "2B471AEE-A9BD-24AB-7D5F-4AFD88C16EEB": {"size": 16, "x": 0, "y": 0},
                "AA:00:00:00:00:01": {"size": 16, "x": 1, "y": 0}
            }}
        }))
        .unwrap();
        assert_eq!(
            crate::links::drop_unreported_slots(&mut kept, &r),
            vec!["AA:00:00:00:00:01".to_string()]
        );
        assert_eq!(kept.wall.map(|w| w.slots.len()), Some(1));
    }

    #[test]
    fn retain_drops_exactly_the_unreported_keys() {
        let r = Reported {
            ids: std::iter::once("real".to_string()).collect(),
        };
        let mut map = json!({"real": 1, "11:22:33:44:55:01": 2, "LAN:10.0.0.2": 3})
            .as_object()
            .cloned()
            .unwrap();
        let dropped = r.retain_admitted(&mut map);
        assert_eq!(dropped, vec!["11:22:33:44:55:01".to_string()]);
        assert_eq!(map.len(), 2);
    }
}
