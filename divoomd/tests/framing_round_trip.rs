//! Encode here, parse there: the round trip the vector parity test cannot see.
//!
//! `framing_parity.rs` proves each direction against recorded bytes — the
//! encoder matches what the C library produced, the parser matches what the
//! Python parser returned. Neither test can see a frame that is *consistently*
//! wrong in a way both sides agree on, and that is exactly what a round trip
//! catches: a command byte that moves, an escape that fires and is not undone,
//! a payload that loses its first or last byte.
//!
//! This file used to exist in Python as `tests/test_framing_both_impls.py`,
//! alongside the C library it compared. Both are gone (phase L4), so the
//! property moved here with the implementation rather than being lost with the
//! test file. The inputs are the same dense sweep the vectors use, because the
//! bugs worth catching here are length-dependent ones.

use divoomd::framing::{
    encode_basic_payload, encode_ios_le_payload, parse_basic_protocol_frames,
    parse_ios_le_notification,
};

/// Payloads across the length range the vectors cover, with the escape bytes
/// planted at the front, the middle and the end -- the three positions where a
/// framing bug hides.
fn payloads() -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    for length in 0..=80usize {
        let base: Vec<u8> = (0..length)
            .map(|i| u8::try_from((i * 7 + length) % 251).unwrap_or(0))
            .collect();
        out.push(base.clone());
        if length >= 3 {
            let mut planted = base.clone();
            planted[0] = 0x01;
            planted[length / 2] = 0x02;
            planted[length - 1] = 0x03;
            out.push(planted);
        }
    }
    out
}

#[test]
fn basic_frames_survive_their_own_parser() {
    for payload in payloads() {
        if payload.is_empty() {
            continue; // a Basic frame with no command id has nothing to recover
        }
        // escape=false only, and that is a decision rather than an omission.
        // Escaping expands 0x01/0x02/0x03 into 0x03 0x04 / 0x03 0x05 / 0x03 0x06
        // (see models::ESCAPE_SEQUENCE_*), and NOTHING on this host reverses it:
        // the DEVICE decodes an escaped frame, not our parser. So an escaped
        // frame does not round-trip through `parse_basic_protocol_frames`, and
        // asserting that it does would be asserting a feature nobody uses --
        // while the expansion itself is pinned by
        // `escaping_expands_the_three_special_bytes_and_nothing_else`, which is
        // where the wire contract actually lives.
        let escape = false;
        {
            let frame = encode_basic_payload(&payload, escape);
            let mut buf = frame.clone();
            let messages = parse_basic_protocol_frames(&mut buf);
            assert_eq!(
                messages.len(),
                1,
                "a {len}B payload (escape={escape}) produced {count} messages",
                len = payload.len(),
                count = messages.len()
            );
            let message = &messages[0];
            // `BasicMessage` splits the command id out: `payload` is what
            // FOLLOWS it. The first draft of this test compared the whole
            // payload and failed on a 1-byte frame, which is the parser being
            // right and the test being wrong.
            assert_eq!(
                message.payload,
                payload[1..],
                "payload changed across the round trip (escape={escape}): payload={payload:?} frame={frame:02x?} message={message:?}"
            );
            assert_eq!(message.command_id, payload[0]);
            assert!(buf.is_empty(), "the parser left {} bytes behind", buf.len());
        }
    }
}

#[test]
fn ios_le_frames_survive_their_own_parser() {
    for payload in payloads() {
        if payload.is_empty() {
            continue;
        }
        for packet in [0u32, 1, 0xFF, 0x1234] {
            let frame = encode_ios_le_payload(&payload, packet).expect("non-empty payload");
            let notification = parse_ios_le_notification(&frame)
                .unwrap_or_else(|| panic!("a {}B frame did not parse", payload.len()));
            assert_eq!(notification.command_id, payload[0]);
            assert_eq!(
                notification.packet_number,
                u8::try_from(packet & 0xFF).unwrap(),
                "only the low byte of the packet number is transmitted"
            );
            assert_eq!(
                notification.payload,
                payload[1..],
                "payload changed across the round trip ({}B)",
                payload.len()
            );
        }
    }
}

