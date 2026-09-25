//! Where the daemon is, and how to authenticate to it.
//!
//! The MCP server used to be reachable in exactly one way: the local unix
//! socket at `DIVOOM_SOCKET`. The Python shell it is replacing also served a
//! REMOTE daemon — `divoom-control mcp-server --host H --port P --token T`, which
//! an editor's MCP config points at when the device is on another machine. That
//! is the one capability the native server lacked, and by the roadmap's own kill
//! criterion it is the thing that would have kept 800 lines of second
//! implementation alive.
//!
//! So the target is selected the same way `divoom_client.daemon_protocol.py`
//! selects it, from the same environment variables, in the same order:
//!
//! 1. `DIVOOM_DAEMON_HOST` set (with `DIVOOM_DAEMON_PORT`, default 9009, and
//!    `DIVOOM_DAEMON_TOKEN`) → TCP;
//! 2. otherwise `DIVOOM_SOCKET` (default `/tmp/divoom.sock`) → unix socket.
//!
//! The wire is the same either way: one NDJSON line per request, with `token`
//! added to the request object when one is configured. That is the daemon's
//! existing contract (`make_request` in `daemon_protocol.py`, and the daemon
//! answers a TCP request without a token with `unauthorized`), so nothing here
//! invents a protocol.

use serde_json::{json, Value};

/// Default TCP port, matching `divoom_client.daemon_protocol.py`.
pub const DEFAULT_TCP_PORT: u16 = 9009;

/// Default unix socket, matching every other default in the project.
pub const DEFAULT_SOCKET: &str = "/tmp/divoom.sock";

/// Which daemon this process talks to, and with what credential.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DaemonTarget {
    /// A local unix socket path.
    Unix(String),
    /// A remote daemon over TCP, optionally requiring a token.
    Remote {
        host: String,
        port: u16,
        token: Option<String>,
    },
}

impl DaemonTarget {
    /// Read the target from the environment, in the order above.
    #[must_use]
    pub fn from_env() -> Self {
        Self::from_env_with(
            std::env::var("DIVOOM_DAEMON_HOST").ok(),
            std::env::var("DIVOOM_DAEMON_PORT").ok(),
            std::env::var("DIVOOM_DAEMON_TOKEN").ok(),
            std::env::var("DIVOOM_SOCKET").ok(),
        )
    }

    /// The selection itself, with the environment read by the caller.
    ///
    /// Split out so the ORDER is testable: precedence between two ways of
    /// naming a daemon is exactly the kind of thing that is right until someone
    /// sets both.
    #[must_use]
    pub fn from_env_with(
        host: Option<String>,
        port: Option<String>,
        token: Option<String>,
        socket: Option<String>,
    ) -> Self {
        // `map_or_else` rather than a `match`: the fallback is the LOCAL case
        // and the closure is the remote one, and reading it that way is how the
        // precedence is obvious. A host wins over a socket, always.
        host.filter(|h| !h.trim().is_empty()).map_or_else(
            || {
                Self::Unix(
                    socket
                        .filter(|s| !s.trim().is_empty())
                        .unwrap_or_else(|| DEFAULT_SOCKET.to_string()),
                )
            },
            |host| Self::Remote {
                host,
                port: port
                    .and_then(|p| p.trim().parse::<u16>().ok())
                    .unwrap_or(DEFAULT_TCP_PORT),
                token: token.filter(|t| !t.is_empty()),
            },
        )
    }

    /// A one-line description for an error message: a path is not a host:port
    /// and a user needs to know which one they got.
    #[must_use]
    pub fn describe(&self) -> String {
        match self {
            Self::Unix(path) => path.clone(),
            Self::Remote { host, port, token } => {
                let auth = if token.is_some() { " (token)" } else { "" };
                format!("{host}:{port}{auth}")
            }
        }
    }

    /// The request object for one command, with the credential attached when
    /// there is one.
    ///
    /// `token` is omitted rather than sent as null when absent, because the
    /// daemon's check is "is there a usable token" and an explicit null is a
    /// different thing to parse than an absent key.
    #[must_use]
    pub fn request(&self, command: &str, args: &Value) -> Value {
        let mut request = json!({ "command": command, "args": args.clone() });
        let token = match self {
            Self::Remote {
                token: Some(token), ..
            } => Some(token.clone()),
            _ => None,
        };
        if let Some(token) = token {
            request["token"] = json!(token);
        }
        request
    }

