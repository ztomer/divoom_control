//! Argument parsing for the `divoomd` binary, as a pure function over a slice
//! of strings so both directions are testable without spawning a process.
//!
//! **Why this is a module and not ten lines in `main`.** The old parser had no
//! `--version` and silently IGNORED anything it did not recognise: the `while`
//! loop simply fell through to `i += 1`. So `divoomd --version` did not print a
//! version and exit — it started a daemon on the default socket. Asking the
//! binary what it is was indistinguishable from launching it, which is how a
//! stale `target/release/divoomd` could sit at an old version with no cheap way
//! to notice (see `tools/check_built_binaries.py`).
//!
//! That is the failure-path-no-op class: the branch meant to REFUSE an input
//! was not written at all, so every typo — `--sokcet /tmp/x.sock` — was accepted
//! and served the default socket instead, looking like a daemon that ignored
//! its arguments. Unknown arguments are now a hard error, and a flag that takes
//! a value is an error when the value is missing rather than being dropped.

/// What the caller should do, once the arguments have been read.
#[derive(Debug, PartialEq, Eq)]
pub enum Outcome {
    /// Run the daemon with this configuration.
    Run(Box<ConfigArgs>),
    /// Run the MCP stdio server (`divoomd mcp`).
    Mcp,
    /// Print `divoomd <version>` and exit 0.
    Version,
    /// Print usage and exit 0.
    Help,
    /// Print this message to stderr and exit 2.
    Error(String),
}

#[derive(Debug, Default, PartialEq, Eq)]
pub struct ConfigArgs {
    pub socket_path: String,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub token: Option<String>,
    pub mac: Option<String>,
}

pub const DEFAULT_SOCKET_PATH: &str = "/tmp/divoomd.sock";

pub const USAGE: &str = "\
divoomd — the native Divoom daemon (unix-socket NDJSON protocol).

USAGE:
    divoomd [OPTIONS]
    divoomd mcp                 run the MCP stdio server against a live daemon

OPTIONS:
    --socket <PATH>             unix socket to serve on [default: /tmp/divoomd.sock]
    --host <HOST>               also serve TCP on this host (requires --port and a token)
    --port <PORT>               TCP port, when --host is given
    --token <TOKEN>             shared secret for the TCP listener [env: DIVOOM_DAEMON_TOKEN]
    --mac <MAC>                 preferred device address
    -V, --version               print version and exit
    -h, --help                  print this help and exit

Each option also accepts the --flag=value form.";

