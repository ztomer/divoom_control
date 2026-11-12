//! The DEVICE'S OWN STORED GALLERY — where the art has to END UP.
//!
//! # What "stored" can mean on this protocol
//!
//! The monthly-best push SHOWS the art: it streams an animation to the panel
//! with `0x8B`. That is a TRANSIENT display, and the repo's own comparison of
//! the app's two channels (`docs/CUSTOM_CHANNEL_VS_APK.md`) says so in a
//! table: the `0x8B` path is "Transient display, one-shot", while the app's
//! OTHER path — the custom-art page — is "**Persistent storage, 3×12 slots**".
//!
//! That other path IS the device's stored gallery, and it is three commands:
//!
//! | What | Command | Where it comes from |
//! |---|---|---|
//! | SAVE a page of art | `0xB1` "Set user gif": header `[0x00,0x00,page]`, packets `[0x01][len:2 LE][data]`, end `[0x02]` | `CmdManager.N2` — the app's page writer (`references/apk/.../bluetooth/CmdManager.java`) |
//! | SHOW a stored page | `0xBD [0x17,page]` — "use user define index" | `SPP_SECOND_USE_USER_DEFINE_INDEX` (0x17) |
//! | FORGET a page | `0xBD [0x16,page]` | ditto (0x16) |
//!
//! The app sends the SAVE in its NEW form (`0x8C`, "App new user define")
//! only for the models whose `DeviceFunction.NewAniSendMode2020` is set
//! (`DigitalBadge`, `CyberBag2`, `Dipow*`…). The panels in this house — Pixoo,
//! Ditoo, Tivoo, Timoo — are not among them, so `0xB1` is the form the app
//! itself uses on them.
//! A page holds ITEMS (the app's own model: 12 slots a page), and an item may
//! be an ANIMATION, so a page's wire form is simply its items' frames one
//! after another — the app composes a page out of the very same art gallery
//! this push reads (`LightMakeNewModel`).
//!
//! # What "stored" CANNOT mean here
//!
//! * **Not the cloud's album route.** `Photo/*` (`GetAlbumList`,
//!   `PlayAlbum`, `LocalAddToAlbum`) is the app's photo-FRAME feature: the
//!   album lives in the cloud, the device pulls it, and the commands that
//!   write to a device's own photo store (`Photo/LocalAddToAlbum`) upload a
//!   phone picture over the device's LOCAL HTTP server. The daemon's
//!   `Photo/GetPhotoList` — the "what does it hold" query — TIMES OUT on the
//!   owner's panels (measured 2026-10-21, all four: the panel does not
//!   answer that form), and a 16×16 pixel-art panel is not a photo frame.
//! * **Not the `0x8B` stream.** Streaming is showing.
//!
//! # What can be PROVEN from this side
//!
//! The write is the device's own acknowledgement of each save packet, and
//! that is all. The app's "what is stored" query (`0x8E`, "App get user
//! define info") is answered by no panel in this house -- it timed out on all
//! four (measured 2026-10-21, and the CHANGELOG's 2026-06 finding: "Pixoo
//! never answers the 0x8E user-define read") -- so the read was REMOVED
//! (D.DV1, owner ruling OW.36, 2026-10-31: "drop gallery read, keep local
//! record"). What the device was given is the app's own record: the fetch
//! snapshot (`hotchannel_fetches.json`) and the panel's verdict
//! (`hotchannel_state.json`, `crate::hot_verdict`).
//! `0xBD [0x15]` ("get user define time") does answer, and it says the device
//! HAS a user-define configuration -- it does not say what is in it.

use std::time::Duration;

use crate::daemon::Daemon;
use crate::monthly_best_push::FileFailure;

/// The stored-gallery page the push writes: the device's FIRST page.
///
/// The app gives a device three pages and the user picks one; the push owns
/// page 0 and REPLACES it on every run, which is what "the device holds this
/// month's art" means.
pub const PAGE: u8 = 0;

