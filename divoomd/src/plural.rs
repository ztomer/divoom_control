//! A count meets its noun: `counted(3, "file")` is `3 files`, never the hedge `file(s)`.
//!
//! The house helper is `goh_tui::counted` / `noun` in `gates_of_heck`, and `goh plural-hedge`
//! (GOH.PLURALHEDGE) refuses the hedge in a string literal. The daemon ships in the app bundle and
//! takes no build dependency on goh, so this is its twin with the same contract. Exactly one is
//! singular; the plural defaults to the singular plus `s`.

/// `1 file`, `0 files`, `3 files`.
#[must_use]
pub fn counted(n: usize, singular: &str) -> String {
    format!("{n} {}", noun(n, singular))
}

/// As [`counted`], for a noun whose plural is not the singular plus `s` (`entry`, `entries`).
#[must_use]
pub fn counted_as(n: usize, singular: &str, plural: &str) -> String {
    format!("{n} {}", noun_as(n, singular, plural))
}

/// The noun alone, for a sentence that places the number itself.
#[must_use]
pub fn noun(n: usize, singular: &str) -> String {
    noun_as(n, singular, &format!("{singular}s"))
}

/// As [`noun`], with the plural named.
#[must_use]
pub fn noun_as(n: usize, singular: &str, plural: &str) -> String {
    if n == 1 { singular } else { plural }.to_string()
}
