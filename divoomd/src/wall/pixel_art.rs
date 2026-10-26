//! Pixel art on a wall: cut one pixel per LED, never rescaled (D14).

impl super::DivoomWall {
    /// `Ok` when pixel art of `w`x`h` covers this wall one pixel per LED:
    /// the canvas is exactly its size, and no slot's cut is rescaled.
    ///
    /// # Errors
    ///
    /// [`crate::art_source::mismatch`] against the canvas, or the slot whose
    /// cut would be squared by a rescale.
    pub fn pixel_art_fits(&self, w: u32, h: u32) -> Result<(), String> {
        let canvas = |v: i32| u32::try_from(v).unwrap_or(0);
        crate::art_source::native(w, h, canvas(self.total_width), canvas(self.total_height))?;
        if self.is_free_form {
            for slot in &self.devices {
                let (cw, ch) = (
                    slot.width.unwrap_or(slot.size),
                    slot.height.unwrap_or(slot.size),
                );
                if (cw, ch) != (slot.size, slot.size) {
                    return Err(format!(
                        "the wall slot {} shows a {cw}x{ch} cut on a {s}x{s} panel; pixel art is \
                         never rescaled to fit a panel",
                        slot.mac,
                        s = slot.size
                    ));
                }
            }
        }
        Ok(())
    }
}
