//! The tray/menubar itself: a status-coloured glyph + a menu that mirrors the
//! pyobjc menubar (Launch Dashboard / Open Notifications / Start+Stop
//! Notifications / Quit) plus a read-only active-device section. State is refreshed
//! by polling the daemon (`poll_daemon`); menu clicks are dispatched in `on_menu`.

use std::time::Duration;
use tray_icon::menu::{
    CheckMenuItem, Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem, Submenu,
};
use tray_icon::{TrayIcon, TrayIconBuilder};

use crate::state::{resolve_icon_state, IconState};
use crate::{daemon, launch};

pub enum TrayAction {
    Quit,
}

pub struct Tray {
    icon: TrayIcon,
    launch_id: MenuId,
    notif_open_id: MenuId,
    notif_start_id: MenuId,
    notif_stop_id: MenuId,
    quit_id: MenuId,
    last_sig: String,
    last_icon_state: Option<IconState>,
    last_tooltip: String,
    /// Frame previews decoded into menu icons, once per frame.
    tiles: std::cell::RefCell<crate::tiles::TileCache>,
    /// The device rows of the installed menu, by mac, so a new frame updates
    /// a row's icon IN PLACE instead of rebuilding the menu (which dismisses
    /// it while the user has it open).
    rows: std::cell::RefCell<std::collections::HashMap<String, Submenu>>,
}

impl Tray {
    pub fn build() -> Option<Self> {
        let icon = TrayIconBuilder::new()
            .with_tooltip("Divoom Control")
            .with_icon(make_icon(IconState::Offline.color()))
            .build()
            .ok()?;
        let tray = Self {
            icon,
            launch_id: MenuId::new("launch"),
            notif_open_id: MenuId::new("notif_open"),
            notif_start_id: MenuId::new("notif_start"),
            notif_stop_id: MenuId::new("notif_stop"),
            quit_id: MenuId::new("quit"),
            last_sig: String::new(),
            last_icon_state: None, // forces the first poll_daemon() to set icon + tooltip
            last_tooltip: String::new(),
            tiles: std::cell::RefCell::new(crate::tiles::TileCache::default()),
            rows: std::cell::RefCell::new(std::collections::HashMap::new()),
        };
        tray.rebuild(&[], false);
        Some(tray)
    }

