//! Where the Divoom account password lives (v0.37 step 6).
//!
//! Until 2026-09-12 it sat in plaintext in `config.ini` next to the scan
//! timeout. This is the seam `cloud_store` reads and writes it through: the OS
//! credential store when there is one, the file (with a logged warning) when
//! there is not. `detect()` picks; the two `cloud_store::*_with` functions take
//! the backend as a parameter so tests drive a fake and never touch a real
//! keychain.
//!
//! macOS goes through the `security` CLI rather than the Security framework
//! on purpose: an item's access list names the program that created it, and
//! for the framework that would be the daemon binary, whose code signature
//! changes with every local build (see `scripts/codesign_identity.sh`), so the
//! first read after a rebuild would prompt. The CLI is Apple-signed and stable,
//! so items it creates are readable by it forever without a dialog. Commands
//! go through its stdin mode (`security -i`), which keeps the password off the
//! process argument list. Both were probed on 2026-09-12: `\"` and `\\` are
//! the only escapes it needs, `-U` updates in place, a missing item exits 44.

use std::process::{Command, Stdio};

/// The service (macOS) / attribute (Secret Service) every item carries.
pub const SERVICE: &str = "divoom-control";
/// One Divoom account per daemon, so one fixed account label; the email
/// stays in `config.ini` where the settings form reads it.
pub const ACCOUNT: &str = "divoom-cloud";
/// Forces a backend: `file`, `keychain` or `secret-service`. Tests and
/// headless CI set `file`.
pub const ENV_OVERRIDE: &str = "DIVOOMD_SECRET_BACKEND";

pub trait SecretBackend: Send + Sync {
    /// What Settings shows: "Keychain", "Secret Service".
    fn label(&self) -> &'static str;
    /// The stored password, `None` when nothing is stored.
    ///
    /// # Errors
    ///
    /// When the store cannot be reached (tool missing, locked, denied).
    fn get(&self) -> Result<Option<String>, String>;
    /// Store (or replace) the password.
    ///
    /// # Errors
    ///
    /// When the store refuses the write.
    fn set(&self, secret: &str) -> Result<(), String>;
}

/// The backend for this host, `None` meaning the password stays in the file.
#[must_use]
pub fn detect() -> Option<Box<dyn SecretBackend>> {
    match std::env::var(ENV_OVERRIDE).ok().as_deref() {
        Some("file") => return None,
        Some("keychain") => return Some(Box::new(Keychain)),
        Some("secret-service") => return Some(Box::new(SecretService)),
        _ => {}
    }
    if cfg!(target_os = "macos") {
        Some(Box::new(Keychain))
    } else if cfg!(target_os = "linux") && on_path("secret-tool") {
        Some(Box::new(SecretService))
    } else {
        None
    }
}

/// The label for what `detect()` would use, for status replies.
#[must_use]
pub fn label() -> &'static str {
    detect().map_or("config.ini", |b| b.label())
}

fn on_path(tool: &str) -> bool {
    std::env::var_os("PATH")
        .is_some_and(|p| std::env::split_paths(&p).any(|d| d.join(tool).is_file()))
}

/// macOS login keychain via `security -i`.
pub struct Keychain;

/// Quote for `security -i`'s line parser (probed: `\"` and `\\` only).
fn security_quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        if c == '"' || c == '\\' {
            out.push('\\');
        }
        out.push(c);
    }
    out.push('"');
    out
}

