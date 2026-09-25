//! The wire contract between `divoomd` and the `spp_bridge.py` co-process.
//!
//! The bridge exists for one reason: classic Bluetooth SPP needs `PyObjC`, which
//! Rust cannot call. Everything else it used to do — turning a payload into a
//! frame — it no longer does. The daemon frames, with the same functions the
//! BLE path uses, and the bridge writes bytes.
//!
//! That is not a tidiness change. Until 2026-09-25 the framing lived in
//! `libdivoom_compact.dylib`, a C library compiled per platform and committed
//! to the tree, reachable only from the bridge's Python; so the C had to exist,
//! and `scripts/build_libdivoom.sh` had to keep working, to send one command.
//! The bytes are already implemented here (`crate::framing`), pinned against
//! the C by 550 vectors in `tests/framing_vectors.json` — every length up to
//! 80 bytes in both escape modes, each escape byte at every position — so the
//! C had one caller left and that caller had a twin.
//!
//! The message is JSON-lines because that is what the bridge already spoke, and
//! the frame travels as hex: a decimal byte array costs four characters per
//! byte on the wire, and an 8 KB frame is the size of a whole basic-protocol
//! message. The frame is hex-ENCODED rather than a JSON array of numbers so a
//! frame containing any byte value is representable without escaping rules
//! changing under us.

use serde_json::{json, Value};

use crate::autoprobe::Protocol;
use crate::framing;
use crate::wire::hex;

/// A message the bridge understands.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BridgeMessage {
    /// Write these EXACT bytes to the device. Already framed.
    Write(Vec<u8>),
    /// Close the link and exit.
    Disconnect,
}

impl BridgeMessage {
    /// The line to write to the bridge's stdin, newline included.
    #[must_use]
    pub fn to_line(&self) -> String {
        let value = match self {
            Self::Write(frame) => json!({"command": "write", "frame": hex(frame)}),
            Self::Disconnect => json!({"command": "disconnect"}),
        };
        format!("{value}\n")
    }
}

/// Frame `[command_id, args...]` in the device's active framing.
///
/// This is the function that used to be a call across the FFI into C, and it is
/// the one place the SPP path can diverge from the BLE path: both must produce
/// the same bytes for the same command, or a device behaves differently
/// depending on which radio reached it.
///
/// # Errors
///
/// `IosLe` framing refuses a payload with no command id (nothing to frame), and
/// refuses one longer than its length field can describe. Both are the C's
/// refusals, kept as refusals rather than truncated into a plausible frame.
pub fn frame_command(
    command_id: u8,
    args: &[u8],
    protocol: Protocol,
) -> Result<Vec<u8>, &'static str> {
    let mut payload = Vec::with_capacity(1 + args.len());
    payload.push(command_id);
    payload.extend_from_slice(args);
    match protocol {
        Protocol::Basic => Ok(framing::encode_basic_payload(&payload, false)),
        Protocol::IosLe => framing::encode_ios_le_payload(&payload, 0),
    }
}

/// A `write` message for `[command_id, args...]`, framed and hex-encoded.
///
/// # Errors
///
/// Whatever [`frame_command`] refuses, for the same reason.
pub fn write_command_line(
    command_id: u8,
    args: &[u8],
    protocol: Protocol,
) -> Result<String, &'static str> {
    Ok(BridgeMessage::Write(frame_command(command_id, args, protocol)?).to_line())
}

