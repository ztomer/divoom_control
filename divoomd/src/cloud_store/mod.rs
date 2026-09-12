//! Divoom credential persistence.
//!
//! The account email lives in `config.ini` (`[divoom]`), the password in the
//! OS credential store through `secret_store` (or in the file, with a
//! warning, where there is none), and the auth-token cache in
//! `auth_token.json` (see `cache`). Used by `cloud::get_credentials` / `save_credentials`. The `*_with`
//! functions take the path and the backend so tests drive a fake store
//! against a temp file and never touch the host's keychain.

mod cache;
mod ini;

use std::path::{Path, PathBuf};
use std::sync::Once;

pub(crate) use cache::{load_cache, save_cache, save_virtual_device};
pub use ini::Password;

use crate::cloud::config_dir;
use crate::secret_store::{detect, SecretBackend};

pub(crate) fn config_file_path() -> Option<PathBuf> {
    Some(config_dir()?.join("config.ini"))
}

pub(crate) fn cache_file_path() -> Option<PathBuf> {
    Some(config_dir()?.join("auth_token.json"))
}

/// Write `data` to `path` atomically with mode 0600: the one way every
/// credential-bearing file here gets written.
pub(crate) fn write_private(path: &Path, data: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let mut temp_name = path
        .file_name()
        .map(std::ffi::OsStr::to_os_string)
        .unwrap_or_default();
    temp_name.push(".tmp");
    let temp_path = path.with_file_name(temp_name);
    std::fs::write(&temp_path, data).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&temp_path, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(temp_path, path).map_err(|e| e.to_string())?;
    Ok(())
}

fn read_ini(path: &Path) -> (String, String) {
    std::fs::read_to_string(path)
        .map(|c| ini::parse_divoom_section(&c))
        .unwrap_or_default()
}

/// The `[divoom]` email and the password, wherever it lives. ("","") if absent.
pub(crate) fn load_config() -> (String, String) {
    let Some(path) = config_file_path() else {
        return (String::new(), String::new());
    };
    load_config_with(&path, detect().as_deref())
}

/// `load_config` against an explicit file and backend.
///
/// A plaintext password still in the file is moved into the backend the
/// first time it is read and the file copy blanked (v0.37 step 6: the
/// migration happens on READ so an upgrade with no visit to Settings still
/// clears the file). With no backend it stays in the file and says so once.
pub(crate) fn load_config_with(
    path: &Path,
    backend: Option<&dyn SecretBackend>,
) -> (String, String) {
    let (email, file_pw) = read_ini(path);
    let Some(backend) = backend else {
        if !file_pw.is_empty() {
            warn_plaintext_once(path);
        }
        return (email, file_pw);
    };
    if !file_pw.is_empty() {
        migrate(path, &email, &file_pw, backend);
        return (email, file_pw);
    }
    match backend.get() {
        Ok(pw) => (email, pw.unwrap_or_default()),
        Err(e) => {
            eprintln!(
                "[Wrn] {}: {e}; treating the account as signed out",
                backend.label()
            );
            (email, String::new())
        }
    }
}

fn migrate(path: &Path, email: &str, pw: &str, backend: &dyn SecretBackend) {
    if let Err(e) = backend.set(pw) {
        eprintln!(
            "[Wrn] could not move the Divoom password into the {}: {e}; it stays in {}",
            backend.label(),
            path.display()
        );
        return;
    }
    match save_config_at(path, email, Password::Clear) {
        Ok(()) => eprintln!(
            "[Inf] moved the Divoom password from {} into the {}",
            path.display(),
            backend.label()
        ),
        Err(e) => eprintln!(
            "[Wrn] password copied to the {} but {} keeps its copy: {e}",
            backend.label(),
            path.display()
        ),
    }
}

fn warn_plaintext_once(path: &Path) {
    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        eprintln!(
            "[Wrn] no OS credential store on this host: the Divoom password is in plaintext (mode 0600) in {}",
            path.display()
        );
    });
}

/// Store the account.
///
/// Email goes to `[divoom]` in config.ini, PRESERVING every other section
/// (R72 P1.1: the version before wrote the whole file and would have eaten
/// `[gui]`/`[gallery]` on the first save). The password goes to the OS store
/// when there is one.
///
/// An EMPTY password means "keep the stored one". The settings form never
/// re-populates the password field, so a plain re-save submits `""`;
/// overwriting with that erased the credential and the next token expiry
/// silently degraded the account to a guest login.
///
/// # Errors
///
/// When no config directory can be located, the file cannot be written, or
/// the OS store refuses a new password (nothing is written in that case: a
/// refused store never falls back to plaintext).
pub fn save_config(email: &str, password: &str) -> Result<(), String> {
    let path = config_file_path().ok_or("cannot find config directory")?;
    save_config_with(&path, email, password, detect().as_deref())
}

/// `save_config` against an explicit file and backend.
pub(crate) fn save_config_with(
    path: &Path,
    email: &str,
    password: &str,
    backend: Option<&dyn SecretBackend>,
) -> Result<(), String> {
    let Some(backend) = backend else {
        let verb = if password.is_empty() {
            Password::Keep
        } else {
            Password::Set(password)
        };
        return save_config_at(path, email, verb);
    };
    if password.is_empty() {
        // Email-only save: a password still in the file moves over first so
        // the clear below loses nothing; if the store refuses, the file keeps
        // it (no worse than before) and the email still saves.
        let (_, file_pw) = read_ini(path);
        if !file_pw.is_empty() {
            if let Err(e) = backend.set(&file_pw) {
                eprintln!(
                    "[Wrn] could not move the Divoom password into the {}: {e}",
                    backend.label()
                );
                return save_config_at(path, email, Password::Keep);
            }
        }
    } else {
        backend.set(password).map_err(|e| {
            format!(
                "could not store the password in the {}: {e}",
                backend.label()
            )
        })?;
    }
    save_config_at(path, email, Password::Clear)
}

