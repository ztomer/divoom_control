//! Can this machine produce now-playing data at all — and if not, WHY.
//!
//! Every prerequisite is probed, and a failure names itself. A feature that is
//! silently absent is indistinguishable from one that is broken, and the user
//! is left with a dead widget and no explanation. That is the failure mode this
//! whole round has been about (house rule: honest placeholders — an unavailable
//! state must say why).
//!
//! Probe with `dlopen`, never with a filesystem check: since the dyld shared
//! cache, system libraries are not materialised as files, so `Path::exists` on
//! the framework returns FALSE while `dlopen` succeeds. Getting that backwards
//! disables the feature on a machine where it works perfectly.

use std::path::{Path, PathBuf};

pub const FRAMEWORK_PATH: &str =
    "/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote";
pub const PERL_PATH: &str = "/usr/bin/perl";

/// Why now-playing cannot work here. `None` means it can.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Unavailable {
    NotMacOS,
    /// Apple moved or withdrew the private framework.
    FrameworkMissing,
    /// No system perl — the entitled host the helper needs.
    PerlMissing,
    /// Our own helper dylib was not found (a packaging mistake).
    HelperMissing(PathBuf),
}

impl Unavailable {
    /// A sentence fit to show a user.
    pub fn reason(&self) -> String {
        match self {
            Self::NotMacOS => "now-playing metadata is only available on macOS".into(),
            Self::FrameworkMissing => {
                "this macOS version does not expose the MediaRemote framework".into()
            }
            Self::PerlMissing => {
                format!("the system perl interpreter ({PERL_PATH}) is missing")
            }
            Self::HelperMissing(p) => {
                format!(
                    "the now-playing helper library is not installed (looked for {})",
                    p.display()
                )
            }
        }
    }
}

/// The pure decision, separated from the probing so both directions are
/// testable on one machine (the accept path as well as each reject path).
pub fn evaluate(
    is_macos: bool,
    framework_loads: bool,
    perl_exists: bool,
    helper: Option<&Path>,
) -> Option<Unavailable> {
    if !is_macos {
        return Some(Unavailable::NotMacOS);
    }
    if !framework_loads {
        return Some(Unavailable::FrameworkMissing);
    }
    if !perl_exists {
        return Some(Unavailable::PerlMissing);
    }
    match helper {
        Some(p) if p.exists() => None,
        Some(p) => Some(Unavailable::HelperMissing(p.to_path_buf())),
        None => Some(Unavailable::HelperMissing(PathBuf::from("<unset>"))),
    }
}

/// Does the private framework load in THIS process?
///
/// Loading it is harmless — the helper loads it anyway — and it is the only
/// check that survives the dyld shared cache. Note this says nothing about
/// whether we are ENTITLED to read from it: since macOS 15.4 an unentitled
/// process gets a successful dlopen and a NULL result. Entitlement is exactly
/// what the perl host provides, so it is not probed here.
#[cfg(target_os = "macos")]
pub fn framework_loads() -> bool {
    use std::ffi::CString;
    extern "C" {
        fn dlopen(filename: *const std::os::raw::c_char, flag: i32) -> *mut std::ffi::c_void;
        fn dlclose(handle: *mut std::ffi::c_void) -> i32;
    }
    const RTLD_LAZY: i32 = 1;
    let Ok(path) = CString::new(FRAMEWORK_PATH) else {
        return false;
    };
    unsafe {
        let h = dlopen(path.as_ptr(), RTLD_LAZY);
        if h.is_null() {
            return false;
        }
        dlclose(h);
        true
    }
}

#[cfg(not(target_os = "macos"))]
pub fn framework_loads() -> bool {
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn available_when_every_prerequisite_holds() {
        let helper = std::env::temp_dir(); // exists
        assert_eq!(evaluate(true, true, true, Some(&helper)), None);
    }

    #[test]
    fn each_missing_prerequisite_names_itself() {
        let helper = std::env::temp_dir();
        assert_eq!(
            evaluate(false, true, true, Some(&helper)),
            Some(Unavailable::NotMacOS)
        );
        assert_eq!(
            evaluate(true, false, true, Some(&helper)),
            Some(Unavailable::FrameworkMissing)
        );
        assert_eq!(
            evaluate(true, true, false, Some(&helper)),
            Some(Unavailable::PerlMissing)
        );
    }

    #[test]
    fn a_missing_helper_reports_the_path_it_looked_for() {
        let absent = PathBuf::from("/nonexistent/np_helper.dylib");
        let got = evaluate(true, true, true, Some(&absent));
        assert_eq!(got, Some(Unavailable::HelperMissing(absent.clone())));
        assert!(
            got.unwrap()
                .reason()
                .contains("/nonexistent/np_helper.dylib"),
            "a packaging mistake must say WHERE it looked"
        );
    }

    #[test]
    fn the_first_failed_prerequisite_wins() {
        // Reporting "perl is missing" on a non-macOS box would be nonsense.
        assert_eq!(
            evaluate(false, false, false, None),
            Some(Unavailable::NotMacOS)
        );
    }

    #[test]
    fn every_reason_is_a_sentence_a_user_could_read() {
        for u in [
            Unavailable::NotMacOS,
            Unavailable::FrameworkMissing,
            Unavailable::PerlMissing,
            Unavailable::HelperMissing(PathBuf::from("/x")),
        ] {
            let r = u.reason();
            assert!(r.len() > 20, "too terse to help: {r}");
            assert!(
                !r.contains("None") && !r.contains("Err"),
                "leaked debug output: {r}"
            );
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn the_framework_loads_on_this_machine() {
        // Calibration: if this fails, `framework_loads` is measuring the wrong
        // thing (a filesystem check would fail here while dlopen succeeds).
        assert!(framework_loads(), "MediaRemote must dlopen on macOS");
    }
}