    /// The request as the NDJSON line the daemon reads.
    ///
    /// # Errors
    ///
    /// If the request cannot be serialised, which for these shapes cannot
    /// happen; the error is a string because the caller is a line-oriented
    /// transport that reports failures as text.
    pub fn request_line(&self, command: &str, args: &Value) -> Result<Vec<u8>, String> {
        let mut line = serde_json::to_vec(&self.request(command, args))
            .map_err(|e| format!("could not encode request: {e}"))?;
        line.push(b'\n');
        Ok(line)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_local_install_is_a_unix_socket() {
        assert_eq!(
            DaemonTarget::from_env_with(None, None, None, None),
            DaemonTarget::Unix(DEFAULT_SOCKET.to_string())
        );
        assert_eq!(
            DaemonTarget::from_env_with(None, None, None, Some("/tmp/other.sock".into())),
            DaemonTarget::Unix("/tmp/other.sock".to_string())
        );
    }

    #[test]
    fn a_host_selects_tcp_and_beats_the_socket() {
        // Precedence is the whole test: a stale DIVOOM_SOCKET in the
        // environment must not silently point an editor's MCP config at the
        // wrong machine.
        let target = DaemonTarget::from_env_with(
            Some("192.168.1.50".into()),
            Some("9100".into()),
            Some("secret".into()),
            Some("/tmp/divoom.sock".into()),
        );
        assert_eq!(
            target,
            DaemonTarget::Remote {
                host: "192.168.1.50".into(),
                port: 9100,
                token: Some("secret".into()),
            }
        );
        assert_eq!(target.describe(), "192.168.1.50:9100 (token)");
    }

    #[test]
    fn a_host_with_nothing_else_still_gets_the_default_port() {
        match DaemonTarget::from_env_with(Some("divoom.local".into()), None, None, None) {
            DaemonTarget::Remote { host, port, token } => {
                assert_eq!(host, "divoom.local");
                assert_eq!(port, DEFAULT_TCP_PORT);
                assert_eq!(token, None);
            }
            DaemonTarget::Unix(path) => panic!("expected a remote target, got unix {path}"),
        }
    }

    #[test]
    fn a_blank_host_is_not_a_host() {
        // An exported-but-empty variable is the same as unset for this
        // decision; treating "" as a hostname would produce a connection to
        // nowhere with a confusing error.
        assert!(matches!(
            DaemonTarget::from_env_with(Some("  ".into()), None, None, None),
            DaemonTarget::Unix(_)
        ));
    }

    #[test]
    fn an_unparseable_port_falls_back_rather_than_refusing() {
        // A typo'd port should reach the default and fail at connect with a
        // comprehensible message, not refuse to start.
        match DaemonTarget::from_env_with(Some("h".into()), Some("not-a-port".into()), None, None) {
            DaemonTarget::Remote { port, .. } => assert_eq!(port, DEFAULT_TCP_PORT),
            unexpected @ DaemonTarget::Unix(_) => {
                panic!("expected a remote target, got {unexpected:?}")
            }
        }
    }

    #[test]
    fn the_token_is_in_the_request_and_only_when_there_is_one() {
        let remote = DaemonTarget::Remote {
            host: "h".into(),
            port: 1,
            token: Some("secret".into()),
        };
        let with_token = remote.request("ping", &json!({}));
        assert_eq!(with_token["token"], json!("secret"));

        let anonymous = DaemonTarget::Remote {
            host: "h".into(),
            port: 1,
            token: None,
        };
        let without = anonymous.request("ping", &json!({}));
        assert!(
            without.get("token").is_none(),
            "an absent token must be absent, not null: {without}"
        );

        // A local socket never carries one — the daemon is the same user.
        let local = DaemonTarget::Unix("/tmp/s".into());
        assert!(local.request("ping", &json!({})).get("token").is_none());
    }

    #[test]
    fn the_request_line_is_ndjson() {
        let line = DaemonTarget::Unix("/tmp/s".into())
            .request_line("device_call", &json!({ "command": "set volume" }))
            .expect("encodes");
        assert_eq!(line.last(), Some(&b'\n'), "one NDJSON line per request");
        assert!(
            !line[..line.len() - 1].contains(&b'\n'),
            "no embedded newline"
        );
        // The parsed shape, not a literal: `serde_json::Value` orders map keys
        // itself, and the daemon parses JSON rather than reading bytes, so key
        // order is an implementation detail of the serializer. The first draft
        // of this test pinned it and failed on a cosmetic difference.
        let parsed: Value =
            serde_json::from_slice(&line[..line.len() - 1]).expect("the line is JSON");
        assert_eq!(parsed["command"], json!("device_call"));
        assert_eq!(parsed["args"]["command"], json!("set volume"));
    }
}
