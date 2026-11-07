//! Which panels cannot be wall slots, and why (P6.1). Split out of `wall.rs`
//! for the 500-line rule.

/// Why a panel on Wi-Fi is not a wall slot (P6.2), as every client shows it.
///
/// The daemon draws images through the Bluetooth 0x8B stream only: a LAN
/// transport has no `send_command` and no `stream_animation_8b`
/// (`transport.rs`), and `device_call/lan.rs` speaks no image command. The
/// vendor app's Wi-Fi upload IS in the references (`Draw/PixelLocalHttp`, a
/// multipart POST to port 9000, `docs/council-p6.md` F10); what is missing is
/// this daemon's command for it and a Wi-Fi panel to prove it on. A wall used
/// to cut a LAN slot's piece, fail to send it and report the whole wall failed
/// with this reason discarded.
pub const LAN_SLOT_REFUSAL: &str =
    "Not a wall slot: this app draws images over Bluetooth only, and has no Wi-Fi image command yet.";

/// Whether `mac` names a LAN panel: the daemon's id for one is `LAN:<ip>`.
pub(super) fn is_lan_id(mac: &str) -> bool {
    mac.get(..4).is_some_and(|p| p.eq_ignore_ascii_case("LAN:"))
}