/// Parse `args` (WITHOUT the program name) into an [`Outcome`].
///
/// `env_token` is the `DIVOOM_DAEMON_TOKEN` value, passed in rather than read
/// here so the parser stays pure and the environment is testable.
pub fn parse(args: &[String], env_token: Option<String>) -> Outcome {
    // `divoomd mcp` is a subcommand, not a flag, and only in first position.
    if args.first().map(String::as_str) == Some("mcp") {
        return Outcome::Mcp;
    }

    let mut cfg = ConfigArgs {
        socket_path: DEFAULT_SOCKET_PATH.to_string(),
        token: env_token,
        ..Default::default()
    };

    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();

        // Value-taking options, in both `--flag value` and `--flag=value` forms.
        // `take` returns the value and advances past it, or reports the miss.
        let mut take = |name: &str| -> Result<String, String> {
            if let Some(v) = arg.strip_prefix(&format!("{name}=")) {
                return Ok(v.to_string());
            }
            match args.get(i + 1) {
                Some(v) => {
                    i += 1;
                    Ok(v.clone())
                }
                None => Err(format!("divoomd: {name} requires a value")),
            }
        };

        let outcome = if arg == "--version" || arg == "-V" {
            return Outcome::Version;
        } else if arg == "--help" || arg == "-h" {
            return Outcome::Help;
        } else if arg == "--socket" || arg.starts_with("--socket=") {
            take("--socket").map(|v| cfg.socket_path = v)
        } else if arg == "--host" || arg.starts_with("--host=") {
            take("--host").map(|v| cfg.host = Some(v))
        } else if arg == "--port" || arg.starts_with("--port=") {
            // A port that does not parse is an error, not a silent None. The
            // old code did `.parse().ok()`, so `--port notanumber` started a
            // unix-only daemon and never mentioned the TCP listener again.
            match take("--port") {
                Ok(v) => match v.parse::<u16>() {
                    Ok(p) => {
                        cfg.port = Some(p);
                        Ok(())
                    }
                    Err(_) => Err(format!("divoomd: --port expects a number, got {v:?}")),
                },
                Err(e) => Err(e),
            }
        } else if arg == "--token" || arg.starts_with("--token=") {
            take("--token").map(|v| cfg.token = Some(v))
        } else if arg == "--mac" || arg.starts_with("--mac=") {
            take("--mac").map(|v| cfg.mac = Some(v))
        } else {
            Err(format!(
                "divoomd: unknown argument {arg:?}\n\nRun `divoomd --help` for usage."
            ))
        };

        if let Err(msg) = outcome {
            return Outcome::Error(msg);
        }
        i += 1;
    }

    Outcome::Run(Box::new(cfg))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    fn run(items: &[&str]) -> ConfigArgs {
        match parse(&args(items), None) {
            Outcome::Run(c) => *c,
            other => panic!("expected Run, got {other:?}"),
        }
    }

    #[test]
    fn no_args_serves_the_default_socket() {
        assert_eq!(run(&[]).socket_path, DEFAULT_SOCKET_PATH);
    }

    #[test]
    fn socket_accepts_both_forms() {
        assert_eq!(run(&["--socket", "/tmp/a.sock"]).socket_path, "/tmp/a.sock");
        assert_eq!(run(&["--socket=/tmp/b.sock"]).socket_path, "/tmp/b.sock");
    }

    #[test]
    fn every_option_round_trips() {
        let c = run(&[
            "--socket",
            "/tmp/c.sock",
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
            "--token",
            "s3cret",
            "--mac",
            "AA:BB:CC:DD:EE:FF",
        ]);
        assert_eq!(c.socket_path, "/tmp/c.sock");
        assert_eq!(c.host.as_deref(), Some("127.0.0.1"));
        assert_eq!(c.port, Some(8080));
        assert_eq!(c.token.as_deref(), Some("s3cret"));
        assert_eq!(c.mac.as_deref(), Some("AA:BB:CC:DD:EE:FF"));
    }

    #[test]
    fn explicit_token_overrides_the_environment() {
        let out = parse(&args(&["--token", "flag"]), Some("env".into()));
        match out {
            Outcome::Run(c) => assert_eq!(c.token.as_deref(), Some("flag")),
            other => panic!("expected Run, got {other:?}"),
        }
    }

    #[test]
    fn environment_token_is_used_when_no_flag_is_given() {
        match parse(&args(&[]), Some("env".into())) {
            Outcome::Run(c) => assert_eq!(c.token.as_deref(), Some("env")),
            other => panic!("expected Run, got {other:?}"),
        }
    }

    #[test]
    fn version_and_help_are_recognised_in_both_spellings() {
        for a in ["--version", "-V"] {
            assert_eq!(parse(&args(&[a]), None), Outcome::Version, "{a}");
        }
        for a in ["--help", "-h"] {
            assert_eq!(parse(&args(&[a]), None), Outcome::Help, "{a}");
        }
    }

    /// The regression that motivated this module: `--version` used to fall
    /// through the parser and start a daemon on the default socket.
    #[test]
    fn version_wins_over_any_other_argument() {
        assert_eq!(
            parse(&args(&["--socket", "/tmp/x.sock", "--version"]), None),
            Outcome::Version
        );
    }

    #[test]
    fn unknown_arguments_are_rejected_not_ignored() {
        // A typo used to be silently dropped, so this served the DEFAULT socket
        // while appearing to have been told otherwise.
        match parse(&args(&["--sokcet", "/tmp/x.sock"]), None) {
            Outcome::Error(m) => assert!(m.contains("--sokcet"), "{m}"),
            other => panic!("expected Error, got {other:?}"),
        }
    }

    #[test]
    fn a_missing_value_is_an_error_not_a_dropped_flag() {
        match parse(&args(&["--socket"]), None) {
            Outcome::Error(m) => assert!(m.contains("--socket"), "{m}"),
            other => panic!("expected Error, got {other:?}"),
        }
    }

    #[test]
    fn a_non_numeric_port_is_an_error() {
        match parse(&args(&["--port", "http"]), None) {
            Outcome::Error(m) => assert!(m.contains("--port"), "{m}"),
            other => panic!("expected Error, got {other:?}"),
        }
    }

    #[test]
    fn mcp_is_a_subcommand_only_in_first_position() {
        assert_eq!(parse(&args(&["mcp"]), None), Outcome::Mcp);
        // Anywhere else it is just an unrecognised word, and must be refused
        // rather than quietly ignored.
        assert!(matches!(
            parse(&args(&["--socket", "/tmp/x.sock", "mcp"]), None),
            Outcome::Error(_)
        ));
    }
}
