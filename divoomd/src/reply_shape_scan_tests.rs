//! No handler builds a failure reply by hand (P5.10).
//!
//! The runtime sweep (`reply_code_sweep_tests`) reaches what a test can
//! reach without a radio or the network; this scan covers the rest by shape.
//! Outside `error_code.rs`, which owns the reply constructors, non-test
//! source may not:
//!
//! - name `err_reply` (the old code-less constructor);
//! - write a `"success"` key with any value but the literal `true`, in a
//!   `json!` literal, an index assignment or an `insert`.
//!
//! So a failure reply can only come from `err_code`/`err_with`, which take
//! an `ErrorCode`, and a new handler cannot regress the class by habit.

#[cfg(test)]
mod tests {
    use std::path::{Path, PathBuf};

    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        for e in std::fs::read_dir(dir).expect("readable src").flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, out);
            } else if p.extension().is_some_and(|x| x == "rs") {
                out.push(p);
            }
        }
    }

    /// A file that is test code from top to bottom.
    fn is_test_file(p: &Path) -> bool {
        let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        name.ends_with("_tests.rs") || name == "tests.rs" || name == "test_pause.rs"
    }

    /// The lines of `src` that are not inside a `#[cfg(test)]` item, with
    /// their 1-based numbers. Braces are counted naively, which is enough
    /// for this tree (no test item opens a brace inside a string).
    fn production_lines(src: &str) -> Vec<(usize, &str)> {
        let mut out = Vec::new();
        let mut lines = src.lines().enumerate();
        while let Some((n, line)) = lines.next() {
            if line.trim_start().starts_with("#[cfg(test)]") {
                let mut depth: i64 = 0;
                let mut opened = false;
                for (_, l) in lines.by_ref() {
                    depth += i64::try_from(l.matches('{').count()).unwrap_or(0);
                    depth -= i64::try_from(l.matches('}').count()).unwrap_or(0);
                    opened |= l.contains('{');
                    if (opened && depth <= 0) || (!opened && l.trim_end().ends_with(';')) {
                        break;
                    }
                }
                continue;
            }
            out.push((n + 1, line));
        }
        out
    }

    /// Why `line` builds a reply by hand, if it does.
    fn hand_built(line: &str) -> Option<&'static str> {
        let code = line.split("//").next().unwrap_or("");
        if code.contains("err_reply") {
            return Some("names the code-less err_reply");
        }
        let mut rest = code;
        while let Some(i) = rest.find("\"success\"") {
            let after = rest[i + "\"success\"".len()..].trim_start();
            let before = rest[..i].trim_end();
            if let Some(v) = after.strip_prefix(':') {
                if !v.trim_start().starts_with("true") {
                    return Some("a \"success\" key that is not the literal true");
                }
            } else if before.ends_with('[') {
                if let Some(v) = after.strip_prefix("] =") {
                    if !v.starts_with('=') && !v.trim_start().starts_with("json!(true)") {
                        return Some("assigns \"success\" something other than true");
                    }
                }
            } else if after.starts_with('.') || before.ends_with("insert(") {
                return Some("inserts a \"success\" key by hand");
            }
            rest = &rest[i + 1..];
        }
        None
    }

    #[test]
    fn the_scanner_sees_each_hand_built_shape() {
        for bad in [
            "    err_reply(\"x\")",
            "json!({\"success\": false, \"error\": e})",
            "json!({\"success\":ok})",
            "v[\"success\"] = json!(success);",
            "map.insert(\"success\".into(), Value::Bool(false));",
        ] {
            assert!(hand_built(bad).is_some(), "missed: {bad}");
        }
        for fine in [
            "json!({\"success\": true, \"result\": v})",
            "status[\"success\"] = json!(true);",
            "if reply[\"success\"] == json!(false) {",
            "reply.get(\"success\").and_then(Value::as_bool)",
            "// {\"success\": false} is what err_reply used to build",
        ] {
            assert!(hand_built(fine).is_none(), "false alarm: {fine}");
        }
        let src = "fn a() {}\n#[cfg(test)]\nmod tests {\n    json!({\"success\": false});\n}\nfn b() {}\n";
        let kept: Vec<usize> = production_lines(src).iter().map(|(n, _)| *n).collect();
        assert_eq!(kept, vec![1, 6], "test items are skipped, the rest kept");
    }

    #[test]
    fn no_handler_builds_a_failure_reply_by_hand() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut files = Vec::new();
        walk(&root, &mut files);
        assert!(files.len() > 100, "walked the tree: {}", files.len());
        let mut found = Vec::new();
        for f in files.iter().filter(|f| !is_test_file(f)) {
            if f.ends_with("error_code.rs") {
                continue;
            }
            let src = std::fs::read_to_string(f).expect("utf-8 source");
            for (n, line) in production_lines(&src) {
                if let Some(why) = hand_built(line) {
                    let rel = f.strip_prefix(&root).unwrap_or(f);
                    found.push(format!("{}:{n}: {why}: {}", rel.display(), line.trim()));
                }
            }
        }
        assert!(
            found.is_empty(),
            "{} failure replies built without an ErrorCode:\n{}",
            found.len(),
            found.join("\n")
        );
    }
}
