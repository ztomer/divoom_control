//! The tray/menubar itself: a status-coloured glyph + a menu that mirrors the
//! pyobjc menubar (Launch Dashboard / Open Notifications / Start+Stop
//! Notifications / Quit) plus a read-only active-device section. State is refreshed
//! by polling the daemon (`poll_daemon`); menu clicks are dispatched in `on_menu`.

use std::time::Duration;
use tray_icon::menu::{
    CheckMenuItem, Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem, Submenu,
};
use tray_icon::{TrayIcon, TrayIconBuilder};

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
}

impl Tray {
    pub fn build() -> Option<Self> {
        let icon = TrayIconBuilder::new()
            .with_tooltip("Divoom Control")
            .with_icon(make_icon(IconState::Offline.color()))
            .build()
            .ok()?;
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
        self.icon.set_menu(Some(Box::new(menu)));
    }

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
            let _ = self.icon.set_icon(Some(make_icon(icon_state.color())));
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

/// A stylized "D" glyph: a flat left edge (the letter's vertical stroke) plus
/// a rounded right side (its bowl), outlined in a fixed light border so the
/// shape reads the same regardless of state, with the STATUS colour filling
/// the interior. Replaces the earlier bland filled square — user feedback
/// (2026-07-13) found a plain colored square too unrecognizable to read at a
/// glance; a named-letter silhouette is legible even before checking color.
///
/// Returns raw RGBA plus its dimensions. Split from `make_icon` so the drawing
/// can be rendered and compared WITHOUT a tray: `tools/render_tray_icon.py`
/// compiles THIS function to check its offscreen preview is the real glyph,
/// byte for byte. Wrapping the bytes in a `tray_icon::Icon` is the only
/// tray-specific part.
///
/// SIZE. tray-icon takes the bitmap's pixel height as its height in points,
/// shrinking anything taller than its 22pt cap to fit (0.26; 0.24 forced every
/// icon to 18pt instead). A 1x bitmap is therefore resampled on every Retina
/// display, and the 22 px glyph this used to be grew from 18pt to 22pt when the
/// cap changed -- larger than any neighbouring item, filling the status item's
/// whole height (`NSStatusBar.system.thickness` measured 22.0pt, 2026-10-05).
/// So the canvas is `W` x `H` = 36 x 44 px: the 22pt cap makes that exactly 2x,
/// crisp on Retina, and the status item keeps the 18pt width and the glyph the
/// optical size it had through v0.40. The geometry is still
/// authored in the original 22-unit square and scaled by `W / UNITS`, so the
/// letterform did not change, only its resolution.
fn draw_icon(rgb: [u8; 3]) -> (Vec<u8>, u32, u32) {
    // All pixel arithmetic stays in integers: subsample counts (0..=16) from
    // the coverage loop all the way to the alpha byte, so the float-to-byte
    // narrowing never arises. The alpha formula below is exact round-half-up
    // for every one of the 17 possible counts (checked against the float
    // version it replaces), and `f32::from` covers the geometry (all values
    // fit in u8, which converts exactly).
    const UNITS: f32 = 22.0; // the design square the geometry is authored in
    const W: u8 = 36; // 18pt at 2x
    const H: u8 = 44; // 22pt at 2x -- exactly tray-icon's height cap
    const MARGIN: f32 = 3.0;
    const STROKE: f32 = 2.2;
    const BORDER: [u8; 3] = [0xf5, 0xf5, 0xf5];
    const SUBSAMPLES: u8 = 4; // cheap supersampled AA so the bowl's curve isn't jagged at this size

    let width = usize::from(W);
    let cells = u16::from(SUBSAMPLES) * u16::from(SUBSAMPLES);

    // Design units to pixels. The glyph fills a W x W square centred in the
    // taller canvas; the rows above and below it stay transparent.
    let k = f32::from(W) / UNITS;
    let stroke = STROKE * k;
    let left = MARGIN * k;
    let radius = (UNITS / 2.0 - MARGIN) * k;
    let mid = left + radius;
    let cy = f32::from(H) / 2.0;
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
        let dist2 = dy.mul_add(dy, dx * dx);
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
            fx <= mid && (fx - left).abs() <= stroke && fy >= top - stroke && fy <= bottom + stroke;
        let near_top = fx <= mid && (fy - top).abs() <= stroke;
        let near_bottom = fx <= mid && (fy - bottom).abs() <= stroke;
        let near_bowl = fx >= mid && dist_from_arc.abs() <= stroke;
        near_left || near_top || near_bottom || near_bowl
    };

    let mut rgba = vec![0u8; width * usize::from(H) * 4];
    for y in 0..H {
        for x in 0..W {
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
            let i = (usize::from(y) * width + usize::from(x)) * 4;
            rgba[i] = color[0];
            rgba[i + 1] = color[1];
            rgba[i + 2] = color[2];
            // coverage <= cells, so this is 0..=255 by construction.
            rgba[i + 3] = u8::try_from((u16::from(coverage) * 255 + cells / 2) / cells)
                .expect("subsample coverage scales to one byte");
        }
    }
    (rgba, u32::from(W), u32::from(H))
}

fn make_icon(rgb: [u8; 3]) -> tray_icon::Icon {
    let (rgba, w, h) = draw_icon(rgb);
    tray_icon::Icon::from_rgba(rgba, w, h).expect("valid tray icon")
}
