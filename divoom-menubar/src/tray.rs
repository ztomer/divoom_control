//! The tray/menubar itself: a status-coloured glyph + a menu that mirrors the
//! pyobjc menubar (Launch Dashboard / Open Notifications / Start+Stop
//! Notifications / Quit) plus a read-only active-device section. State is refreshed
//! by polling the daemon (`poll_daemon`); menu clicks are dispatched in `on_menu`.

use std::time::Duration;
use tray_icon::menu::{
    CheckMenuItem, Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem, Submenu,
};
use tray_icon::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};

use crate::menu_model::{MenuChange, MenuModel, RowModel};
use crate::state::{resolve_icon_state, IconState};
use crate::{daemon, launch};

pub enum TrayAction {
    Quit,
}

/// The items of one device row that change without a rebuild.
struct RowItems {
    submenu: Submenu,
    active: CheckMenuItem,
}

/// The notification items, whose enabled state follows the monitor.
struct NotifItems {
    start: MenuItem,
    stop: MenuItem,
}

pub struct Tray {
    icon: TrayIcon,
    launch_id: MenuId,
    notif_open_id: MenuId,
    notif_start_id: MenuId,
    notif_stop_id: MenuId,
    quit_id: MenuId,
    /// What the installed menu shows. A new model is diffed against it whole
    /// to decide between nothing, an in-place update and a rebuild (P5.3).
    installed: Option<MenuModel>,
    last_icon_state: Option<IconState>,
    last_tooltip: String,
    /// Frame previews decoded into menu icons, once per frame.
    tiles: std::cell::RefCell<crate::tiles::TileCache>,
    /// The device rows of the installed menu, by mac, so a new frame, name,
    /// kind or active panel updates the row IN PLACE instead of rebuilding
    /// the menu (which dismisses it while the user has it open).
    rows: std::cell::RefCell<std::collections::HashMap<String, RowItems>>,
    notif: std::cell::RefCell<Option<NotifItems>>,
    #[cfg(target_os = "macos")]
    menu: std::cell::RefCell<Option<Menu>>,
}

impl Tray {
    pub fn build() -> Option<Self> {
        let builder = TrayIconBuilder::new()
            .with_tooltip("Divoom Control")
            .with_icon(make_icon(IconState::Offline));
        #[cfg(target_os = "macos")]
        let builder = builder
            .with_menu_on_left_click(false)
            .with_menu_on_right_click(false);
        let icon = builder.build().ok()?;
        let mut tray = Self {
            icon,
            launch_id: MenuId::new("launch"),
            notif_open_id: MenuId::new("notif_open"),
            notif_start_id: MenuId::new("notif_start"),
            notif_stop_id: MenuId::new("notif_stop"),
            quit_id: MenuId::new("quit"),
            installed: None,
            last_icon_state: None, // forces the first poll_daemon() to set icon + tooltip
            last_tooltip: String::new(),
            tiles: std::cell::RefCell::new(crate::tiles::TileCache::default()),
            rows: std::cell::RefCell::new(std::collections::HashMap::new()),
            notif: std::cell::RefCell::new(None),
            #[cfg(target_os = "macos")]
            menu: std::cell::RefCell::new(None),
        };
        let empty = MenuModel::default();
        tray.rebuild(&[], &empty);
        tray.installed = Some(empty);
        Some(tray)
    }

