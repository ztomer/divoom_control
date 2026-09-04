//! LAN transport (Wi-Fi HTTP API) — ported from `divoom_lib/lan_transport.py`.
//! POST `http://{ip}:9000/divoom_api` with `{"Command","LocalToken",...}`.
//!
//! This chunk ports the hardware-independent, bug-prone parts: the request body
//! construction and `validate_response` — the latter being the ACK != success
//! honesty (a REJECTED command comes back HTTP 200 with a non-zero `error_code`,
//! which must be an error, not a silent success). The actual HTTP send (reqwest)
//! is thin glue added in the device-integration phase, where there's a device or
//! mock server to exercise it.

use serde_json::{json, Map, Value};

pub const PORT: u16 = 9000;
pub const PATH: &str = "/divoom_api";

/// A LAN transport target.
#[derive(Debug, Clone)]
pub struct LanTransport {
    pub device_ip: String,
    pub local_token: i64,
}

/// Why a LAN request failed (mirrors what `_validate_lan_response` raises).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LanError {
    /// HTTP status was not 200 (and the body was valid JSON).
    BadStatus { status: u16, command: String },
    /// The response body was not JSON.
    NonJson { command: String, snippet: String },
    /// HTTP 200 but a non-zero `error_code` — the device rejected the command.
    Rejected { code: String, command: String },
    /// Network request failed.
    NetworkError { message: String, command: String },
}

impl std::fmt::Display for LanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LanError::BadStatus { status, command } => {
                write!(f, "device returned HTTP {status} for {command}")
            }
            LanError::NonJson { command, snippet } => {
                write!(f, "device returned non-JSON for {command}: {snippet:?}")
            }
            LanError::Rejected { code, command } => {
                write!(f, "device rejected {command}: error_code={code}")
            }
            LanError::NetworkError { message, command } => {
                write!(f, "LAN request failed for {command}: {message}")
            }
        }
    }
}

impl LanTransport {
    pub fn new(device_ip: impl Into<String>, local_token: i64) -> Self {
        LanTransport {
            device_ip: device_ip.into(),
            local_token,
        }
    }

    pub fn base_url(&self) -> String {
        format!("http://{}:{}{}", self.device_ip, PORT, PATH)
    }

    /// Build the POST body: `{"Command": cmd, "LocalToken": token, ...extra}`.
    /// Extra fields are merged in (command-specific args like `SelectIndex`).
    pub fn build_body(&self, command: &str, extra: Option<Value>) -> Value {
        let mut map = Map::new();
        map.insert("Command".into(), Value::String(command.to_string()));
        map.insert("LocalToken".into(), json!(self.local_token));
        if let Some(Value::Object(extra)) = extra {
            for (k, v) in extra {
                map.insert(k, v);
            }
        }
        Value::Object(map)
    }

    /// POST a JSON command to the device's local HTTP API.
    pub async fn post(&self, command: &str, extra: Option<Value>) -> Result<Value, LanError> {
        let body = self.build_body(command, extra);
        let client = reqwest::Client::new();
        let res = client
            .post(self.base_url())
            .header("Content-Type", "application/json")
            .json(&body)
            .timeout(std::time::Duration::from_secs(5))
            .send()
            .await;

        let resp = match res {
            Ok(r) => r,
            Err(e) => {
                return Err(LanError::NetworkError {
                    message: e.to_string(),
                    command: command.to_string(),
                });
            }
        };

        let status = resp.status().as_u16();
        let text = match resp.text().await {
            Ok(t) => t,
            Err(e) => {
                return Err(LanError::NetworkError {
                    message: format!("failed to read response text: {e}"),
                    command: command.to_string(),
                });
            }
        };

        validate_response(status, &text, command)
    }

    /// Check whether the device is reachable on the LAN.
    pub async fn probe(&self) -> bool {
        match self.post("Channel/GetIndex", None).await {
            Ok(val) => val.is_object(),
            Err(_) => false,
        }
    }
}

/// Validate a Divoom local-API HTTP response. Parse JSON FIRST (so a non-200 with
/// an HTML body reports non-JSON, matching Python's ordering), then reject a
/// non-200 status, then reject a present, non-null, non-zero `error_code`. A
/// missing/null/zero `error_code` (or a non-object body) is tolerated as success.
pub fn validate_response(status: u16, text: &str, command: &str) -> Result<Value, LanError> {
    let result: Value = serde_json::from_str(text).map_err(|_| LanError::NonJson {
        command: command.to_string(),
        snippet: text.chars().take(120).collect(),
    })?;
    if status != 200 {
        return Err(LanError::BadStatus {
            status,
            command: command.to_string(),
        });
    }
    match result.get("error_code") {
        None | Some(Value::Null) => {}
        Some(v) if v.as_i64() == Some(0) => {}
        Some(v) => {
            return Err(LanError::Rejected {
                code: v.to_string(),
                command: command.to_string(),
            })
        }
    }
    Ok(result)
}
