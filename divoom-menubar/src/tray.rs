//! The tray/menubar itself: a status-coloured glyph + a menu that mirrors the
//! pyobjc menubar (Launch Dashboard / Open Notifications / Start+Stop
//! Notifications / Quit) plus a read-only active-device section. State is refreshed
//! by polling the daemon (`poll_daemon`); menu clicks are dispatched in `on_menu`.

use tray_icon::menu::{Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem};
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
}

impl Tray {
    pub fn build() -> Option<Tray> {
        let icon = TrayIconBuilder::new()
            .with_tooltip("Divoom Control")
            .with_icon(make_icon(IconState::Offline.color()))
            .build()
            .ok()?;
        let mut tray = Tray {
            icon,
            launch_id: MenuId::new("launch"),
            notif_open_id: MenuId::new("notif_open"),
            notif_start_id: MenuId::new("notif_start"),
            notif_stop_id: MenuId::new("notif_stop"),
            quit_id: MenuId::new("quit"),
            last_sig: String::new(),
            last_icon_state: None, // forces the first poll_daemon() to set icon + tooltip
            last_tooltip: String::new(),
        };
        tray.rebuild(&[], false);
        Some(tray)
    }

    /// Build + install the whole menu: active-device rows (disabled, informational)
    /// then the fixed actions.
    fn rebuild(&mut self, devices: &[(String, String)], notif_running: bool) {
        let menu = Menu::new();
        if devices.is_empty() {
            let _ = menu.append(&MenuItem::new("No active devices", false, None));
        } else {
            for (name, kind) in devices {
                let label = if kind.is_empty() || kind == "idle" {
                    name.clone()
                } else {
                    format!("{name} — {kind}")
                };
                let _ = menu.append(&MenuItem::new(label, false, None));
            }
        }
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
    /// avoid rebuilding the menu while the user has it open).
    pub fn poll_daemon(&mut self) {
        let status = daemon::status();
        let offline = matches!(status, daemon::Status::Offline);
        let notif_running = !offline && daemon::notifications_running();
        // R61 follow-up: the icon previously reflected ONLY the notification
        // monitor (`status`, above) — never whether a device is BLE/LAN
        // connected. connection_state() adds that as the primary signal;
        // notif_running now only affects the tooltip (see resolve_icon_state).
        let connection_state = if offline {
            None
        } else {
            daemon::connection_state()
        };
        let (icon_state, tooltip) =
            resolve_icon_state(!offline, connection_state.as_deref(), notif_running);
        if self.last_icon_state != Some(icon_state) {
            let _ = self.icon.set_icon(Some(make_icon(icon_state.color())));
            self.last_icon_state = Some(icon_state);
        }
        if tooltip != self.last_tooltip {
            let _ = self.icon.set_tooltip(Some(&tooltip));
            self.last_tooltip = tooltip;
        }

        let devices = if offline {
            Vec::new()
        } else {
            daemon::device_activity()
        };

        let sig = format!(
            "{}|{}|{}",
            if offline { "off" } else { "on" },
            notif_running,
            devices
                .iter()
                .map(|(n, k)| format!("{n}:{k}"))
                .collect::<Vec<_>>()
                .join(",")
        );
        if sig != self.last_sig {
            self.rebuild(&devices, notif_running);
            self.last_sig = sig;
        }
    }

    /// Dispatch a menu click. Returns `Some(Quit)` when the app should exit.
    pub fn on_menu(&mut self, ev: &MenuEvent) -> Option<TrayAction> {
        if ev.id == self.launch_id {
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
    const N: usize = 22;
    const MARGIN: f32 = 3.0;
    const STROKE: f32 = 2.2;
    const BORDER: [u8; 3] = [0xf5, 0xf5, 0xf5];
    const SUBSAMPLES: i32 = 4; // cheap supersampled AA so the bowl's curve isn't jagged at this size

    let left = MARGIN;
    let radius = (N as f32) / 2.0 - MARGIN;
    let mid = left + radius;
    let cy = (N as f32) / 2.0;
    let top = cy - radius;
    let bottom = cy + radius;

    // The D's silhouette: a rectangle (the spine + body) unioned with a
    // semicircle (the bowl) sharing the rectangle's right edge as its diameter.
    let inside_d = |fx: f32, fy: f32| -> bool {
        let in_rect = fx >= left && fx <= mid && fy >= top && fy <= bottom;
        let dx = fx - mid;
        let dy = fy - cy;
        let in_bowl = fx >= mid && (dx * dx + dy * dy) <= radius * radius;
        in_rect || in_bowl
    };
    // Within STROKE of the silhouette's own boundary (left/top/bottom edges of
    // the rect, or the bowl's arc) — the fixed-color outline band.
    let is_border = |fx: f32, fy: f32| -> bool {
        let dx = fx - mid;
        let dy = fy - cy;
        let dist_from_arc = radius - (dx * dx + dy * dy).sqrt();
        let near_left =
            fx <= mid && (fx - left).abs() <= STROKE && fy >= top - STROKE && fy <= bottom + STROKE;
        let near_top = fx <= mid && (fy - top).abs() <= STROKE;
        let near_bottom = fx <= mid && (fy - bottom).abs() <= STROKE;
        let near_bowl = fx >= mid && dist_from_arc.abs() <= STROKE;
        near_left || near_top || near_bottom || near_bowl
    };

    let mut rgba = vec![0u8; N * N * 4];
    for y in 0..N {
        for x in 0..N {
            let mut coverage = 0.0f32;
            let mut border_weight = 0.0f32;
            for sy in 0..SUBSAMPLES {
                for sx in 0..SUBSAMPLES {
                    let fx = x as f32 + (sx as f32 + 0.5) / SUBSAMPLES as f32;
                    let fy = y as f32 + (sy as f32 + 0.5) / SUBSAMPLES as f32;
                    if inside_d(fx, fy) {
                        coverage += 1.0;
                        if is_border(fx, fy) {
                            border_weight += 1.0;
                        }
                    }
                }
            }
            let total = (SUBSAMPLES * SUBSAMPLES) as f32;
            if coverage <= 0.0 {
                continue;
            }
            let border_frac = border_weight / coverage;
            let color = if border_frac >= 0.5 { BORDER } else { rgb };
            let i = (y * N + x) * 4;
            rgba[i] = color[0];
            rgba[i + 1] = color[1];
            rgba[i + 2] = color[2];
            rgba[i + 3] = ((coverage / total) * 255.0).round() as u8;
        }
    }
    tray_icon::Icon::from_rgba(rgba, N as u32, N as u32).expect("valid tray icon")
}