    /// Build + install the whole menu: one submenu per device (panel switching,
    /// channels, screen power), then the fixed actions. Only for a change in
    /// WHICH rows exist (`MenuChange::Rebuild`): installing a new root menu
    /// dismisses it if it is open.
    fn rebuild(&self, devices: &[daemon::DeviceView], model: &MenuModel) {
        let menu = Menu::new();
        let mut rows = std::collections::HashMap::new();
        if model.rows.is_empty() {
            let _ = menu.append(&MenuItem::new("No active devices", false, None));
        } else {
            for row in &model.rows {
                let dev_submenu = Submenu::new(&row.label, true);
                // The tile: the frame the panel is showing, from the daemon's
                // broadcast (none when it has not sent one -- text stays honest).
                let preview = devices
                    .iter()
                    .find(|d| d.mac == row.mac)
                    .and_then(|d| d.preview.as_deref());
                dev_submenu.set_icon(self.tiles.borrow_mut().icon_for(preview));
                // Switching panels: the check is the state, the click is the
                // action; the active one is disabled because there is nothing
                // to do on it.
                let active = CheckMenuItem::with_id(
                    MenuId::new(format!("sel:{}", row.mac)),
                    "Active panel",
                    !row.selected,
                    row.selected,
                    None,
                );
                let _ = dev_submenu.append(&active);
                let _ = dev_submenu.append(&PredefinedMenuItem::separator());
                let clk_id = MenuId::new(format!("ch:clock:{}", row.mac));
                let _ = dev_submenu.append(&MenuItem::with_id(clk_id, "Show Clock", true, None));
                let eq_id = MenuId::new(format!("ch:visualizer:{}", row.mac));
                let _ =
                    dev_submenu.append(&MenuItem::with_id(eq_id, "Show Visualizer", true, None));
                let amb_id = MenuId::new(format!("ch:ambient:{}", row.mac));
                let _ = dev_submenu.append(&MenuItem::with_id(amb_id, "Show Ambient", true, None));
                let _ = dev_submenu.append(&PredefinedMenuItem::separator());
                let off_id = MenuId::new(format!("pwr:off:{}", row.mac));
                let _ =
                    dev_submenu.append(&MenuItem::with_id(off_id, "Turn Off Screen", true, None));
                let on_id = MenuId::new(format!("pwr:on:{}", row.mac));
                let _ = dev_submenu.append(&MenuItem::with_id(on_id, "Turn On Screen", true, None));

                let _ = menu.append(&dev_submenu);
                rows.insert(
                    row.mac.clone(),
                    RowItems {
                        submenu: dev_submenu,
                        active,
                    },
                );
            }
        }
        *self.rows.borrow_mut() = rows;
        let _ = menu.append(&PredefinedMenuItem::separator());
        let _ = menu.append(&MenuItem::with_id(
            self.launch_id.clone(),
            "Launch Dashboard",
            true,
            None,
        ));
        let _ = menu.append(&MenuItem::with_id(
            self.notif_open_id.clone(),
            "Open Notifications…",
            true,
            None,
        ));
        let _ = menu.append(&PredefinedMenuItem::separator());
        // Start is enabled when stopped; Stop when running (parity with pyobjc,
        // which shows both — we just disable the inapplicable one).
        let notif = NotifItems {
            start: MenuItem::with_id(
                self.notif_start_id.clone(),
                "Start Notifications",
                !model.notif_running,
                None,
            ),
            stop: MenuItem::with_id(
                self.notif_stop_id.clone(),
                "Stop Notifications",
                model.notif_running,
                None,
            ),
        };
        let _ = menu.append(&notif.start);
        let _ = menu.append(&notif.stop);
        *self.notif.borrow_mut() = Some(notif);
        let _ = menu.append(&PredefinedMenuItem::separator());
        let _ = menu.append(&MenuItem::with_id(
            self.quit_id.clone(),
            "Quit Divoom (stop daemon)",
            true,
            None,
        ));
        #[cfg(target_os = "macos")]
        {
            *self.menu.borrow_mut() = Some(menu);
        }
        #[cfg(not(target_os = "macos"))]
        {
            self.icon.set_menu(Some(Box::new(menu)));
        }
    }

    /// Pop up the context menu anchored flush at the bottom edge of the status
    /// bar button (`NSPoint(x: 0, y: button.bounds.height)` in button-local
    /// coordinates), instead of `tray-icon`'s `setMenu` + `performClick(None)` +
    /// `setMenu(None)` sequence.
    #[cfg(target_os = "macos")]
    pub fn show_menu(&self) {
        use objc2_app_kit::NSMenu;
        use objc2_foundation::{MainThreadMarker, NSPoint};
        use tray_icon::menu::ContextMenu;

        let Some(mtm) = MainThreadMarker::new() else {
            return;
        };
        let Some(status_item) = self.icon.ns_status_item() else {
            return;
        };
        let Some(button) = status_item.button(mtm) else {
            return;
        };
        let menu_ptr = {
            let borrow = self.menu.borrow();
            let Some(menu) = borrow.as_ref() else {
                return;
            };
            menu.ns_menu().cast::<NSMenu>().cast_const()
        };
        if menu_ptr.is_null() {
            return;
        }
        let (x, y) = popup_anchor_in_button(button.bounds().size.height);
        // SAFETY: `menu_ptr` is the live `NSMenu` owned by `self.menu` on the
        // main thread (`MainThreadMarker::new()` succeeded above).
        let ns_menu = unsafe { &*menu_ptr };
        let _ = ns_menu.popUpMenuPositioningItem_atLocation_inView(
            None,
            NSPoint::new(x, y),
            Some(&button),
        );
        button.highlight(false);
    }