#[test]
fn escaping_expands_the_three_special_bytes_and_nothing_else() {
    // The wire contract, asserted directly: 0x01/0x02/0x03 each become a
    // 0x03-prefixed pair, and every other byte passes through. The host never
    // un-escapes (the device does), so this is the only place the expansion can
    // be checked -- and getting it wrong corrupts a frame in a way that still
    // has a valid checksum, which is the worst kind of framing bug.
    for (special, expansion) in [
        (0x01u8, [0x03u8, 0x04]),
        (0x02, [0x03, 0x05]),
        (0x03, [0x03, 0x06]),
    ] {
        let frame = encode_basic_payload(&[0x44, special, 0x55], true);
        // start, length, command, expansion, tail, checksum(2), end
        assert_eq!(
            &frame[3..6],
            &[0x44, expansion[0], expansion[1]],
            "0x{special:02x}"
        );
        assert_eq!(frame[6], 0x55, "the byte after the expansion is untouched");
        // Unescaped, the same payload is three bytes longer than the frame body.
        let plain = encode_basic_payload(&[0x44, special, 0x55], false);
        assert_eq!(
            plain.len() + 1,
            frame.len(),
            "escaping adds one byte per special"
        );
    }
    // A payload with no special bytes is byte-identical either way, which is
    // what makes the flag safe to pass unconditionally on the write path.
    let payload = [0x44u8, 0x10, 0x20, 0x30];
    assert_eq!(
        encode_basic_payload(&payload, true),
        encode_basic_payload(&payload, false)
    );
}

#[test]
fn an_ack_shaped_frame_parses_as_an_ack() {
    // A Basic frame whose body is `04 <id> 55` is an acknowledgement, and the
    // parser reads the command id from the SECOND byte for it. That branch is
    // real behaviour on a live path, so it is pinned here rather than avoided
    // by choosing payloads that dodge it -- a test that never produces an ACK
    // cannot tell a correct ACK branch from a missing one.
    let frame = encode_basic_payload(&[0x04, 0x46, 0x55], false);
    let mut buf = frame;
    let messages = parse_basic_protocol_frames(&mut buf);
    assert_eq!(messages.len(), 1);
    assert_eq!(
        messages[0].command_id, 0x46,
        "an ACK frame's id is the middle byte"
    );
    assert!(
        messages[0].payload.is_empty(),
        "an ACK frame carries no payload"
    );
}

#[test]
fn several_frames_in_one_buffer_parse_in_order() {
    // A device answers a burst, and the parser drains a buffer rather than one
    // frame at a time. Getting the ORDER wrong is invisible to a single-frame
    // round trip.
    let commands: Vec<Vec<u8>> = (0..8u8).map(|i| vec![0x08, i, i.wrapping_mul(3)]).collect();
    let mut buf = Vec::new();
    for payload in &commands {
        buf.extend_from_slice(&encode_basic_payload(payload, false));
    }
    let messages = parse_basic_protocol_frames(&mut buf);
    assert_eq!(messages.len(), commands.len());
    for (message, payload) in messages.iter().zip(&commands) {
        assert_eq!(
            message.payload,
            payload[1..],
            "frames came back out of order"
        );
        assert_eq!(message.command_id, payload[0]);
    }
    assert!(buf.is_empty());
}

#[test]
fn a_truncated_trailing_frame_is_kept_not_guessed() {
    // The parser must not invent a message from half a frame: an incomplete
    // tail stays in the buffer for the next read, because guessing is how a
    // device gets told to do something nobody asked for.
    let payload = vec![0x44, 0x00, 0x0A, 0x0A, 0x04];
    let frame = encode_basic_payload(&payload, false);
    let mut buf = frame[..frame.len() - 2].to_vec();
    let messages = parse_basic_protocol_frames(&mut buf);
    assert!(
        messages.is_empty(),
        "a truncated frame parsed as {messages:?}"
    );
    assert!(
        !buf.is_empty(),
        "the partial frame was dropped instead of kept"
    );
    // ...and it parses once the rest arrives.
    buf.extend_from_slice(&frame[frame.len() - 2..]);
    let messages = parse_basic_protocol_frames(&mut buf);
    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].payload, payload[1..]);
    assert_eq!(messages[0].command_id, payload[0]);
}
