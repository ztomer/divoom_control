//! An OPEN menu follows the daemon (D.MENULIVE 2026-11-02, D.MENUEVENT).
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
//! The fix is a run-loop SOURCE of our own, added in the mode `AppKit` tracks
//! menus in (`NSEventTrackingRunLoopMode`, and the common modes besides). The
//! daemon DOES offer an event stream -- the subscribe thread already folds
//! every `selection`, `owned_devices`, `status` and `activity` broadcast into
//! the snapshot -- so that thread signals the source ([`notify`]) and the open
//! menu re-reads the snapshot exactly when it changed, instead of on a clock.
//! D.MENULIVE first used a 250 ms timer, which woke the process four times a
//! second for as long as a menu stayed open and could show a change up to 250
//! ms late. The menu applies only IN-PLACE changes: a change in which rows
//! exist needs a new root menu, which would dismiss the open one, so that
//! waits for the next poll after the menu closes.

use std::ffi::c_void;
use std::sync::{Mutex, PoisonError};

use objc2_core_foundation::{
    kCFRunLoopCommonModes, CFRetained, CFRunLoop, CFRunLoopSource, CFRunLoopSourceContext, CFString,
};

use crate::daemon::DaemonSnapshot;
use crate::menu_model::{MenuChange, MenuModel};

/// The run-loop mode `AppKit` tracks an open menu in.
pub const TRACKING_MODE: &str = "NSEventTrackingRunLoopMode";

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

/// The addresses of every live [`WhileOpen`]'s run-loop source and run loop,
/// which the subscribe thread signals and wakes. Addresses, not references: a
/// `CFRetained` is not `Send`, and the one thing this registry is for is the
/// pair of calls CoreFoundation documents as safe from any thread.
///
/// A REGISTRY keyed by source, not one slot (D.REV1): two `WhileOpen`s can
/// overlap -- `self.live = start(..)` builds the new one before the old one
/// drops, and a menu can open while another is tracking -- and a single slot
/// that each drop cleared unconditionally let the old drop wipe the new
/// registration, so the open menu stopped following the daemon. Each drop now
/// removes exactly its own entry.
static OPEN: Mutex<Vec<(usize, usize)>> = Mutex::new(Vec::new());

/// Tell the open menu, if there is one, that the daemon's state changed. Cheap
/// and callable from any thread: the subscribe thread calls it after folding
/// each broadcast into the snapshot.
pub fn notify() {
    let open = OPEN.lock().unwrap_or_else(PoisonError::into_inner);
    for &(source, run_loop) in open.iter() {
        // SAFETY: the two addresses are those of the source and run loop that
        // a live `WhileOpen` holds a retain on, and `WhileOpen::drop` removes
        // its entry -- under the lock held here -- before it releases either,
        // so both are alive for as long as this guard is. `signal` is
        // `CFRunLoopSourceSignal` and `wake_up` is `CFRunLoopWakeUp`: the two
        // CoreFoundation calls documented as safe from any thread (that is
        // what a run-loop source is for).
        unsafe {
            (*std::ptr::with_exposed_provenance::<CFRunLoopSource>(source)).signal();
            (*std::ptr::with_exposed_provenance::<CFRunLoop>(run_loop)).wake_up();
        }
    }
}

/// Calls `tick` on `run_loop` -- in the menu-tracking mode as well as the
/// common modes -- once on opening and again after every [`notify`], until
/// dropped.
pub struct WhileOpen {
    source: CFRetained<CFRunLoopSource>,
    // Held so the address in `OPEN` stays valid until `drop` clears it.
    _run_loop: CFRetained<CFRunLoop>,
    // Boxed twice so the pointer handed to the source is a thin, stable one.
    _tick: Box<Box<dyn Fn()>>,
}

unsafe extern "C-unwind" fn fire(info: *mut c_void) {
    // SAFETY: `info` is the `Box<dyn Fn()>` owned by the `WhileOpen` that
    // created this source, and that `WhileOpen` invalidates the source before
    // it drops the box, so the pointer is live whenever the source fires.
    let tick = unsafe { &*info.cast::<Box<dyn Fn()>>() };
    tick();
}

impl WhileOpen {
    pub fn start(run_loop: CFRetained<CFRunLoop>, tick: Box<dyn Fn()>) -> Option<Self> {
        let tick = Box::new(tick);
        let mut context = CFRunLoopSourceContext {
            version: 0,
            info: std::ptr::from_ref::<Box<dyn Fn()>>(&tick).cast_mut().cast(),
            retain: None,
            release: None,
            copyDescription: None,
            equal: None,
            hash: None,
            schedule: None,
            cancel: None,
            perform: Some(fire),
        };
        // SAFETY: `context` is a valid pointer for the duration of the call
        // (CF copies it), `fire` matches `perform`, and its `info` outlives
        // the source (see `fire`).
        let source = unsafe { CFRunLoopSource::new(None, 0, &raw mut context) }?;
        let tracking = CFString::from_static_str(TRACKING_MODE);
        run_loop.add_source(Some(&source), Some(&tracking));
        // SAFETY: reading an immutable CoreFoundation constant.
        run_loop.add_source(Some(&source), unsafe { kCFRunLoopCommonModes });
        // Catch up on whatever changed since the last poll: the first tick.
        source.signal();
        OPEN.lock().unwrap_or_else(PoisonError::into_inner).push((
            std::ptr::from_ref::<CFRunLoopSource>(&source).expose_provenance(),
            std::ptr::from_ref::<CFRunLoop>(&run_loop).expose_provenance(),
        ));
        Some(Self {
            source,
            _run_loop: run_loop,
            _tick: tick,
        })
    }
}

