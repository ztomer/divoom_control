//! An OPEN menu follows the daemon (D.MENULIVE, 2026-11-02).
//!
//! QA held the menu open, made Pixoo-1 the active panel from the CLI, and two
//! seconds later the menu still read "Tivoo-Max-light-3 (active)". The model
//! half was right (P5.3 updates rows in place) but never ran: the menu is
//! shown with `popUpMenuPositioningItem:atLocation:inView:`, which TRACKS the
//! menu in a nested run loop until it closes, and it is called from inside
//! winit's event handler. winit does not re-enter its handler, so the poll
//! timer and every daemon broadcast queued behind the open menu -- the menu
//! was frozen exactly while someone was looking at it.
//!
//! So while the menu is open a run-loop timer of its own refreshes it, in the
//! mode `AppKit` tracks menus in (`NSEventTrackingRunLoopMode`, and the common
//! modes besides). It reads the snapshot the subscribe thread keeps current
//! and applies only IN-PLACE changes: a change in which rows exist needs a new
//! root menu, which would dismiss the open one, so that waits for the next
//! poll after the menu closes.

use std::ffi::c_void;
use std::time::Duration;

use objc2_core_foundation::{
    kCFRunLoopCommonModes, CFAbsoluteTimeGetCurrent, CFRetained, CFRunLoop, CFRunLoopTimer,
    CFRunLoopTimerContext, CFString,
};

use crate::daemon::DaemonSnapshot;
use crate::menu_model::{MenuChange, MenuModel};

/// The run-loop mode `AppKit` tracks an open menu in.
pub const TRACKING_MODE: &str = "NSEventTrackingRunLoopMode";
/// How often an open menu re-reads the daemon's state.
pub const OPEN_REFRESH: Duration = Duration::from_millis(250);

/// The model an open menu should now show, when it can show it without
/// closing: `Some` for an in-place change, `None` when nothing changed or the
/// SET of rows did (that needs a rebuild, which waits for the menu to close).
pub fn open_menu_update(shown: &MenuModel, snap: &DaemonSnapshot) -> Option<MenuModel> {
    let next = MenuModel::from_devices(&snap.devices, snap.notifications_running);
    match next.change_from(Some(shown)) {
        MenuChange::InPlace => Some(next),
        MenuChange::Unchanged | MenuChange::Rebuild => None,
    }
}

/// Calls `tick` every `every` on `run_loop` -- in the menu-tracking mode as
/// well as the common modes -- until dropped.
pub struct WhileOpen {
    timer: CFRetained<CFRunLoopTimer>,
    // Boxed twice so the pointer handed to the timer is a thin, stable one.
    _tick: Box<Box<dyn Fn()>>,
}

unsafe extern "C-unwind" fn fire(_timer: *mut CFRunLoopTimer, info: *mut c_void) {
    // SAFETY: `info` is the `Box<dyn Fn()>` owned by the `WhileOpen` that
    // created this timer, and that `WhileOpen` invalidates the timer before
    // it drops the box, so the pointer is live whenever the timer fires.
    let tick = unsafe { &*info.cast::<Box<dyn Fn()>>() };
    tick();
}

impl WhileOpen {
    pub fn start(run_loop: &CFRunLoop, every: Duration, tick: Box<dyn Fn()>) -> Option<Self> {
        let tick = Box::new(tick);
        let mut context = CFRunLoopTimerContext {
            version: 0,
            info: std::ptr::from_ref::<Box<dyn Fn()>>(&tick).cast_mut().cast(),
            retain: None,
            release: None,
            copyDescription: None,
        };
        let interval = every.as_secs_f64();
        // SAFETY: `fire` matches `CFRunLoopTimerCallBack`; `context` is a
        // valid pointer for the duration of the call (CF copies it), and its
        // `info` outlives the timer (see `fire`).
        let timer = unsafe {
            CFRunLoopTimer::new(
                None,
                CFAbsoluteTimeGetCurrent() + interval,
                interval,
                0,
                0,
                Some(fire),
                &raw mut context,
            )
        }?;
        let tracking = CFString::from_static_str(TRACKING_MODE);
        run_loop.add_timer(Some(&timer), Some(&tracking));
        // SAFETY: reading an immutable CoreFoundation constant.
        run_loop.add_timer(Some(&timer), unsafe { kCFRunLoopCommonModes });
        Some(Self { timer, _tick: tick })
    }
}

