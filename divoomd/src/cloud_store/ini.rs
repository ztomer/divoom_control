//! The `[divoom]` section of `config.ini`: parse and merge, line by line.
//!
//! Hand-rolled on both sides on purpose: adding an ini crate for the writer
//! while the reader stays bespoke would give one file two parsers with
//! different ideas about it, which is the shape R72 exists to remove.

/// What a save does to the `password` key.
#[derive(Clone, Copy, Debug)]
pub enum Password<'a> {
    /// Leave whatever the file holds (the settings form never re-populates
    /// the field, so a plain re-save must not erase the credential).
    Keep,
    /// Write this value.
    Set(&'a str),
    /// Remove the line: the password lives in the OS store now.
    Clear,
}

/// Read the `[divoom]` email/password from an ini text. Absent keys read as "".
#[must_use]
pub fn parse_divoom_section(content: &str) -> (String, String) {
    let mut email = String::new();
    let mut password = String::new();
    let mut in_divoom_section = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            let section = &trimmed[1..trimmed.len() - 1];
            in_divoom_section = section.eq_ignore_ascii_case("divoom");
        } else if in_divoom_section {
            if let Some(pos) = trimmed.find('=') {
                let key = trimmed[..pos].trim();
                let val = trimmed[pos + 1..].trim();
                if key.eq_ignore_ascii_case("email") {
                    email = val.to_string();
                } else if key.eq_ignore_ascii_case("password") {
                    password = val.to_string();
                }
            }
        }
    }
    (email, password)
}

/// Rewrite only the `email`/`password` keys of `[divoom]`, line by line;
/// every other line and section passes through untouched.
///
/// Hand-rolled to match `load_config` above, which is also hand-rolled: adding
/// an ini crate for the writer while the reader stays bespoke would give one
/// file two parsers with different ideas about it, which is the shape R72
/// exists to remove.
pub fn merge_divoom_section(existing: &str, email: &str, password: Password) -> String {
    let keep_password = matches!(password, Password::Keep);
    let drop_password = matches!(password, Password::Clear);
    let password = match password {
        Password::Set(p) => p,
        Password::Keep | Password::Clear => "",
    };
    let mut out: Vec<String> = Vec::new();
    let mut in_divoom = false;
    let mut saw_section = false;
    let mut wrote_email = false;
    let mut wrote_password = false;

    for line in existing.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            if in_divoom {
                if !wrote_email {
                    out.push(format!("email = {email}"));
                    wrote_email = true;
                }
                if !wrote_password && !keep_password && !drop_password {
                    out.push(format!("password = {password}"));
                    wrote_password = true;
                }
            }
            in_divoom = trimmed[1..trimmed.len() - 1].eq_ignore_ascii_case("divoom");
            saw_section |= in_divoom;
            out.push(line.to_string());
            continue;
        }
        if in_divoom {
            let key = trimmed
                .split('=')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if key == "email" {
                out.push(format!("email = {email}"));
                wrote_email = true;
                continue;
            }
            if key == "password" {
                if keep_password {
                    out.push(line.to_string());
                } else if !drop_password {
                    out.push(format!("password = {password}"));
                }
                wrote_password = true;
                continue;
            }
        }
        out.push(line.to_string());
    }

    if in_divoom {
        if !wrote_email {
            out.push(format!("email = {email}"));
        }
        if !wrote_password && !keep_password && !drop_password {
            out.push(format!("password = {password}"));
        }
    } else if !saw_section {
        if !out.is_empty() && !out.last().is_some_and(std::string::String::is_empty) {
            out.push(String::new());
        }
        out.push("[divoom]".to_string());
        out.push(format!("email = {email}"));
        if !keep_password && !drop_password {
            out.push(format!("password = {password}"));
        }
    }

    let mut joined = out.join("\n");
    joined.push('\n');
    joined
}

#[cfg(test)]
mod merge_tests {
    use super::{merge_divoom_section, Password};

    // These guard a DATA-LOSS path. The version this replaced wrote the whole
    // file as "[divoom]\nemail=..\npassword=..\n", so every other section went
    // with it. Nothing had noticed because no client called it -- the GUI did
    // its own read-modify-write -- and the capability map's verdict was to
    // route the GUI here, which would have eaten the user's settings on the
    // first save.

