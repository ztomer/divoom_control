//! A frame sequence as a `data:` URL the GUI can show as-is.
//!
//! One place encodes a preview of what a panel was sent: a live job's frame
//! (`live_jobs/frame.rs`) and each wall slot's cut (`wall/previews.rs`, P6.5)
//! both come here, so a preview is always the frames themselves, never a
//! second rendering of the source.

use base64::Engine as _;

use crate::image_proc::Frame;

/// One frame as a PNG, several as a looping GIF with each frame's delay;
/// `None` for no frames or a buffer that is not `w * h * 3` bytes.
#[must_use]
pub fn data_url(frames: &[Frame]) -> Option<String> {
    let ((rgb, w, h, _), rest) = frames.split_first()?;
    let (wu, hu) = (u32::try_from(*w).ok()?, u32::try_from(*h).ok()?);
    let (mime, bytes) = if rest.is_empty() {
        let img = image::RgbImage::from_raw(wu, hu, rgb.clone())?;
        let mut png = std::io::Cursor::new(Vec::new());
        img.write_to(&mut png, image::ImageFormat::Png).ok()?;
        ("image/png", png.into_inner())
    } else {
        let timed: Vec<(Vec<u8>, u32)> = frames
            .iter()
            .map(|(rgb, _, _, t)| (rgb.clone(), u32::from(*t)))
            .collect();
        (
            "image/gif",
            crate::media::encode_frames_to_gif(&timed, wu, hu)?,
        )
    };
    Some(format!(
        "data:{mime};base64,{}",
        base64::engine::general_purpose::STANDARD.encode(bytes)
    ))
}
