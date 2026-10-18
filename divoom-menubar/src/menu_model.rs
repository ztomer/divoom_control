//! What the tray menu shows, as one value, and whether a new one needs the
//! menu REBUILT or only UPDATED IN PLACE (P5.3).
//!
//! Installing a new root `Menu` dismisses it if the user has it open, so a
//! rename, a new widget kind, a moved "Active panel" check or a notification
//! toggle must not install one -- each is an in-place update of an item that
//! already exists. Only a change in WHICH rows exist needs new items, and so a
//! rebuild.
//!
//! The decision diffs one whole signature (`MenuModel`, `PartialEq`), never a
//! per-field dirty flag: a field added to the model is compared without anyone
//! remembering to add a flag for it (house rule 15), and the in-place path in
//! `tray.rs` destructures `MenuModel` and `RowModel` with no `..`, so a field
//! added here does not compile until that path names it (E0027), and a named
//! field it then ignores is an unused binding, which `-D warnings` refuses.

use crate::daemon::DeviceView;

/// One device row: what its submenu title and its "Active panel" check show.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RowModel {
    /// The row's identity. Rows are matched by mac, never by position.
    pub mac: String,
    pub label: String,
    pub selected: bool,
}

/// Everything the menu shows except the tiles (which already update in place
/// from their own cache, every poll).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MenuModel {
    pub rows: Vec<RowModel>,
    pub notif_running: bool,
}

/// What applying a new model to the installed menu takes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MenuChange {
    /// Nothing the menu shows differs.
    Unchanged,
    /// The same rows exist; their labels, checks or the notification items
    /// changed. Applied to the existing items, so an open menu stays open.
    InPlace,
    /// The SET of rows changed (one appeared or went away), or nothing is
    /// installed yet. Needs new items, so a new root menu.
    Rebuild,
}

/// The row title: the panel's name, what it is showing, and whether it is the
/// active panel -- named in the row itself, not only by the check inside its
/// submenu (never one channel).
pub fn row_label(name: &str, kind: &str, selected: bool) -> String {
    let mut label = if kind.is_empty() || kind == "idle" {
        name.to_string()
    } else {
        format!("{name} — {kind}")
    };
    if selected {
        label.push_str(" (active)");
    }
    label
}

impl MenuModel {
    pub fn from_devices(devices: &[DeviceView], notif_running: bool) -> Self {
        Self {
            rows: devices
                .iter()
                .map(|d| RowModel {
                    mac: d.mac.clone(),
                    label: row_label(&d.name, &d.kind, d.selected),
                    selected: d.selected,
                })
                .collect(),
            notif_running,
        }
    }

    /// Which rows exist, independent of order. Order is deliberately not
    /// structure: the polled fleet is sorted by name and the broadcast one is
    /// not, so an order-sensitive key would rebuild (and close the menu)
    /// whenever the two sources alternated, with nothing having changed.
    fn row_set(&self) -> std::collections::BTreeSet<&str> {
        self.rows.iter().map(|r| r.mac.as_str()).collect()
    }