    #[cfg(not(target_os = "macos"))]
    pub const fn show_menu(&self) {}

    /// Apply a model whose rows are the installed ones to the existing items,
    /// so an open menu stays open. Both patterns name every field with no
    /// `..`: a field added to the model does not compile until it is named
    /// here (E0027), and one named but not applied is an unused binding.
    fn apply_in_place(&self, model: &MenuModel) {
        let MenuModel {
            rows: row_models,
            notif_running,
        } = model;
        let rows = self.rows.borrow();
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
        if let Some(notif) = self.notif.borrow().as_ref() {
            notif.start.set_enabled(!*notif_running);
            notif.stop.set_enabled(*notif_running);
        }
    }

    /// Same rows, maybe new frames: refresh the tiles in place.
    fn refresh_tiles(&self, devices: &[daemon::DeviceView]) {
        let rows = self.rows.borrow();
        for d in devices {
            if let Some(items) = rows.get(&d.mac) {
                items
                    .submenu
                    .set_icon(self.tiles.borrow_mut().icon_for(d.preview.as_deref()));
            }
        }
    }

    /// Poll the daemon and refresh the glyph colour + menu: in place when the
    /// same rows exist, rebuilt only when the set of rows changed (P5.3). Ingests cached state
    /// from the subscription stream when fresh to eliminate socket churn.
    pub fn poll_daemon(&mut self) {
        let cached = daemon::get_cached_snapshot();
        let (offline, notif_running, connection_state, devices) = if let Some(snap) =
            cached.filter(|s| {
                s.reachable
                    && s.last_event_at
                        .is_some_and(|t| t.elapsed() < Duration::from_secs(10))
            }) {
            (
                !snap.reachable,
                snap.notifications_running,
                snap.connection_state(),
                snap.devices,
            )
        } else {
            let status = daemon::status();
            let off = matches!(status, daemon::Status::Offline);
            let notif = !off && daemon::notifications_running();
            let conn = if off {
                None
            } else {
                daemon::connection_state()
            };
            let acts = if off {
                Vec::new()
            } else {
                daemon::owned_devices()
            };
            daemon::set_cached_snapshot(daemon::DaemonSnapshot::polled(
                !off,
                conn.as_deref(),
                notif,
                acts.clone(),
            ));
            (off, notif, conn, acts)
        };

        let (icon_state, base_tooltip) =
            resolve_icon_state(!offline, connection_state.as_deref(), notif_running);
        // The fleet count belongs in the tooltip: one word cannot say
        // "3 of 4 online".
        let linked = devices
            .iter()
            .filter(|d| matches!(d.link.as_deref(), Some("active" | "connected" | "degraded")))
            .count();
        let mut tooltip = if devices.len() > 1 {
            format!(
                "{base_tooltip} ({linked} of {} panels online)",
                devices.len()
            )
        } else {
            base_tooltip
        };
        if let Some(active) = devices.iter().find(|d| d.selected) {
            tooltip.push_str(" — active: ");
            tooltip.push_str(&active.name);
        }
        if self.last_icon_state != Some(icon_state) {
            let _ = self.icon.set_icon(Some(make_icon(icon_state)));
            self.last_icon_state = Some(icon_state);
        }
        if tooltip != self.last_tooltip {
            let _ = self.icon.set_tooltip(Some(&tooltip));
            self.last_tooltip = tooltip;
        }

        let model = MenuModel::from_devices(&devices, notif_running);
        match model.change_from(self.installed.as_ref()) {
            MenuChange::Rebuild => self.rebuild(&devices, &model),
            MenuChange::InPlace => {
                self.apply_in_place(&model);
                self.refresh_tiles(&devices);
            }
            MenuChange::Unchanged => self.refresh_tiles(&devices),
        }
        self.installed = Some(model);
    }