/// Parse a line FROM the bridge (notifications and status), for symmetry with
/// [`BridgeMessage::to_line`] and so the contract has one home.
///
/// # Errors
///
/// On a line that is not JSON, or JSON that is not an object with a `type`.
pub fn parse_bridge_message(line: &str) -> Result<Value, &'static str> {
    let value: Value = serde_json::from_str(line.trim()).map_err(|_| "bridge line is not JSON")?;
    if !value.is_object() {
        return Err("bridge line is not a JSON object");
    }
    if value.get("type").is_none() {
        return Err("bridge line has no `type`");
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex_of(bytes: &[u8]) -> String {
        crate::wire::hex(bytes)
    }

    #[test]
    fn the_frame_is_the_owners_own_encoder() {
        // The whole point: this path must produce the same bytes the BLE path
        // does, so it calls the same function rather than a second encoder.
        let frame = frame_command(0x46, &[0x01, 0x02], Protocol::Basic).expect("basic frames");
        let mut payload = vec![0x46, 0x01, 0x02];
        assert_eq!(frame, framing::encode_basic_payload(&payload, false));
        payload.clear();
    }

    /// Expectations come from the committed C-derived vectors, never from
    /// arithmetic in this file. The first draft of these three tests hard-coded
    /// hex from memory and three of them were wrong: the basic frame of a bare
    /// 0x46 is `01030046490002` (not `010200464b0002`), the `ios_le` header is
    /// four bytes `FE EF AA 55` (not three), and a 64 KB payload is MASKED to
    /// 16 bits rather than refused. All three are the C's real behaviour --
    /// which is the point of reading them off the vectors instead of off my own
    /// head.
    fn c_vectors() -> serde_json::Value {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/framing_vectors.json");
        let raw = std::fs::read_to_string(path).unwrap_or_else(|e| {
            panic!("read {path}: {e} (run scripts/codegen/gen_framing_vectors.py)")
        });
        serde_json::from_str(&raw).expect("vectors parse")
    }

    fn hex_bytes(s: &str) -> Vec<u8> {
        (0..s.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("hex"))
            .collect()
    }

    #[test]
    fn every_framed_command_matches_the_committed_c_vectors() {
        // The strongest statement this module can make: the frames the SPP path
        // puts on the wire are, byte for byte, the frames the C library put
        // there -- for a sweep of payloads and packet numbers, not a sample.
        let vectors = c_vectors();
        let basic_cases = vectors["encode_basic"]
            .as_array()
            .expect("encode_basic cases");
        let mut checked = 0;
        for case in basic_cases {
            let payload = payload_of(case);
            let escape = case["escape"].as_bool().expect("escape flag");
            let expected = hex_bytes(case["out"].as_str().expect("out hex"));
            let framed = framing::encode_basic_payload(&payload, escape);
            assert_eq!(framed, expected, "basic framing diverged from the C vector");
            checked += 1;
        }
        assert!(
            checked > 150,
            "only {checked} basic vectors: the sweep shrank"
        );

        let ios_cases = vectors["encode_ios_le"]
            .as_array()
            .expect("encode_ios_le cases");
        let mut checked = 0;
        for case in ios_cases {
            let payload = payload_of(case);
            let packet = u32::try_from(case["packet"].as_u64().expect("packet")).expect("u32");
            let expected = hex_bytes(case["out"].as_str().expect("out hex"));
            let framed = framing::encode_ios_le_payload(&payload, packet).expect("ios_le frames");
            assert_eq!(
                framed, expected,
                "ios_le framing diverged from the C vector"
            );
            checked += 1;
        }
        assert!(
            checked > 300,
            "only {checked} ios_le vectors: the sweep shrank"
        );
    }

    fn payload_of(case: &serde_json::Value) -> Vec<u8> {
        case["payload"]
            .as_array()
            .expect("payload array")
            .iter()
            .map(|v| u8::try_from(v.as_u64().expect("payload byte")).expect("u8"))
            .collect()
    }

    #[test]
    fn the_two_radios_frame_identically() {
        // Same command, both framings, from the vectors. If a command reaches a
        // device differently depending on which radio sent it, that is a defect
        // no single-path test sees -- and the SPP path is the one that just
        // changed who does the framing.
        let vectors = c_vectors();
        let basic = &vectors["encode_basic"][2]; // payload [0x46], escape off
        let ios_le = &vectors["encode_ios_le"][0]; // payload [0x46], packet 0
        let bare = frame_command(0x46, &[], Protocol::Basic).expect("basic frames");
        assert_eq!(hex_of(&bare), basic["out"].as_str().expect("out hex"));
        let bare_ios = frame_command(0x46, &[], Protocol::IosLe).expect("ios_le frames");
        assert_eq!(hex_of(&bare_ios), ios_le["out"].as_str().expect("out hex"));
    }

    #[test]
    fn an_oversize_payload_is_masked_not_refused() {
        // Pinned, not wished away. The length field is 16 bits and the encoder
        // takes `length_value`'s low two bytes, so a payload past 64 KB declares
        // a length that does not describe the frame around it. That is the
        // owner's behaviour -- the C did the same, and the vectors cannot show
        // it because no fixture is that large -- so it is asserted here rather
        // than left to be found on a device. A future change that starts
        // REFUSING such a payload is a behaviour change someone should have to
        // notice, and the fix belongs at the caller that should never send one.
        let huge = vec![0u8; 0x1_0000];
        let framed = frame_command(0x46, &huge, Protocol::Basic).expect("basic frames");
        let length_value = huge.len() + 1 + crate::models::MESSAGE_CHECKSUM_LENGTH;
        let declared = u16::from(framed[1]) | (u16::from(framed[2]) << 8);
        assert_eq!(
            usize::from(declared),
            length_value & 0xFFFF,
            "the mask is not where this test says it is"
        );
        // And the consequence, so nobody reads the line above as safety: the
        // frame is far longer than the length it declares.
        assert!(framed.len() > usize::from(declared));
    }

    #[test]
    fn a_write_carries_the_frame_and_nothing_else() {
        let line = write_command_line(0x46, &[], Protocol::Basic).expect("frames");
        assert!(line.ends_with('\n'), "the bridge reads lines");
        let value: Value = serde_json::from_str(line.trim()).expect("valid JSON");
        assert_eq!(value["command"], "write");
        // The C's own bytes for a bare 0x46 in basic framing, read off the
        // committed vectors rather than computed here.
        let vectors = c_vectors();
        let expected = vectors["encode_basic"][2]["out"].as_str().expect("out hex");
        assert_eq!(
            value["frame"].as_str().expect("frame is a string"),
            expected
        );
        // The payload/framing/packet triple the bridge used to be handed is
        // GONE: one message, one meaning, and no second place for the framing to
        // live and disagree with the daemon's.
        assert!(value.get("payload").is_none());
        assert!(value.get("framing").is_none());
        assert!(value.get("packet_number").is_none());
    }

    #[test]
    fn from_the_bridge_needs_a_type() {
        assert!(parse_bridge_message(r#"{"type":"connected","mtu":100}"#).is_ok());
        assert!(parse_bridge_message("not json").is_err());
        assert!(parse_bridge_message("[1,2,3]").is_err());
        assert!(parse_bridge_message(r#"{"mtu":100}"#).is_err());
    }

    #[test]
    fn disconnect_says_only_disconnect() {
        assert_eq!(
            BridgeMessage::Disconnect.to_line().trim(),
            r#"{"command":"disconnect"}"#
        );
    }
}
