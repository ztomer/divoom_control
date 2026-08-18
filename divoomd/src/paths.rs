//! Locate repo-relative resources from the running binary.
//!
//! Callers used to hardcode a parent COUNT: "binary is at
//! divoomd/target/release/divoomd, so 4 parents = project root". That silently
//! broke the moment the build layout changed -- R66 collapsed the two crates
//! into one workspace, so the binary moved to `target/release/divoomd` and the
//! correct count became 3. Nothing failed loudly: `find_encoder_lib()` just
//! returned None (no native encoder, silent fallback) and the SPP bridge path
//! pointed at a file that did not exist.
//!
//! Searching UP for a known marker directory is immune to that whole class. It
//! also handles layouts a fixed count never could -- a shared CARGO_TARGET_DIR,
//! `cargo run`, or an installed .app bundle.

use std::path::{Path, PathBuf};

/// How far up to walk. Deep enough for any plausible target layout, bounded so
/// a binary run from an unrelated location cannot wander to `/`.
const MAX_DEPTH: usize = 8;

/// Walk up from `start` looking for a directory that contains `marker`.
/// Returns that containing directory (the repo root), not the marker itself.
pub fn find_root_containing_from(start: &Path, marker: &str) -> Option<PathBuf> {
    let mut dir = start;
    for _ in 0..MAX_DEPTH {
        let parent = dir.parent()?;
        if parent.join(marker).is_dir() {
            return Some(parent.to_path_buf());
        }
        dir = parent;
    }
    None
}

/// Same, anchored at the running executable.
pub fn find_root_containing(marker: &str) -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    find_root_containing_from(&exe, marker)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build <tmp>/<layout>/divoomd and a sibling marker dir at the fake root,
    /// then assert the search finds the root regardless of how deep the binary
    /// is buried.
    fn layout(tmp: &Path, bin_rel: &str, marker: &str) -> (PathBuf, PathBuf) {
        let root = tmp.join("repo");
        std::fs::create_dir_all(root.join(marker)).unwrap();
        let bin = root.join(bin_rel);
        std::fs::create_dir_all(bin.parent().unwrap()).unwrap();
        std::fs::write(&bin, b"").unwrap();
        (root, bin)
    }

    #[test]
    fn finds_root_for_the_pre_workspace_layout() {
        let tmp = tempfile::tempdir().unwrap();
        let (root, bin) = layout(tmp.path(), "divoomd/target/release/divoomd", "divoom_lib");
        assert_eq!(
            find_root_containing_from(&bin, "divoom_lib").unwrap(),
            root,
            "4-deep layout (what the hardcoded count assumed)"
        );
    }

    #[test]
    fn finds_root_for_the_workspace_layout() {
        // The layout that broke the hardcoded count: one level shallower.
        let tmp = tempfile::tempdir().unwrap();
        let (root, bin) = layout(tmp.path(), "target/release/divoomd", "divoom_lib");
        assert_eq!(find_root_containing_from(&bin, "divoom_lib").unwrap(), root);
    }

    #[test]
    fn finds_root_for_a_deeply_nested_target_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let (root, bin) = layout(
            tmp.path(),
            "target/x86_64-unknown-linux-gnu/release/divoomd",
            "divoom_daemon",
        );
        assert_eq!(
            find_root_containing_from(&bin, "divoom_daemon").unwrap(),
            root
        );
    }

    #[test]
    fn returns_none_when_the_marker_is_absent() {
        let tmp = tempfile::tempdir().unwrap();
        let (_root, bin) = layout(tmp.path(), "target/release/divoomd", "divoom_lib");
        assert!(
            find_root_containing_from(&bin, "no_such_dir").is_none(),
            "must not walk off to / and claim success"
        );
    }
}