/// Items (files) a page holds — the app's own page model.
pub const ITEMS_PER_PAGE: usize = 12;

/// "Set user gif" (0xB1) — the app's save path for the panels in this house.
const CMD_SET_USER_GIF: u8 = 0xB1;

/// "Set design" (0xBD) — the extended command that selects a stored page.
const CMD_SET_DESIGN: u8 = 0xBD;

/// Bytes per data packet — the app's `n().q(256)`.
const CHUNK: usize = 256;

/// The gap between packets — the app sleeps 40 ms between them.
const INTER_CHUNK_MS: u64 = 40;

/// One file's art, as the frames the device will hold.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtItem {
    /// The gallery file's name, as the cloud calls it.
    pub name: String,
    /// The device's own frame encoding, one entry per frame.
    pub frames: Vec<Vec<u8>>,
}

/// What the store did.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct StoreOutcome {
    /// Files whose art is in the device's gallery.
    pub stored: usize,
    /// Files the run offered.
    pub offered: usize,
    /// The files that did not make it, and why.
    pub failures: Vec<FileFailure>,
    /// The frames the device holds.
    pub frames: usize,
}

/// Encode resolved pixel art into the frames a `panel`x`panel` device stores.
///
/// The same encoder the SHOW path uses (`image_encode::encode_animation_frame`
/// over `image_proc::prepare`), so the art that is stored is the art that was
/// shown, byte for byte. It is pixel art, so it is stored only on a panel of
/// its own size and never rescaled (D14).
///
/// # Errors
///
/// When the art is not drawn for `panel`, the image cannot be prepared, or a
/// frame cannot be encoded. The message says which.
pub fn frames_for(gif: &[u8], panel: u32) -> Result<Vec<Vec<u8>>, String> {
    let frames = crate::image_proc::prepare(
        gif.to_vec(),
        crate::art_source::Source::PixelArt,
        panel,
        100,
    )
    .map_err(|e| format!("the image could not be prepared for the panel: {e}"))?;
    let mut out = Vec::with_capacity(frames.len());
    for (rgb, w, h, time_ms) in frames {
        out.push(
            crate::image_encode::encode_animation_frame(&rgb, w, h, time_ms)
                .map_err(|why| format!("the frame {w}x{h} could not be encoded: {why}"))?,
        );
    }
    Ok(out)
}

/// The page's wire body: the items' frames, one after another.
///
/// A page holds [`ITEMS_PER_PAGE`] items; the items past that do not fit and
/// are named by the caller.
#[must_use]
pub fn page_body(items: &[ArtItem]) -> Vec<u8> {
    let mut body = Vec::new();
    for item in items {
        for frame in &item.frames {
            body.extend_from_slice(frame);
        }
    }
    body
}

/// The save header: `[0x00, 0x00, page]`.
///
/// The third byte is the PAGE — the app's own page writer sends it
/// (`CmdManager.N2`), and the protocol doc's "Data[0]: 0 for a normal image"
/// is the second byte.
#[must_use]
pub fn page_header(page: u8) -> Vec<u8> {
    vec![0x00, 0x00, page]
}

/// The end-of-page signal: `[0x02]` — the app's `K0()`.
#[must_use]
pub fn page_end() -> Vec<u8> {
    vec![0x02]
}

/// The packets a page's body is sent in: `[0x01][len:2 LE][data]`.
#[must_use]
pub fn page_packets(body: &[u8]) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    for chunk in body.chunks(CHUNK) {
        let mut packet = vec![0x01];
        let len = u16::try_from(chunk.len()).unwrap_or(u16::MAX);
        packet.extend_from_slice(&len.to_le_bytes());
        packet.extend_from_slice(chunk);
        out.push(packet);
    }
    out
}