    /// Build + install the whole menu: active-device rows (disabled, informational)
    /// then the fixed actions.
    /// Build + install the whole menu: active-device submenus with actionable
    /// channel switching and power controls, plus fixed actions.
    fn rebuild(&self, devices: &[daemon::DeviceView], notif_running: bool) {
        let menu = Menu::new();
        let mut rows = std::collections::HashMap::new();
        if devices.is_empty() {
            let _ = menu.append(&MenuItem::new("No active devices", false, None));
        } else {
            for item in devices {
                let name = &item.name;
                let kind = &item.kind;
                let mut label = if kind.is_empty() || kind == "idle" {
                    name.clone()
                } else {
                    format!("{name} — {kind}")
                };
                // The active panel is named in the row itself, not only by
                // a mark inside its submenu (never one channel).
                if item.selected {
                    label.push_str(" (active)");
                }
                let dev_submenu = Submenu::new(&label, true);
                // The tile: the frame the panel is showing, from the daemon's
                // broadcast (none when it has not sent one -- text stays honest).
                dev_submenu.set_icon(self.tiles.borrow_mut().icon_for(item.preview.as_deref()));
                // Switching panels: the check is the state, the click is the
                // action; the active one is disabled because there is nothing
                // to do on it.
                let sel_id = MenuId::new(format!("sel:{}", item.mac));
                let _ = dev_submenu.append(&CheckMenuItem::with_id(
                    sel_id,
                    "Active panel",
                    !item.selected,
                    item.selected,
                    None,
                ));
                let _ = dev_submenu.append(&PredefinedMenuItem::separator());
                let clk_id = MenuId::new(format!("ch:clock:{}", item.mac));
                let _ = dev_submenu.append(&MenuItem::with_id(clk_id, "Show Clock", true, None));
                let eq_id = MenuId::new(format!("ch:visualizer:{}", item.mac));
                let _ =
                    dev_submenu.append(&MenuItem::with_id(eq_id, "Show Visualizer", true, None));
                let amb_id = MenuId::new(format!("ch:ambient:{}", item.mac));
                let _ = dev_submenu.append(&MenuItem::with_id(amb_id, "Show Ambient", true, None));
                let _ = dev_submenu.append(&PredefinedMenuItem::separator());
                let off_id = MenuId::new(format!("pwr:off:{}", item.mac));
                let _ =
                    dev_submenu.append(&MenuItem::with_id(off_id, "Turn Off Screen", true, None));
                let on_id = MenuId::new(format!("pwr:on:{}", item.mac));
                let _ = dev_submenu.append(&MenuItem::with_id(on_id, "Turn On Screen", true, None));

                let _ = menu.append(&dev_submenu);
                rows.insert(item.mac.clone(), dev_submenu);
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
        let _ = menu.append(&MenuItem::with_id(
            self.notif_start_id.clone(),
            "Start Notifications",
            !notif_running,
            None,
        ));
        let _ = menu.append(&MenuItem::with_id(
            self.notif_stop_id.clone(),
            "Stop Notifications",
            notif_running,
            None,
        ));
        let _ = menu.append(&PredefinedMenuItem::separator());
        let _ = menu.append(&MenuItem::with_id(
            self.quit_id.clone(),
            "Quit Divoom (stop daemon)",
            true,
            None,
        ));
        self.icon.set_menu(Some(Box::new(menu)));
    }

    /// Poll the daemon and refresh the glyph colour + menu (only when changed, to
    /// avoid rebuilding the menu while the user has it open). Ingests cached state
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
            let _ = self.icon.set_icon(Some(make_icon(icon_state.color())));
            self.last_icon_state = Some(icon_state);
        }
        if tooltip != self.last_tooltip {
            let _ = self.icon.set_tooltip(Some(&tooltip));
            self.last_tooltip = tooltip;
        }

        let sig = format!(
            "{}|{}|{}",
            if offline { "off" } else { "on" },
            notif_running,
            devices
                .iter()
                .map(|d| format!("{}:{}:{}:{}", d.mac, d.name, d.kind, d.selected))
                .collect::<Vec<_>>()
                .join(",")
        );
        if sig == self.last_sig {
            // Same rows, maybe new frames: refresh the tiles in place.
            let rows = self.rows.borrow();
            for d in &devices {
                if let Some(row) = rows.get(&d.mac) {
                    row.set_icon(self.tiles.borrow_mut().icon_for(d.preview.as_deref()));
                }
            }
        } else {
            self.rebuild(&devices, notif_running);
            self.last_sig = sig;
        }
    }

    /// Dispatch a menu click. Returns `Some(Quit)` when the app should exit.
    pub fn on_menu(&mut self, ev: &MenuEvent) -> Option<TrayAction> {
        let id_str = ev.id.as_ref();
        if let Some(mac) = id_str.strip_prefix("sel:") {
            daemon::select_device(mac);
            self.last_sig.clear(); // the mark moves on the next poll
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
            self.last_sig.clear(); // force a menu refresh on next poll
        } else if ev.id == self.notif_stop_id {
            daemon::stop_notifications();
            self.last_sig.clear();
        } else if ev.id == self.quit_id {
            launch::quit();
            return Some(TrayAction::Quit);
        }
        None
    }
}

