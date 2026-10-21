//! The stored gallery's rules, pinned: what goes on the wire, and what the
//! device's answer means.
//!
//! Every test here is a RULE the owner's ruling rests on ("art should be
//! stored", 2026-10-21), and every one of them can be checked without a
//! radio, a device or the cloud:
//!
//! * the art that is STORED is the art that was SHOWN — the same frames, in
//!   the device's own encoding;
//! * the page goes on the wire in the app's own form, so the panel reads it
//!   the way the app writes it;
//! * the read-back's answer is read as the app reads it, and an answer this
//!   reader does not know is NAMED rather than guessed at.

use crate::gallery_store::{
    frames_for, page_body, page_end, page_header, page_packets, parse_what_it_holds,
    split_for_page, ArtItem, WhatItHolds,
};
use std::path::PathBuf;

fn raw(name: &str) -> Vec<u8> {
    std::fs::read(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/cloud_fixtures")
            .join(name),
    )
    .expect("fixture")
}

fn item(name: &str, frames: Vec<Vec<u8>>) -> ArtItem {
    ArtItem {
        name: name.to_string(),
        frames,
    }
}

/// The art that is STORED is the art that was SHOWN.
///
/// The show path encodes the panel's frames with the device's own encoder;
/// the store must encode the SAME frames, or the device would hold a
/// different picture than the one that was shown.
#[test]
fn the_stored_frames_are_the_frames_the_device_is_shown() {
    let gif = crate::media::resolve_to_gif(&raw("magic9.bin")).expect("resolve the cloud art");
    let frames = frames_for(&gif).expect("frames for the device");

    assert!(
        frames.len() > 1,
        "an animation must stay an animation in the store: {} frame(s)",
        frames.len()
    );
    for frame in &frames {
        assert_eq!(
            frame.first(),
            Some(&0xAA),
            "every stored frame is in the device's own encoding"
        );
        // AA LLLL(2 LE) TTTT(2 LE) RR NN — the duration is the frame's own.
        // The fixture's art plays at 50 ms a frame, and the store must keep
        // that: a store that flattened every frame to a default would hold a
        // different picture than the one that was shown.
        let duration = u16::from_le_bytes([frame[3], frame[4]]);
        assert_eq!(
            duration, 50,
            "the stored frame keeps the art's own display time"
        );
    }
}

/// A page is its items' frames, one after another.
#[test]
fn a_page_is_the_items_frames_one_after_another() {
    let items = vec![
        item("first", vec![vec![1, 2, 3], vec![4, 5, 6]]),
        item("second", vec![vec![7, 8, 9]]),
    ];
    assert_eq!(
        page_body(&items),
        vec![1, 2, 3, 4, 5, 6, 7, 8, 9],
        "the page is the frames, in order"
    );
}

/// The save goes on the wire in the app's own form.
///
/// The header is `[0x00, 0x00, page]` — the app's `CmdManager.N2` — and the
/// end is `[0x02]`, the app's `K0()`. A different form is a different
/// command, and the panel would not store the page.
#[test]
fn the_save_is_written_the_way_the_app_writes_it() {
    assert_eq!(page_header(0), vec![0x00, 0x00, 0], "the app's page header");
    assert_eq!(
        page_header(2),
        vec![0x00, 0x00, 2],
        "the page is the third byte"
    );
    assert_eq!(page_end(), vec![0x02], "the app's end-of-page signal");
}

/// The packets are `[0x01][len:2 LE][data]`, and the body is split at 256.
#[test]
fn the_page_is_sent_in_the_apps_packets() {
    let body: Vec<u8> = (0..300)
        .map(|i| u8::try_from(i % 251).unwrap_or(0))
        .collect();
    let packets = page_packets(&body);

    assert_eq!(packets.len(), 2, "300 bytes is two packets of 256");
    assert_eq!(packets[0][0], 0x01, "the packet's control word");
    assert_eq!(
        u16::from_le_bytes([packets[0][1], packets[0][2]]),
        256,
        "the packet's length is little-endian"
    );
    assert_eq!(packets[0].len(), 3 + 256);
    assert_eq!(packets[1].len(), 3 + 44, "the last packet carries the rest");
}

/// A run that offers FEWER items than a page must not fall off the end.
///
/// This is a REGRESSION test for a panic in the push path, found by the live
/// run of 2026-10-21: nine items reached the store and `items[12..]` panicked
/// — the run died on the first real device with fewer items than a page.
#[test]
fn fewer_items_than_a_page_are_split_without_panicking() {
    let items: Vec<ArtItem> = (0..9)
        .map(|i| item(&format!("file {i}"), vec![vec![i as u8]]))
        .collect();
    let (fitting, overflow) = split_for_page(&items);
    assert_eq!(fitting.len(), 9, "every item fits a page of twelve");
    assert_eq!(overflow.len(), 0, "and none is left over");
}

/// More items than a page: the ones that do not fit are named, not dropped.
#[test]
fn the_items_that_do_not_fit_a_page_are_the_ones_left_over() {
    let items: Vec<ArtItem> = (0..15)
        .map(|i| item(&format!("file {i}"), vec![vec![i as u8]]))
        .collect();
    let (fitting, overflow) = split_for_page(&items);
    assert_eq!(fitting.len(), 12, "a page holds twelve items");
    assert_eq!(overflow.len(), 3, "the rest are named by the store");
    assert_eq!(overflow[0].name, "file 12", "and they are the last ones");
}

/// The device's answer is read as the app reads it.
#[test]
fn the_read_back_reads_the_ids_the_device_holds() {
    // Type 1: user_index, total, offset, num, then num 4-byte file ids.
    let mut answer = vec![1u8, 0, 2, 0, 0, 0, 2, 0];
    answer.extend_from_slice(&[0x00, 0x00, 0x00, 0x07]);
    answer.extend_from_slice(&[0x00, 0x00, 0x00, 0x09]);

    match parse_what_it_holds(&answer) {
        Some(WhatItHolds::Ids(ids)) => assert_eq!(ids, vec![7, 9]),
        other => panic!("the answer must be the ids the device holds: {other:?}"),
    }
}

/// An empty page says so, and an answer this reader does not know is NAMED.
#[test]
fn an_empty_page_and_an_unknown_answer_are_told_apart() {
    assert_eq!(
        parse_what_it_holds(&[2, 0]),
        Some(WhatItHolds::Empty),
        "type 2 is an empty page"
    );
    assert_eq!(
        parse_what_it_holds(&[9, 0]),
        Some(WhatItHolds::Unknown(9)),
        "an answer this reader does not know is named, not guessed at"
    );
    assert_eq!(
        parse_what_it_holds(&[]),
        None,
        "no answer at all is no answer"
    );
}
