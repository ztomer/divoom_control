use super::WireNarrow;

#[test]
fn in_range_values_pass_through_unchanged() {
    assert_eq!(0i64.byte(), 0);
    assert_eq!(1i64.byte(), 1);
    assert_eq!(100i64.byte(), 100);
    assert_eq!(255i64.byte(), 255);
    assert_eq!(65_535i64.word(), 65_535);
    assert_eq!(1_000i64.dword(), 1_000);
}

#[test]
#[expect(
    clippy::cast_possible_truncation,
    reason = "the test asserts what the BARE CAST does, next to what the helper does, so the difference is legible where it matters"
)]
fn an_over_range_value_saturates_instead_of_wrapping() {
    // THE POINT. `300 as u8` is 44 -- a real, wrong value that goes to the
    // hardware with nothing to say it was not what was asked for.
    assert_eq!(300i64 as u8, 44, "this is what the bare cast did");
    assert_eq!(300i64.byte(), 255, "and this is what it should do");
    assert_eq!(70_000i64.word(), 65_535);
    assert_eq!(i64::MAX.byte(), 255);
    assert_eq!(i64::MAX.dword(), u32::MAX);
}

#[test]
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "as above: `-1 as u8` is 255, and the test says so out loud"
)]
fn a_negative_value_saturates_to_zero_rather_than_a_large_one() {
    // `-1 as u8` is 255: the maximum, from a caller who asked for less than the
    // minimum. That inversion is the worst reading of the two.
    assert_eq!(-1i64 as u8, 255, "this is what the bare cast did");
    assert_eq!((-1i64).byte(), 0, "and this is what it should do");
    assert_eq!((-300i64).word(), 0);
    assert_eq!(i64::MIN.dword(), 0);
}

#[test]
fn the_unsigned_impl_agrees_on_the_ceiling() {
    assert_eq!(0u64.byte(), 0);
    assert_eq!(255u64.byte(), 255);
    assert_eq!(256u64.byte(), 255);
    assert_eq!(u64::MAX.dword(), u32::MAX);
}