impl Drop for WhileOpen {
    fn drop(&mut self) {
        // Out of the registry first, so no `notify` signals a dead source --
        // and only this source's entry: another `WhileOpen` may be live.
        let mine = std::ptr::from_ref::<CFRunLoopSource>(&self.source).expose_provenance();
        OPEN.lock()
            .unwrap_or_else(PoisonError::into_inner)
            .retain(|&(source, _)| source != mine);
        self.source.invalidate();
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

    /// `OPEN` is process-wide and the test harness runs tests in parallel, so
    /// a test that registers a source or calls `notify` holds this lock: one
    /// test's `notify` must not tick another test's source.
    static SERIAL: Mutex<()> = Mutex::new(());

    fn serial() -> std::sync::MutexGuard<'static, ()> {
        SERIAL.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// A `WhileOpen` on the current thread's run loop that counts its ticks.
    fn counting() -> (WhileOpen, Rc<RefCell<u32>>) {
        let ticks = Rc::new(RefCell::new(0_u32));
        let t = ticks.clone();
        let live = WhileOpen::start(
            CFRunLoop::current().expect("run loop"),
            Box::new(move || *t.borrow_mut() += 1),
        )
        .expect("source");
        (live, ticks)
    }

    fn run_tracking(seconds: f64) {
        let tracking = CFString::from_static_str(TRACKING_MODE);
        CFRunLoop::run_in_mode(Some(&tracking), seconds, false);
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

    /// D.MENUEVENT: an open menu is driven by the daemon's event stream, not by
    /// a clock. With no event the tick runs once (on opening, to catch up with
    /// what changed since the last poll); an event from another thread -- the
    /// subscribe thread -- runs it again, in the menu-tracking mode, and the
    /// shown model follows the new active panel.
    /// D.REV1: two `WhileOpen`s overlap whenever the new one is built before
    /// the old one drops (`self.live = start(..)`), or a menu opens while
    /// another tracks. Whichever drops first, the survivor still follows
    /// `notify` -- a drop removes its own registration, never the other's.
    #[test]
    fn an_overlapping_drop_does_not_unregister_the_survivor() {
        let _serial = serial();
        // The old one drops after the new one registered (assignment order).
        let (old, _) = counting();
        let (new, new_ticks) = counting();
        drop(old);
        run_tracking(0.05);
        assert_eq!(*new_ticks.borrow(), 1, "the opening tick");
        notify();
        run_tracking(0.05);
        assert_eq!(*new_ticks.borrow(), 2, "the survivor still follows events");
        // The inner one drops first (nested): the outer one still follows.
        let (inner, _) = counting();
        drop(inner);
        notify();
        run_tracking(0.05);
        assert_eq!(*new_ticks.borrow(), 3, "the outer one still follows events");
        drop(new);
        assert_eq!(
            OPEN.lock().unwrap().len(),
            0,
            "every drop removed its own registration"
        );
    }

    #[test]
    fn an_open_menu_follows_an_event_and_does_not_poll() {
        use std::sync::{mpsc, Arc, Mutex};
        let _serial = serial();
        // A broadcast that lands while no menu is open finds no waker and does
        // nothing -- the subscribe thread calls `notify` for every event.
        notify();
        let state = Arc::new(Mutex::new(snap("AA")));
        let sub_state = state.clone();
        // The event lands AFTER the opening tick has shown the old state:
        // ordered by a channel the first tick sends on, not by a sleep, so a
        // loaded run cannot reorder them (D.REV1). (An event that lands before
        // the opening tick fires coalesces into it -- a signalled source fires
        // once -- and that tick reads the newer snapshot, which is correct but
        // is not the case this test is about.)
        let (opened, is_open) = mpsc::channel::<()>();
        let subscriber = std::thread::spawn(move || {
            is_open.recv().expect("the menu opened");
            // The daemon's `selection` event lands in the snapshot, then wakes
            // the open menu.
            *sub_state.lock().unwrap() = snap("BB");
            notify();
        });
        let (label, ticks) = std::thread::spawn(move || {
            let run_loop = CFRunLoop::current().expect("run loop");
            let shown = Rc::new(RefCell::new(MenuModel::from_devices(
                &state.lock().unwrap().devices,
                false,
            )));
            let ticks = Rc::new(RefCell::new(0_u32));
            let (m, t) = (shown.clone(), ticks.clone());
            let live = WhileOpen::start(
                run_loop,
                Box::new(move || {
                    *t.borrow_mut() += 1;
                    let next = open_menu_update(&m.borrow(), &state.lock().unwrap());
                    if let Some(next) = next {
                        *m.borrow_mut() = next;
                    }
                    if *t.borrow() == 1 {
                        opened.send(()).expect("subscriber waiting");
                    }
                }),
            )
            .expect("source");
            run_tracking(0.8);
            drop(live);
            let label = active_label(&shown.borrow()).map(str::to_string);
            let count = *ticks.borrow();
            (label, count)
        })
        .join()
        .expect("thread");
        subscriber.join().expect("subscriber");
        notify(); // and after the menu closed
        assert_eq!(label.as_deref(), Some("Pixoo-1 (active)"));
        assert_eq!(
            ticks, 2,
            "one tick on opening, one for the event, none else"
        );
    }
}
