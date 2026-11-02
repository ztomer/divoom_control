//! The menu items that change WITHOUT a rebuild, and the two functions that
//! change them. Shared by the poll (`tray`) and by the refresh an open menu
//! runs while it is tracking (`menu_live`, D.MENULIVE), so both apply one
//! model the same way.

use std::cell::RefCell;
use std::collections::HashMap;

use tray_icon::menu::{CheckMenuItem, MenuItem, Submenu};

use crate::daemon;
use crate::menu_model::{MenuModel, RowModel};

/// The items of one device row that change without a rebuild.
pub struct RowItems {
    pub submenu: Submenu,
    pub active: CheckMenuItem,
}

/// The notification items, whose enabled state follows the monitor.
pub struct NotifItems {
    pub start: MenuItem,
    pub stop: MenuItem,
}

/// Apply `model` to the existing items. Both patterns name every field with
/// no `..`: a field added to the model does not compile until it is named
/// here (E0027), and one named but not applied is an unused binding.
pub fn apply_in_place(
    rows: &RefCell<HashMap<String, RowItems>>,
    notif: &RefCell<Option<NotifItems>>,
    model: &MenuModel,
) {
    let MenuModel {
        rows: row_models,
        notif_running,
    } = model;
    let rows = rows.borrow();
    for RowModel {
        mac,
        label,
        selected,
    } in row_models
    {
        if let Some(items) = rows.get(mac) {
            items.submenu.set_text(label);
            items.active.set_checked(*selected);
            items.active.set_enabled(!*selected);
        }
    }
    if let Some(notif) = notif.borrow().as_ref() {
        notif.start.set_enabled(!*notif_running);
        notif.stop.set_enabled(*notif_running);
    }
}

/// Refresh the row tiles from new frames, in place.
pub fn refresh_tiles(
    rows: &RefCell<HashMap<String, RowItems>>,
    tiles: &RefCell<crate::tiles::TileCache>,
    devices: &[daemon::DeviceView],
) {
    let rows = rows.borrow();
    for d in devices {
        if let Some(items) = rows.get(&d.mac) {
            items
                .submenu
                .set_icon(tiles.borrow_mut().icon_for(d.preview.as_deref()));
        }
    }
}