    /// Dispatch a menu click. Returns `Some(Quit)` when the app should exit.
    pub fn on_menu(&self, ev: &MenuEvent) -> Option<TrayAction> {
        let id_str = ev.id.as_ref();
        if let Some(mac) = id_str.strip_prefix("sel:") {
            daemon::select_device(mac);
            // muda toggles a check item on click by itself. Put the checks
            // back to what the daemon last said: the mark moves when a poll
            // reports the new active panel, and stays put if the switch failed.
            if let Some(model) = &self.installed {
                self.apply_in_place(model);
            }
        } else if let Some(rest) = id_str.strip_prefix("ch:") {
            if let Some((ch, mac)) = rest.split_once(':') {
                daemon::switch_channel(mac, ch);
            }
        } else if let Some(rest) = id_str.strip_prefix("pwr:") {
            if let Some((action, mac)) = rest.split_once(':') {
                daemon::set_screen_power(mac, action == "on");
            }
        } else if ev.id == self.launch_id {
            launch::open_dashboard();
        } else if ev.id == self.notif_open_id {
            launch::open_notifications();
        } else if ev.id == self.notif_start_id {
            daemon::start_notifications();
        } else if ev.id == self.notif_stop_id {
            daemon::stop_notifications();
        } else if ev.id == self.quit_id {
            launch::quit();
            return Some(TrayAction::Quit);
        }
        None
    }
}

/// Whether a tray icon event should pop up the status-item context menu: left
/// or right mouse-down opens the menu, while mouse-up, middle click, and hover
/// events do not.
pub const fn should_pop_up_menu(ev: &TrayIconEvent) -> bool {
    matches!(
        ev,
        TrayIconEvent::Click {
            button: MouseButton::Left | MouseButton::Right,
            button_state: MouseButtonState::Down,
            ..
        }
    )
}

/// Anchor point in the status bar button's flipped coordinate system (`x = 0`,
/// `y = button.bounds.height`), placing the popup menu flush against the
/// bottom edge of the `NSStatusBarButton`.
#[cfg(any(target_os = "macos", test))]
pub const fn popup_anchor_in_button(bounds_height: f64) -> (f64, f64) {
    (0.0, bounds_height)
}

/// The status item's image for `state`. The pixels come from `glyph::draw`,
/// which `tools/render_tray_icon.py` also compiles, so its sheets are this glyph.
fn make_icon(state: IconState) -> tray_icon::Icon {
    let (rgba, w, h) = crate::glyph::draw(state.look());
    tray_icon::Icon::from_rgba(rgba, w, h).expect("valid tray icon")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tray_icon::dpi::PhysicalPosition;
    use tray_icon::{Rect, TrayIconId};

    fn click_event(button: MouseButton, button_state: MouseButtonState) -> TrayIconEvent {
        TrayIconEvent::Click {
            id: TrayIconId::new("divoom-test"),
            position: PhysicalPosition::new(10.0, 12.0),
            rect: Rect::default(),
            button,
            button_state,
        }
    }

    #[test]
    fn popup_anchor_sits_flush_at_button_bottom_edge() {
        assert_eq!(popup_anchor_in_button(22.0), (0.0, 22.0));
        assert_eq!(popup_anchor_in_button(24.0), (0.0, 24.0));
    }

    #[test]
    fn left_and_right_mouse_down_pop_up_menu() {
        assert!(should_pop_up_menu(&click_event(
            MouseButton::Left,
            MouseButtonState::Down
        )));
        assert!(should_pop_up_menu(&click_event(
            MouseButton::Right,
            MouseButtonState::Down
        )));
    }

    #[test]
    fn mouse_up_middle_click_and_move_do_not_pop_up_menu() {
        assert!(!should_pop_up_menu(&click_event(
            MouseButton::Left,
            MouseButtonState::Up
        )));
        assert!(!should_pop_up_menu(&click_event(
            MouseButton::Right,
            MouseButtonState::Up
        )));
        assert!(!should_pop_up_menu(&click_event(
            MouseButton::Middle,
            MouseButtonState::Down
        )));
        let move_ev = TrayIconEvent::Move {
            id: TrayIconId::new("divoom-test"),
            position: PhysicalPosition::new(10.0, 12.0),
            rect: Rect::default(),
        };
        assert!(!should_pop_up_menu(&move_ev));
    }
}