/// The file half of a save: read-modify-write of `[divoom]` at `path`.
pub(crate) fn save_config_at(path: &Path, email: &str, password: Password) -> Result<(), String> {
    let existing = std::fs::read_to_string(path).unwrap_or_default();
    write_private(
        path,
        &ini::merge_divoom_section(&existing, email.trim(), password),
    )
}

#[cfg(test)]
mod tests {
    use super::{load_config_with, save_config_at, save_config_with, Password};
    use crate::secret_store::FakeBackend;

    fn tmp(name: &str) -> std::path::PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!(
            "divoomd_cfg_test_{}_{name}.ini",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&p);
        p
    }

    const PLAIN: &str = "[gui]\ntimeout = 120\n\n[divoom]\nemail = a@b.com\npassword = secret\n";

    // Drives the real read-modify-write against a real file: sabotaging
    // `save_config` to write the whole file left every merge test green.
    #[test]
    fn save_config_at_preserves_other_sections_on_disk() {
        let p = tmp("preserve");
        std::fs::write(&p, PLAIN).unwrap();
        save_config_at(&p, "new@x.com", Password::Set("pw2")).unwrap();
        let after = std::fs::read_to_string(&p).unwrap();
        assert!(
            after.contains("timeout = 120"),
            "settings destroyed: {after}"
        );
        assert!(after.contains("email = new@x.com"), "{after}");
        assert!(after.contains("password = pw2"), "{after}");
        assert!(
            !p.with_extension("ini.tmp").exists(),
            "temp file left behind"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn without_a_store_the_file_keeps_the_password_and_a_blank_save_keeps_it() {
        let p = tmp("nostore");
        std::fs::write(&p, PLAIN).unwrap();
        assert_eq!(
            load_config_with(&p, None),
            ("a@b.com".into(), "secret".into())
        );
        save_config_with(&p, "new@x.com", "", None).unwrap();
        let after = std::fs::read_to_string(&p).unwrap();
        assert!(
            after.contains("password = secret"),
            "credential erased: {after}"
        );
        assert!(after.contains("email = new@x.com"), "{after}");
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn a_plaintext_password_migrates_into_the_store_on_first_read() {
        let p = tmp("migrate");
        std::fs::write(&p, PLAIN).unwrap();
        let store = FakeBackend::empty();
        assert_eq!(
            load_config_with(&p, Some(&store)),
            ("a@b.com".into(), "secret".into())
        );
        assert_eq!(
            store.stored().as_deref(),
            Some("secret"),
            "not moved into the store"
        );
        let after = std::fs::read_to_string(&p).unwrap();
        assert!(
            !after.contains("secret"),
            "plaintext survived the migration: {after}"
        );
        assert!(
            after.contains("email = a@b.com") && after.contains("timeout = 120"),
            "{after}"
        );
        // Second read: nothing left to migrate, the store answers.
        assert_eq!(
            load_config_with(&p, Some(&store)),
            ("a@b.com".into(), "secret".into())
        );
        assert_eq!(
            store.sets.load(std::sync::atomic::Ordering::SeqCst),
            1,
            "migrated twice"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn a_store_that_refuses_leaves_the_file_as_it_was() {
        let p = tmp("refuse");
        std::fs::write(&p, PLAIN).unwrap();
        let store = FakeBackend {
            fail_set: true,
            ..FakeBackend::empty()
        };
        assert_eq!(load_config_with(&p, Some(&store)).1, "secret");
        assert!(std::fs::read_to_string(&p)
            .unwrap()
            .contains("password = secret"));
        // A NEW password the store refuses is not written anywhere.
        assert!(save_config_with(&p, "new@x.com", "pw2", Some(&store)).is_err());
        let after = std::fs::read_to_string(&p).unwrap();
        assert!(
            !after.contains("pw2") && after.contains("a@b.com"),
            "{after}"
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn a_save_with_a_store_never_writes_the_password_to_the_file() {
        let p = tmp("store_save");
        let store = FakeBackend::empty();
        save_config_with(&p, "a@b.com", "hunter2", Some(&store)).unwrap();
        let after = std::fs::read_to_string(&p).unwrap();
        assert!(
            !after.contains("hunter2") && !after.contains("password"),
            "{after}"
        );
        assert_eq!(store.stored().as_deref(), Some("hunter2"));
        assert_eq!(
            load_config_with(&p, Some(&store)),
            ("a@b.com".into(), "hunter2".into())
        );
        // An email-only re-save keeps the stored password.
        save_config_with(&p, "b@c.com", "", Some(&store)).unwrap();
        assert_eq!(
            load_config_with(&p, Some(&store)),
            ("b@c.com".into(), "hunter2".into())
        );
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn an_email_only_save_with_a_store_migrates_a_file_password_first() {
        let p = tmp("email_only");
        std::fs::write(&p, PLAIN).unwrap();
        let store = FakeBackend::empty();
        save_config_with(&p, "new@x.com", "", Some(&store)).unwrap();
        assert_eq!(
            store.stored().as_deref(),
            Some("secret"),
            "file password lost"
        );
        let after = std::fs::read_to_string(&p).unwrap();
        assert!(
            !after.contains("secret") && after.contains("new@x.com"),
            "{after}"
        );
        let _ = std::fs::remove_file(&p);
    }
}
