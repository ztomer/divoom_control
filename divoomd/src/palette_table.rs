//! Colour lookup for the image encoders: the C's 512-slot open-addressing
//! table, mirrored.
//!
//! The C keeps this table (`palette_entry_t table[512]`, Thomas Wang's
//! `hash32`) purely to find an existing colour fast; the index handed back
//! is first-seen order, so the hash cannot affect a single output byte.
//! Split out of `image_encode` when that file hit the 500-line cap —
//! this table is the cohesive unit, with no other reason to change.

/// Slots in the colour lookup table. Mirrors `DIVOOM_HASH_TABLE_SIZE`:
/// a power of two, more than twice the palette cap it serves, so linear
/// probing stays short.
const HASH_TABLE_SIZE: usize = 512;

/// Thomas Wang's 32-bit integer hash, straight from the C (`hash32`
/// there): good distribution for sequential RGB keys, no divides. The
/// wrapping arithmetic is load-bearing — the C relies on wraparound,
/// and debug builds panic on overflow, so plain `+`/`*` would be a
/// debug-only crash.
#[must_use]
const fn hash32(mut x: u32) -> u32 {
    x = (x ^ 0x3D) ^ (x >> 16); // 0x3D is 61, as the C writes it
    x = x.wrapping_add(x << 3);
    x ^= x >> 4;
    x = x.wrapping_mul(0x27d4_eb2d);
    x ^= x >> 15;
    x
}

/// Colour lookup: maps packed RGB to palette index. `u32::MAX` marks an
/// empty slot, which no colour can collide with (keys top out at
/// `0x00FF_FFFF`). The table only FINDS colours fast — indices handed
/// back are first-seen order.
pub(crate) struct ColourTable {
    /// Packed RGB per slot, or `u32::MAX` when empty.
    keys: [u32; HASH_TABLE_SIZE],
    /// Palette index per slot.
    slots: [u8; HASH_TABLE_SIZE],
}

impl ColourTable {
    pub(crate) const fn new() -> Self {
        Self {
            keys: [u32::MAX; HASH_TABLE_SIZE],
            slots: [0; HASH_TABLE_SIZE],
        }
    }

    /// The palette index for this colour, inserting it first if new.
    /// Mirrors `palette_add`: linear probing bounded by the table size.
    /// `None` (the C's `-1`) when a new colour meets a full palette of
    /// `max` entries, or when a full probe finds neither — the latter is
    /// unreachable (at most `max` inserts into 512 slots, and `max` is
    /// 256 everywhere it is called), but refuses rather than looping
    /// forever.
    pub(crate) fn intern(
        &mut self,
        key: u32,
        rgb: [u8; 3],
        palette: &mut Vec<[u8; 3]>,
        max: usize,
    ) -> Option<u8> {
        let mask = HASH_TABLE_SIZE - 1;
        let mut slot = (hash32(key) as usize) & mask;
        for _ in 0..HASH_TABLE_SIZE {
            if self.keys[slot] == u32::MAX {
                if palette.len() >= max {
                    return None;
                }
                let fresh = u8::try_from(palette.len()).ok()?;
                palette.push(rgb);
                self.keys[slot] = key;
                self.slots[slot] = fresh;
                return Some(fresh);
            }
            if self.keys[slot] == key {
                return Some(self.slots[slot]);
            }
            slot = (slot + 1) & mask;
        }
        None
    }
}

impl Default for ColourTable {
    fn default() -> Self {
        Self::new()
    }
}