    /// What it takes to go from `installed` (the model the menu was last
    /// built or updated from; `None` before the first build) to `self`.
    pub fn change_from(&self, installed: Option<&Self>) -> MenuChange {
        let Some(prev) = installed else {
            return MenuChange::Rebuild;
        };
        if prev == self {
            MenuChange::Unchanged
        } else if prev.row_set() == self.row_set() {
            MenuChange::InPlace
        } else {
            MenuChange::Rebuild
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dev(mac: &str, name: &str, kind: &str, selected: bool) -> DeviceView {
        DeviceView {
            mac: mac.to_string(),
            name: name.to_string(),
            kind: kind.to_string(),
            preview: None,
            link: Some("active".to_string()),
            selected,
        }
    }

    fn fleet() -> Vec<DeviceView> {
        vec![
            dev("AA", "Desk", "clock", true),
            dev("BB", "Shelf", "idle", false),
        ]
    }

    fn model(devices: &[DeviceView], notif: bool) -> MenuModel {
        MenuModel::from_devices(devices, notif)
    }

    #[test]
    fn nothing_installed_yet_is_a_rebuild() {
        assert_eq!(
            model(&fleet(), false).change_from(None),
            MenuChange::Rebuild
        );
        assert_eq!(model(&[], false).change_from(None), MenuChange::Rebuild);
    }

    #[test]
    fn the_same_fleet_changes_nothing() {
        let installed = model(&fleet(), false);
        assert_eq!(
            model(&fleet(), false).change_from(Some(&installed)),
            MenuChange::Unchanged
        );
    }

    #[test]
    fn a_new_frame_alone_changes_nothing_here() {
        // Tiles are refreshed from their own cache every poll; a frame is not
        // a reason to touch labels, let alone rebuild.
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next[0].preview = Some("data:image/png;base64,AAAA".to_string());
        assert_eq!(
            model(&next, false).change_from(Some(&installed)),
            MenuChange::Unchanged
        );
    }

    #[test]
    fn a_rename_updates_in_place() {
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next[1].name = "Bookshelf".to_string();
        assert_eq!(
            model(&next, false).change_from(Some(&installed)),
            MenuChange::InPlace
        );
    }

    #[test]
    fn a_new_widget_kind_updates_in_place() {
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next[1].kind = "sysmon".to_string();
        assert_eq!(
            model(&next, false).change_from(Some(&installed)),
            MenuChange::InPlace
        );
    }

    #[test]
    fn the_active_panel_moving_updates_in_place() {
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next[0].selected = false;
        next[1].selected = true;
        let m = model(&next, false);
        assert_eq!(m.change_from(Some(&installed)), MenuChange::InPlace);
        // ...and the model carries the moved check, so applying it moves it.
        assert_eq!(
            m.rows.iter().map(|r| r.selected).collect::<Vec<_>>(),
            [false, true]
        );
    }

    #[test]
    fn a_notification_toggle_updates_in_place() {
        let installed = model(&fleet(), false);
        assert_eq!(
            model(&fleet(), true).change_from(Some(&installed)),
            MenuChange::InPlace
        );
    }

    #[test]
    fn a_reorder_of_the_same_rows_does_not_rebuild() {
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next.reverse();
        assert_ne!(
            model(&next, false).change_from(Some(&installed)),
            MenuChange::Rebuild
        );
    }

    #[test]
    fn a_panel_appearing_rebuilds() {
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next.push(dev("CC", "Window", "idle", false));
        assert_eq!(
            model(&next, false).change_from(Some(&installed)),
            MenuChange::Rebuild
        );
    }

    #[test]
    fn a_panel_going_away_rebuilds() {
        let installed = model(&fleet(), false);
        let next = &fleet()[..1];
        assert_eq!(
            model(next, false).change_from(Some(&installed)),
            MenuChange::Rebuild
        );
    }

    #[test]
    fn the_same_count_with_a_different_panel_rebuilds() {
        // A count is not a set: one panel swapped for another needs new items.
        let installed = model(&fleet(), false);
        let mut next = fleet();
        next[1].mac = "CC".to_string();
        assert_eq!(
            model(&next, false).change_from(Some(&installed)),
            MenuChange::Rebuild
        );
    }

    #[test]
    fn the_last_panel_leaving_rebuilds_into_the_empty_row() {
        let installed = model(&fleet(), false);
        assert_eq!(
            model(&[], false).change_from(Some(&installed)),
            MenuChange::Rebuild
        );
    }

    #[test]
    fn labels_name_the_kind_and_the_active_panel() {
        assert_eq!(row_label("Desk", "clock", true), "Desk — clock (active)");
        assert_eq!(row_label("Shelf", "idle", false), "Shelf");
        assert_eq!(row_label("Shelf", "", false), "Shelf");
    }
}
