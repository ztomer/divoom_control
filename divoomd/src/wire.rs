//! Narrowing a JSON argument into a protocol field, once, on purpose.
//!
//! Nearly every device command reads its arguments as `i64` (that is what
//! `serde_json` hands back) and writes them into a frame as `u8`, `u16` or
//! `u32`. Written as a bare `as` cast, that conversion WRAPS: `volume: 300`
//! becomes 44 and is sent to the hardware as a real, wrong value. Nothing
//! reports it, and the device has no way to know it was not asked for 44.
//!
//! This crate already knew that. Eighteen call sites had a `.clamp(0, 100)` or
//! `.clamp(1, 255)` in front of the cast, written where somebody thought about
//! the range. A hundred and thirty-five did not -- the same conversion, the
//! same protocol surface, two different behaviours depending on which line you
//! landed on. These helpers make the clamping one the only one.
//!
//! SATURATING, NOT REJECTING. A caller that asks for a brightness of 300 has
//! made a mistake, and the honest answer would arguably be an error. That is a
//! protocol-surface decision affecting every command's contract; clamping is
//! what this crate already did where it thought about it at all, so that is
//! what is made uniform here. Where a field's real range is NARROWER than its
//! width -- brightness is 0..=100, not 0..=255 -- the existing `.clamp()` in
//! front stays and still applies first.

/// Narrow a JSON-sourced integer into a protocol field, saturating.
pub trait WireNarrow {
    /// A one-byte field. Values outside `0..=255` saturate.
    fn byte(self) -> u8;
    /// A two-byte field. Values outside `0..=65_535` saturate.
    fn word(self) -> u16;
    /// A four-byte field. Values outside `0..=u32::MAX` saturate.
    fn dword(self) -> u32;
}

impl WireNarrow for i64 {
    fn byte(self) -> u8 {
        u8::try_from(self.clamp(0, Self::from(u8::MAX))).unwrap_or(u8::MAX)
    }
    fn word(self) -> u16 {
        u16::try_from(self.clamp(0, Self::from(u16::MAX))).unwrap_or(u16::MAX)
    }
    fn dword(self) -> u32 {
        u32::try_from(self.clamp(0, Self::from(u32::MAX))).unwrap_or(u32::MAX)
    }
}

impl WireNarrow for u64 {
    fn byte(self) -> u8 {
        u8::try_from(self.min(Self::from(u8::MAX))).unwrap_or(u8::MAX)
    }
    fn word(self) -> u16 {
        u16::try_from(self.min(Self::from(u16::MAX))).unwrap_or(u16::MAX)
    }
    fn dword(self) -> u32 {
        u32::try_from(self.min(Self::from(u32::MAX))).unwrap_or(u32::MAX)
    }
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