    #[test]
    fn other_sections_survive() {
        let before = "[gui]\ntimeout = 120\nlimit = 4\n\n\
                      [divoom]\nemail = old@x.com\npassword = secret\n\n\
                      [gallery]\ngallery_sort = 1\n";
        let after = merge_divoom_section(before, "new@x.com", Password::Set("hunter2"));
        assert!(after.contains("[gui]"), "{after}");
        assert!(after.contains("timeout = 120"), "{after}");
        assert!(after.contains("[gallery]"), "{after}");
        assert!(after.contains("gallery_sort = 1"), "{after}");
        assert!(after.contains("email = new@x.com"), "{after}");
        assert!(after.contains("password = hunter2"), "{after}");
    }

    #[test]
    fn an_empty_password_keeps_the_stored_one() {
        // The settings form never re-populates the password field, so a plain
        // re-save submits "". Overwriting with that erased the credential and
        // the next token expiry degraded the account to a guest login.
        let before = "[divoom]\nemail = old@x.com\npassword = secret\n";
        let after = merge_divoom_section(before, "new@x.com", Password::Keep);
        assert!(
            after.contains("password = secret"),
            "password was wiped: {after}"
        );
        assert!(after.contains("email = new@x.com"), "{after}");
        assert!(!after.contains("old@x.com"), "{after}");
    }

    #[test]
    fn a_missing_divoom_section_is_appended_without_touching_the_rest() {
        let before = "[gui]\ntimeout = 120\n";
        let after = merge_divoom_section(before, "a@b.com", Password::Set("pw"));
        assert!(after.contains("[gui]"), "{after}");
        assert!(after.contains("timeout = 120"), "{after}");
        assert!(after.contains("[divoom]"), "{after}");
        assert!(after.contains("email = a@b.com"), "{after}");
    }

    #[test]
    fn an_empty_file_gets_a_whole_section() {
        let after = merge_divoom_section("", "a@b.com", Password::Set("pw"));
        assert!(after.contains("[divoom]"), "{after}");
        assert!(after.contains("email = a@b.com"), "{after}");
        assert!(after.contains("password = pw"), "{after}");
    }

    #[test]
    fn a_divoom_section_missing_a_key_gains_it() {
        let before = "[divoom]\nemail = a@b.com\n\n[gui]\ntimeout = 5\n";
        let after = merge_divoom_section(before, "a@b.com", Password::Set("pw"));
        assert!(after.contains("password = pw"), "{after}");
        assert!(after.contains("[gui]"), "section order broken: {after}");
        assert!(after.contains("timeout = 5"), "{after}");
    }

    #[test]
    fn keys_outside_divoom_are_never_rewritten() {
        let before = "[other]\nemail = do-not-touch\n\n[divoom]\nemail = a@b.com\n";
        let after = merge_divoom_section(before, "new@x.com", Password::Keep);
        assert!(after.contains("email = do-not-touch"), "{after}");
        assert!(after.contains("email = new@x.com"), "{after}");
    }

    #[test]
    fn the_file_ends_with_exactly_one_newline() {
        let after = merge_divoom_section("[divoom]\nemail = a@b.com\n", "b@c.com", Password::Keep);
        assert!(after.ends_with('\n'), "{after:?}");
        assert!(!after.ends_with("\n\n"), "{after:?}");
    }

    #[test]
    fn clear_drops_the_password_line_and_never_writes_one() {
        // The migration to the OS store (v0.37 step 6) blanks the file copy.
        let before = "[gui]\ntimeout = 5\n\n[divoom]\nemail = a@b.com\npassword = secret\n";
        let after = merge_divoom_section(before, "a@b.com", Password::Clear);
        assert!(!after.contains("password"), "plaintext survived: {after}");
        assert!(after.contains("email = a@b.com"), "{after}");
        assert!(after.contains("timeout = 5"), "{after}");
        let fresh = merge_divoom_section("", "a@b.com", Password::Clear);
        assert!(!fresh.contains("password"), "{fresh}");
        assert!(fresh.contains("[divoom]"), "{fresh}");
    }
}