/// Put the run's art into the device's own gallery.
///
/// The device must be CONNECTED: the save packets go down the link the push
/// opened, and they take the link's queue so a live widget's frame cannot be
/// interleaved into the middle of a page.
///
/// # Errors
///
/// When the device cannot be resolved, has no link, or the queue refuses the
/// permit. The message says which.
pub async fn store(
    daemon: &Daemon,
    target: &str,
    items: &[ArtItem],
) -> Result<StoreOutcome, String> {
    let mut outcome = StoreOutcome {
        offered: items.len(),
        ..StoreOutcome::default()
    };
    if items.is_empty() {
        return Ok(outcome);
    }

    let device = daemon
        .fleet
        .resolve_target(Some(target))
        .await
        .map_err(|e| e.to_string())?;
    let Some(link) = device.link().await else {
        return Err(format!(
            "the device '{target}' has no link to store through"
        ));
    };
    let _permit = link
        .queue
        .acquire(None)
        .await
        .map_err(|e| format!("the device's queue refused the store: {e}"))?;
    let dev = link.transport.clone();
    crate::screen_previews::mark_device_rendered(&device, "gallery_store");

    let (stored, failures) = store_items(&dev, items, &mut outcome).await;
    outcome.stored = stored;
    outcome.failures.extend(failures);
    Ok(outcome)
}

/// The items that fit the device's page, and the ones that do not.
///
/// A page holds [`ITEMS_PER_PAGE`] items. A run that offers FEWER must not
/// fall off the end of the slice: the live run of 2026-10-21 offered nine
/// (one file's container was not readable) and the store panicked on
/// `items[12..]` — a panic in the push path, on the first run that reached
/// the device with fewer items than a page.
#[must_use]
pub fn split_for_page(items: &[ArtItem]) -> (&[ArtItem], &[ArtItem]) {
    let fitting = items.len().min(ITEMS_PER_PAGE);
    (
        &items[..fitting],
        items.get(ITEMS_PER_PAGE..).unwrap_or(&[]),
    )
}

/// Save the items into the device's page, and say what did not fit.
async fn store_items(
    dev: &crate::daemon::DeviceTransport,
    items: &[ArtItem],
    outcome: &mut StoreOutcome,
) -> (usize, Vec<FileFailure>) {
    let mut failures = Vec::new();
    let (fitting, overflow) = split_for_page(items);
    for item in overflow {
        failures.push(FileFailure {
            name: item.name.clone(),
            reason: format!(
                "the device's gallery page holds {} and this run offered more",
                crate::plural::counted(ITEMS_PER_PAGE, "item")
            ),
        });
    }
    if fitting.is_empty() {
        return (0, failures);
    }

    let body = page_body(fitting);
    outcome.frames = fitting.iter().map(|i| i.frames.len()).sum::<usize>();

    // The header, the packets, the end — the app's own order.
    if dev
        .send_command(CMD_SET_USER_GIF, &page_header(PAGE), true)
        .await
        .is_err()
    {
        failures.push(FileFailure {
            name: fitting[0].name.clone(),
            reason: "the device did not take the gallery page's header".to_string(),
        });
        return (0, failures);
    }
    for (index, packet) in page_packets(&body).iter().enumerate() {
        if dev
            .send_command(CMD_SET_USER_GIF, packet, true)
            .await
            .is_err()
        {
            failures.push(FileFailure {
                name: fitting[0].name.clone(),
                reason: format!("the device stopped taking the gallery page at packet {index}"),
            });
            return (0, failures);
        }
        tokio::time::sleep(Duration::from_millis(INTER_CHUNK_MS)).await;
    }
    if dev
        .send_command(CMD_SET_USER_GIF, &page_end(), true)
        .await
        .is_err()
    {
        failures.push(FileFailure {
            name: fitting[0].name.clone(),
            reason: "the device did not take the gallery page's end".to_string(),
        });
        return (0, failures);
    }

    // The page is stored: tell the device to USE it, so the panel shows the
    // art from its own storage rather than a stream that passed by.
    let _ = dev.send_command(CMD_SET_DESIGN, &[0x17, PAGE], true).await;

    (fitting.len(), failures)
}