impl SecretBackend for Keychain {
    fn label(&self) -> &'static str {
        "Keychain"
    }

    fn get(&self) -> Result<Option<String>, String> {
        let out = Command::new("/usr/bin/security")
            .args(["find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("security: {e}"))?;
        if out.status.success() {
            let pw = String::from_utf8_lossy(&out.stdout);
            return Ok(Some(pw.trim_end_matches(['\n', '\r']).to_string()));
        }
        // 44 = errSecItemNotFound: nothing stored yet, not a fault.
        if out.status.code() == Some(44) {
            return Ok(None);
        }
        Err(format!(
            "security find-generic-password failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ))
    }

    fn set(&self, secret: &str) -> Result<(), String> {
        if secret.contains(['\n', '\r']) {
            return Err("password cannot contain a line break".to_string());
        }
        let line = format!(
            "add-generic-password -U -s {SERVICE} -a {ACCOUNT} -l \"Divoom cloud account\" -w {}\n",
            security_quote(secret)
        );
        let mut child = Command::new("/usr/bin/security")
            .arg("-i")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("security: {e}"))?;
        if let Some(mut stdin) = child.stdin.take() {
            use std::io::Write;
            stdin
                .write_all(line.as_bytes())
                .map_err(|e| e.to_string())?;
        }
        let out = child.wait_with_output().map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok(())
        } else {
            Err(format!(
                "security add-generic-password failed: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            ))
        }
    }
}

/// Linux Secret Service (GNOME Keyring, the `KWallet` bridge) via `secret-tool`.
pub struct SecretService;

impl SecretBackend for SecretService {
    fn label(&self) -> &'static str {
        "Secret Service"
    }

    fn get(&self) -> Result<Option<String>, String> {
        let out = Command::new("secret-tool")
            .args(["lookup", "service", SERVICE, "account", ACCOUNT])
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("secret-tool: {e}"))?;
        if out.status.success() {
            let pw = String::from_utf8_lossy(&out.stdout);
            let pw = pw.trim_end_matches(['\n', '\r']);
            return Ok((!pw.is_empty()).then(|| pw.to_string()));
        }
        // `lookup` exits 1 with nothing on stdout when no item matches.
        if out.status.code() == Some(1) && out.stderr.is_empty() {
            return Ok(None);
        }
        Err(format!(
            "secret-tool lookup failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        ))
    }

    fn set(&self, secret: &str) -> Result<(), String> {
        let mut child = Command::new("secret-tool")
            .args([
                "store",
                "--label=Divoom cloud account",
                "service",
                SERVICE,
                "account",
                ACCOUNT,
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("secret-tool: {e}"))?;
        if let Some(mut stdin) = child.stdin.take() {
            use std::io::Write;
            stdin
                .write_all(secret.as_bytes())
                .map_err(|e| e.to_string())?;
        }
        let out = child.wait_with_output().map_err(|e| e.to_string())?;
        if out.status.success() {
            Ok(())
        } else {
            Err(format!(
                "secret-tool store failed: {}",
                String::from_utf8_lossy(&out.stderr).trim()
            ))
        }
    }
}

/// An in-memory backend for tests: the seam-and-cover double. Never touches
/// the host's store.
#[cfg(test)]
pub(crate) struct FakeBackend {
    pub(crate) stored: std::sync::Mutex<Option<String>>,
    pub(crate) sets: std::sync::atomic::AtomicUsize,
    pub(crate) fail_set: bool,
}

#[cfg(test)]
impl FakeBackend {
    pub(crate) fn empty() -> Self {
        Self {
            stored: std::sync::Mutex::new(None),
            sets: std::sync::atomic::AtomicUsize::new(0),
            fail_set: false,
        }
    }

    pub(crate) fn stored(&self) -> Option<String> {
        self.stored.lock().unwrap().clone()
    }
}

#[cfg(test)]
impl SecretBackend for FakeBackend {
    fn label(&self) -> &'static str {
        "Fake"
    }

    fn get(&self) -> Result<Option<String>, String> {
        Ok(self.stored())
    }

    fn set(&self, secret: &str) -> Result<(), String> {
        self.sets.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        if self.fail_set {
            return Err("store refused".to_string());
        }
        *self.stored.lock().unwrap() = Some(secret.to_string());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::security_quote;

    #[test]
    fn the_security_quoter_escapes_exactly_what_the_cli_parses() {
        // Probed 2026-09-12 against `security -i`: only `"` and `\` need a
        // backslash; `'`, `$`, `%` and spaces pass through inside quotes.
        assert_eq!(security_quote(r#"p@ss"w'rd it$%"#), r#""p@ss\"w'rd it$%""#);
        assert_eq!(security_quote(r"a\b"), r#""a\\b""#);
        assert_eq!(security_quote(""), r#""""#);
    }
}
