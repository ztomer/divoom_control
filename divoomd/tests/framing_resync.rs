//! P1.7: a spurious start byte must not swallow the real frames behind it.
//!
//! `parse_basic_protocol_frames` resyncs one byte at a time when a candidate
//! fails validation. A stray `0x01` whose fake length covers genuine frames
//! behind it used to drain the whole span and lose them instead of re-scanning.
//! The Python twin is `tests/test_framing_resync.py`; the shared vector in
//! `framing_vectors.json` pins both implementations on the same case.

use divoomd::framing::{encode_basic_payload, parse_basic_protocol_frames};

/// A `[0x01, len_lo, len_hi, ...]` header whose span covers both real frames,
/// padded with `0x11` so the fake frame fails the end-byte test.
fn spurious_header_over(first: &[u8], second: &[u8], fake_length: usize) -> Vec<u8> {
    let span = 4 + fake_length;
    let len_lo = u8::try_from(fake_length & 0xFF).expect("masked to a byte");
    let len_hi = u8::try_from(fake_length >> 8).expect("fake length fits sixteen bits");
    let mut buf = vec![0x01, len_lo, len_hi];
    buf.extend_from_slice(first);
    buf.extend_from_slice(second);
    assert!(
        buf.len() <= span,
        "the real frames must fit inside the fake span"
    );
    buf.resize(span, 0x11);
    buf
}

#[test]
fn spurious_start_byte_does_not_swallow_the_frames_behind_it() {
    let first = encode_basic_payload(&[0x46], false);
    let second = encode_basic_payload(&[0x74, 0x3C], false);
    let mut buf = spurious_header_over(&first, &second, 21);
    let messages = parse_basic_protocol_frames(&mut buf);
    let ids: Vec<u8> = messages.iter().map(|m| m.command_id).collect();
    assert_eq!(
        ids,
        vec![0x46, 0x74],
        "the spurious byte swallowed the real frames"
    );
    assert_eq!(messages[0].payload, [] as [u8; 0]);
    assert_eq!(messages[1].payload, vec![0x3C]);
    assert!(
        buf.is_empty(),
        "leftover bytes after the final frame: {buf:?}"
    );
}

#[test]
fn the_real_frames_parse_identically_without_the_spurious_byte() {
    // Guards the test itself: the spurious header must be the ONLY difference,
    // so the same two frames parse from the bare concatenation.
    let first = encode_basic_payload(&[0x46], false);
    let second = encode_basic_payload(&[0x74, 0x3C], false);
    let mut buf = first;
    buf.extend_from_slice(&second);
    let messages = parse_basic_protocol_frames(&mut buf);
    let ids: Vec<u8> = messages.iter().map(|m| m.command_id).collect();
    assert_eq!(ids, vec![0x46, 0x74]);
}