impl Drop for WhileOpen {
    fn drop(&mut self) {
        self.timer.invalidate();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::daemon::DeviceView;
    use std::cell::RefCell;
    use std::rc::Rc;

    fn dev(mac: &str, name: &str, selected: bool) -> DeviceView {
        DeviceView {
            mac: mac.to_string(),
            name: name.to_string(),
            kind: "idle".to_string(),
            preview: None,
            link: Some("active".to_string()),
            selected,
        }
    }

    fn snap(active: &str) -> DaemonSnapshot {
        DaemonSnapshot::polled(
            true,
            None,
            false,
            vec![
                dev("AA", "Tivoo-Max-light-3", active == "AA"),
                dev("BB", "Pixoo-1", active == "BB"),
            ],
        )
    }

    fn active_label(m: &MenuModel) -> Option<&str> {
        m.rows.iter().find(|r| r.selected).map(|r| r.label.as_str())
    }

    #[test]
    fn a_new_active_panel_is_an_in_place_update() {
        let shown = MenuModel::from_devices(&snap("AA").devices, false);
        let next = open_menu_update(&shown, &snap("BB")).expect("in place");
        assert_eq!(active_label(&next), Some("Pixoo-1 (active)"));
        assert!(
            open_menu_update(&next, &snap("BB")).is_none(),
            "nothing changed"
        );
        let mut more = snap("BB");
        more.devices.push(dev("CC", "Ditoo", false));
        assert!(
            open_menu_update(&next, &more).is_none(),
            "a new row needs a rebuild, which would close the menu"
        );
    }

    /// The defect itself: with the menu OPEN (its run loop in `AppKit`'s
    /// tracking mode, where winit's handler cannot run), the active panel
    /// changes in the daemon's state -- and the shown model follows it,
    /// without the menu closing.
    #[test]
    fn an_open_menu_follows_the_active_panel() {
        let applied = std::thread::spawn(|| {
            let run_loop = CFRunLoop::current().expect("run loop");
            let state = Rc::new(RefCell::new(snap("AA")));
            let shown = Rc::new(RefCell::new(MenuModel::from_devices(
                &state.borrow().devices,
                false,
            )));
            let ticks = Rc::new(RefCell::new(0_u32));
            let (s, m, t) = (state, shown.clone(), ticks.clone());
            let live = WhileOpen::start(
                &run_loop,
                Duration::from_millis(50),
                Box::new(move || {
                    *t.borrow_mut() += 1;
                    // The CLI makes Pixoo-1 active while the menu is open.
                    if *t.borrow() == 2 {
                        *s.borrow_mut() = snap("BB");
                    }
                    let next = open_menu_update(&m.borrow(), &s.borrow());
                    if let Some(next) = next {
                        *m.borrow_mut() = next;
                    }
                }),
            )
            .expect("timer");
            let tracking = CFString::from_static_str(TRACKING_MODE);
            CFRunLoop::run_in_mode(Some(&tracking), 0.6, false);
            drop(live);
            let label = active_label(&shown.borrow()).map(str::to_string);
            let count = *ticks.borrow();
            (label, count)
        })
        .join()
        .expect("thread");
        assert!(
            applied.1 >= 3,
            "the open menu was refreshed {} times",
            applied.1
        );
        assert_eq!(applied.0.as_deref(), Some("Pixoo-1 (active)"));
    }
}