/// A stylized "D" glyph: a flat left edge (the letter's vertical stroke) plus
/// a rounded right side (its bowl), outlined in a fixed light border so the
/// shape reads the same regardless of state, with the STATUS colour filling
/// the interior. Replaces the earlier bland filled square — user feedback
/// (2026-07-13) found a plain colored square too unrecognizable to read at a
/// glance; a named-letter silhouette is legible even before checking color.
fn make_icon(rgb: [u8; 3]) -> tray_icon::Icon {
    // All pixel arithmetic stays in integers: subsample counts (0..=16) from
    // the coverage loop all the way to the alpha byte, so the float-to-byte
    // narrowing never arises. The alpha formula below is exact round-half-up
    // for every one of the 17 possible counts (checked against the float
    // version it replaces), and `f32::from` covers the geometry (all values
    // fit in u8, which converts exactly).
    const N: u8 = 22;
    const MARGIN: f32 = 3.0;
    const STROKE: f32 = 2.2;
    const BORDER: [u8; 3] = [0xf5, 0xf5, 0xf5];
    const SUBSAMPLES: u8 = 4; // cheap supersampled AA so the bowl's curve isn't jagged at this size

    let side = usize::from(N);
    let cells = u16::from(SUBSAMPLES) * u16::from(SUBSAMPLES);

    let left = MARGIN;
    let radius = f32::from(N) / 2.0 - MARGIN;
    let mid = left + radius;
    let cy = f32::from(N) / 2.0;
    let top = cy - radius;
    let bottom = cy + radius;

    // The D's silhouette: a rectangle (the spine + body) unioned with a
    // semicircle (the bowl) sharing the rectangle's right edge as its diameter.
    let inside_d = |fx: f32, fy: f32| -> bool {
        let in_rect = fx >= left && fx <= mid && fy >= top && fy <= bottom;
        let dx = fx - mid;
        let dy = fy - cy;
        // Two independent tests ANDed: below the rim (a half-plane) and
        // inside the circle. The squared distance is bound first so the
        // shape reads as two facts, not one tangled comparison.
        let dist2 = dx * dx + dy * dy;
        let in_bowl = fx >= mid && dist2 <= radius * radius;
        in_rect || in_bowl
    };
    // Within STROKE of the silhouette's own boundary (left/top/bottom edges of
    // the rect, or the bowl's arc) — the fixed-color outline band.
    let is_border = |fx: f32, fy: f32| -> bool {
        let dx = fx - mid;
        let dy = fy - cy;
        let dist_from_arc = radius - dx.hypot(dy);
        let near_left =
            fx <= mid && (fx - left).abs() <= STROKE && fy >= top - STROKE && fy <= bottom + STROKE;
        let near_top = fx <= mid && (fy - top).abs() <= STROKE;
        let near_bottom = fx <= mid && (fy - bottom).abs() <= STROKE;
        let near_bowl = fx >= mid && dist_from_arc.abs() <= STROKE;
        near_left || near_top || near_bottom || near_bowl
    };

    let mut rgba = vec![0u8; side * side * 4];
    for y in 0..N {
        for x in 0..N {
            let mut coverage = 0u8;
            let mut border_weight = 0u8;
            for sy in 0..SUBSAMPLES {
                for sx in 0..SUBSAMPLES {
                    let fx = f32::from(x) + (f32::from(sx) + 0.5) / f32::from(SUBSAMPLES);
                    let fy = f32::from(y) + (f32::from(sy) + 0.5) / f32::from(SUBSAMPLES);
                    if inside_d(fx, fy) {
                        coverage += 1;
                        if is_border(fx, fy) {
                            border_weight += 1;
                        }
                    }
                }
            }
            if coverage == 0 {
                continue;
            }
            // At least half the covered samples on the outline band.
            let color = if border_weight * 2 >= coverage {
                BORDER
            } else {
                rgb
            };
            let i = (usize::from(y) * side + usize::from(x)) * 4;
            rgba[i] = color[0];
            rgba[i + 1] = color[1];
            rgba[i + 2] = color[2];
            // coverage <= cells, so this is 0..=255 by construction.
            rgba[i + 3] = u8::try_from((u16::from(coverage) * 255 + cells / 2) / cells)
                .expect("subsample coverage scales to one byte");
        }
    }
    tray_icon::Icon::from_rgba(rgba, u32::from(N), u32::from(N)).expect("valid tray icon")
}
