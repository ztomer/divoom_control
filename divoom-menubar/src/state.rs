//! Pure icon-state resolution (R61 follow-up).
//!
//! Before this, the menubar's icon color came ONLY from `daemon::status()`,
//! which reflects the macOS notification monitor's activity — NOT whether a
//! Divoom device is BLE/LAN connected. `resolve_icon_state` combines both
//! signals: device connection health is the primary, more actionable signal
//! for an at-a-glance icon (mirrors the Python GUI's `transport-dot`
//! precedence in `divoom_gui/web_ui/connection_events.js` — dropped beats
//! degraded beats connected); notification-monitor activity is folded into
//! the tooltip only, so that existing signal isn't silently lost, just
//! demoted from icon color to a detail string.

use crate::glyph::Look;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IconState {
    /// The daemon itself is unreachable — nothing else is known.
    Offline,
    /// Daemon reachable, no device connected (or a device cleanly dropped).
    Idle,
    /// Device connected and healthy.
    Connected,
    /// Device connected but the link is unhealthy (a write/drop just failed;
    /// the daemon's own self-heal may still revive it).
    Degraded,
}

// Kept distinct from tray.rs's icon-drawing code so this module stays pure
// (no TrayIcon, no socket) and trivially unit-testable.
pub const GREEN: [u8; 3] = [0x00, 0xcc, 0x66];
// Darker than a pure amber (#FFCC00): a fill must sit a quarter of the grey
// range away from BOTH menu bars, and #FFCC00's luma (200) was all but the
// light bar's own (236), so Degraded's fill vanished there in greyscale.
pub const AMBER: [u8; 3] = [0xe0, 0x9a, 0x00];

impl IconState {
    /// Every state, for the gates and the offscreen renderer that must cover
    /// them all (the tray itself only ever draws the current one).
    #[cfg(any(test, tray_glyph_probe))]
    pub const ALL: [Self; 4] = [Self::Offline, Self::Idle, Self::Connected, Self::Degraded];

    /// The glyph this state wears (P7.1, owner ruling D8: Offline HOLLOW,
    /// Online FILLED, Error BARRED). Shape carries; the fill colour reinforces.
    ///
    /// The ruling named three states; the agent has four, so the two shape
    /// channels compose: FILLED says a device is linked, BARRED says something
    /// is at fault. Idle (daemon up, no device) is the plain hollow D; a
    /// Connected device is the filled D; Degraded is a linked device at fault
    /// (filled + bar); Offline -- the daemon itself unreachable, the fault that
    /// stops everything -- is hollow + bar. Every pair differs in shape.
    pub const fn look(self) -> Look {
        match self {
            Self::Idle => Look {
                fill: None,
                barred: false,
            },
            Self::Connected => Look {
                fill: Some(GREEN),
                barred: false,
            },
            Self::Degraded => Look {
                fill: Some(AMBER),
                barred: true,
            },
            Self::Offline => Look {
                fill: None,
                barred: true,
            },
        }
    }
}

/// `connection_state` is the daemon's `device_status`/broadcast field —
/// `Some("connected")`, `Some("degraded")`, `Some("disconnected")`, or `None`
/// when no device is owned at all. `notif_active` is the (now secondary)
/// notification-monitor signal `daemon::status()` already tracked.
pub fn resolve_icon_state(
    daemon_reachable: bool,
    connection_state: Option<&str>,
    notif_active: bool,
) -> (IconState, String) {
    let (state, mut tooltip) = if daemon_reachable {
        match connection_state {
            Some("connected") => (
                IconState::Connected,
                "Divoom Control — device connected".to_string(),
            ),
            Some("degraded") => (
                IconState::Degraded,
                "Divoom Control — link degraded, reconnecting".to_string(),
            ),
            _ => (
                IconState::Idle,
                "Divoom Control — no device connected".to_string(),
            ),
        }
    } else {
        (
            IconState::Offline,
            "Divoom Control — daemon offline".to_string(),
        )
    };
    if daemon_reachable && notif_active {
        tooltip.push_str(" · notifications routing");
    }
    (state, tooltip)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn offline_wins_regardless_of_connection_state_or_notif() {
        let (s, t) = resolve_icon_state(false, Some("connected"), true);
        assert_eq!(s, IconState::Offline);
        assert!(
            !t.contains("notifications"),
            "notif detail must not leak when unreachable"
        );
    }

    #[test]
    fn idle_when_no_device_owned() {
        let (s, _) = resolve_icon_state(true, None, false);
        assert_eq!(s, IconState::Idle);
    }

    #[test]
    fn idle_after_clean_disconnect() {
        let (s, _) = resolve_icon_state(true, Some("disconnected"), false);
        assert_eq!(s, IconState::Idle);
    }

    #[test]
    fn connected_is_filled_green_and_says_so() {
        let (s, t) = resolve_icon_state(true, Some("connected"), false);
        assert_eq!(s, IconState::Connected);
        assert_eq!(s.look().fill, Some(GREEN));
        assert!(t.contains("connected"));
    }

    #[test]
    fn degraded_is_visually_distinct_from_connected_and_idle() {
        let (s, t) = resolve_icon_state(true, Some("degraded"), false);
        assert_eq!(s, IconState::Degraded);
        assert_ne!(s.look(), IconState::Connected.look());
        assert_ne!(s.look(), IconState::Idle.look());
        assert_ne!(s.look(), IconState::Offline.look());
        assert!(t.contains("degraded"));
    }

    #[test]
    fn notif_activity_changes_tooltip_not_color() {
        let (s1, t1) = resolve_icon_state(true, Some("connected"), false);
        let (s2, t2) = resolve_icon_state(true, Some("connected"), true);
        assert_eq!(
            s1, s2,
            "notification activity must not change the icon state/glyph"
        );
        assert_ne!(t1, t2);
        assert!(t2.contains("notifications"));
    }

    #[test]
    fn unknown_connection_state_string_falls_back_to_idle_not_a_panic() {
        let (s, _) = resolve_icon_state(true, Some("some-future-state-value"), false);
        assert_eq!(s, IconState::Idle);
    }
}
