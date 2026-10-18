//! Which panels cannot be wall slots, and why (P6.1). Split out of `wall.rs`
//! for the 500-line rule.

/// Why a panel on Wi-Fi is not a wall slot (P6.1), as every client shows it.
///
/// The daemon draws images through the Bluetooth 0x8B stream only: a LAN
/// transport has no `send_command` and no `stream_animation_8b`
/// (`transport.rs`), and `device_call/lan.rs` speaks no image command. The
/// vendor app's Wi-Fi image upload is `DesignSendModel.sendByLocalHttp`, and
/// that method did not decompile ("Method dump skipped"), so its protocol is
/// not in the references and is not invented here. A wall used to cut a LAN
/// slot's piece, fail to send it and report the whole wall failed with this
/// reason discarded.
pub const LAN_SLOT_REFUSAL: &str = "Not a wall slot: images reach panels over Bluetooth only, \
     and the Wi-Fi image upload Divoom's own app uses is not known.";

/// Whether `mac` names a LAN panel: the daemon's id for one is `LAN:<ip>`.
pub(super) fn is_lan_id(mac: &str) -> bool {
    mac.get(..4).is_some_and(|p| p.eq_ignore_ascii_case("LAN:"))
}
