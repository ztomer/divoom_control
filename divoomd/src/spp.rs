//! SPP transport — connects to classic Divoom Bluetooth devices (e.g. Tivoo-Max, older Ditoo)
//! via the `spp_bridge.py` python/IOBluetooth co-process.

use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt};
use tokio::sync::{mpsc, Mutex};

use crate::autoprobe::Protocol;
use crate::response::{self, Frame};

pub struct SppTransport {
    child_stdin: Arc<Mutex<tokio::process::ChildStdin>>,
    rx: Arc<Mutex<mpsc::Receiver<Frame>>>,
    device_name: std::sync::Mutex<Option<String>>,
    protocol: std::sync::Mutex<Protocol>,
}

impl SppTransport {
    pub async fn connect(
        mac: &str,
        device_name: Option<&str>,
        kind: Option<&str>,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let python = std::env::var("DIVOOM_PYTHON").unwrap_or_else(|_| "python3".to_string());

        // Find spp_bridge.py by searching UP for the dir containing
        // divoom_client/, not by counting parents — the count changed when R66
        // made this a workspace crate (target/ moved to the repo root).
        let root = crate::paths::find_root_containing("divoom_client")
            .ok_or("could not locate divoom_client/ from the running binary")?;
        let bridge_path = root.join("divoom_client").join("spp_bridge.py");

        let mut cmd = tokio::process::Command::new(python);
        cmd.args([bridge_path.to_str().unwrap(), "--mac", mac]);
        if let Some(n) = device_name {
            cmd.args(["--name", n]);
        }
        if let Some(k) = kind {
            cmd.args(["--kind", k]);
        }
        cmd.stdin(std::process::Stdio::piped());
        cmd.stdout(std::process::Stdio::piped());
        cmd.stderr(std::process::Stdio::inherit());

        let mut child = cmd.spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or("failed to open stdin of spp_bridge")?;
        let stdout = child
            .stdout
            .take()
            .ok_or("failed to open stdout of spp_bridge")?;

        let (tx, rx) = mpsc::channel::<Frame>(256);
        let connected_notify = Arc::new(tokio::sync::Notify::new());
        let conn_err = Arc::new(Mutex::new(None));

        let conn_clone = connected_notify.clone();
        let conn_err_clone = conn_err.clone();
        tokio::spawn(async move {
            let mut reader = tokio::io::BufReader::new(stdout).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                if let Ok(val) = serde_json::from_str::<Value>(&line) {
                    let ty = val.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if ty == "connected" {
                        conn_clone.notify_one();
                    } else if ty == "disconnected" {
                        let err = val
                            .get("error")
                            .and_then(|v| v.as_str())
                            .unwrap_or("disconnected");
                        *conn_err_clone.lock().await = Some(err.to_string());
                        conn_clone.notify_one();
                        break;
                    } else if ty == "notification" {
                        let cmd_id =
                            val.get("command_id").and_then(|v| v.as_u64()).unwrap_or(0) as u8;
                        let payload: Vec<u8> = val
                            .get("payload")
                            .and_then(|v| serde_json::from_value(v.clone()).ok())
                            .unwrap_or_default();
                        let _ = tx
                            .send(Frame {
                                command_id: cmd_id,
                                payload,
                            })
                            .await;
                    }
                }
            }
        });

        // Wait for connection callback
        tokio::select! {
            _ = connected_notify.notified() => {}
            _ = tokio::time::sleep(Duration::from_secs(12)) => {
                let _ = child.kill().await;
                return Err("SPP connection timeout".into());
            }
        }

        if let Some(ref err) = *conn_err.lock().await {
            let _ = child.kill().await;
            return Err(format!("SPP connection failed: {err}").into());
        }

        // Auto-run probe to set correct framing (SPP defaults to Basic but can be IosLe)
        let transport = Self {
            child_stdin: Arc::new(Mutex::new(stdin)),
            rx: Arc::new(Mutex::new(rx)),
            device_name: std::sync::Mutex::new(device_name.map(|s| s.to_string())),
            protocol: std::sync::Mutex::new(Protocol::Basic),
        };

        Ok(transport)
    }

    pub fn device_name(&self) -> Option<String> {
        self.device_name.lock().unwrap().clone()
    }

    pub fn set_cached_device_name(&self, name: String) {
        *self.device_name.lock().unwrap() = Some(name);
    }

    pub async fn disconnect(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let msg = json!({"command": "disconnect"});
        let mut stdin = self.child_stdin.lock().await;
        let _ = stdin.write_all(format!("{}\n", msg).as_bytes()).await;
        let _ = stdin.flush().await;
        Ok(())
    }

    pub async fn send_command(
        &self,
        command_id: u8,
        args: &[u8],
        _write_with_response: bool,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let mut payload = Vec::with_capacity(1 + args.len());
        payload.push(command_id);
        payload.extend_from_slice(args);

        let framing_str = match *self.protocol.lock().unwrap() {
            Protocol::Basic => "basic",
            Protocol::IosLe => "ios_le",
        };

        let msg = json!({
            "command": "write",
            "payload": payload,
            "framing": framing_str,
            "packet_number": 0
        });

        let mut stdin = self.child_stdin.lock().await;
        stdin.write_all(format!("{}\n", msg).as_bytes()).await?;
        stdin.flush().await?;
        Ok(())
    }

    pub async fn wait_for_response(&self, command_id: u8, timeout: Duration) -> Option<Vec<u8>> {
        let mut rx = self.rx.lock().await;
        response::wait_for_response(&mut rx, command_id, timeout).await
    }

    pub async fn wait_for_any_response(
        &self,
        command_ids: &[u8],
        timeout: Duration,
    ) -> Option<(u8, Vec<u8>)> {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                return None;
            }
            let frame = {
                let mut rx = self.rx.lock().await;
                match tokio::time::timeout(remaining, rx.recv()).await {
                    Ok(Some(f)) => f,
                    _ => return None,
                }
            };
            if command_ids.contains(&frame.command_id) {
                return Some((frame.command_id, frame.payload));
            }
        }
    }

    pub async fn send_command_and_wait(
        &self,
        command_id: u8,
        args: &[u8],
        timeout: Duration,
    ) -> Option<Vec<u8>> {
        let _ = self
            .wait_for_response(command_id, Duration::from_millis(1))
            .await; // drain
        if self.send_command(command_id, args, true).await.is_err() {
            return None;
        }
        self.wait_for_response(command_id, timeout).await
    }

    pub async fn stream_animation_8b(
        &self,
        blob: &[u8],
    ) -> Result<bool, Box<dyn std::error::Error + Send + Sync>> {
        const CMD: u8 = 0x8B;
        const CHUNK_SIZE: usize = 256;

        let file_size = blob.len() as u32;
        if file_size == 0 {
            return Ok(false);
        }

        // Phase 1: START — [CW=0, file_size:4 LE]
        let mut start_args = Vec::with_capacity(5);
        start_args.push(0u8);
        start_args.extend_from_slice(&file_size.to_le_bytes());
        self.send_command(CMD, &start_args, true).await?;

        // Wait for device "ready" ACK
        let mut rx = self.rx.lock().await;
        let deadline = std::time::Instant::now() + Duration::from_millis(2000);
        let mut ready = false;
        loop {
            let remaining = deadline.saturating_duration_since(std::time::Instant::now());
            if remaining.is_zero() {
                break;
            }
            match tokio::time::timeout(remaining, rx.recv()).await {
                Ok(Some(frame)) if frame.command_id == CMD => {
                    if frame.payload.first() == Some(&0) {
                        ready = true;
                        break;
                    }
                }
                _ => break,
            }
        }
        if !ready {
            tokio::time::sleep(Duration::from_millis(500)).await;
        }

        // Phase 2: Chunks stream
        let mut chunk_idx = 0;
        let mut offset = 0;
        while offset < blob.len() {
            let chunk_len = std::cmp::min(CHUNK_SIZE, blob.len() - offset);
            let mut chunk_args = Vec::with_capacity(7 + chunk_len);
            chunk_args.push(1u8); // CW=1
            chunk_args.extend_from_slice(&file_size.to_le_bytes());
            chunk_args.extend_from_slice(&(chunk_idx as u16).to_le_bytes());
            chunk_args.extend_from_slice(&blob[offset..offset + chunk_len]);
            if chunk_len < CHUNK_SIZE {
                chunk_args.resize(7 + CHUNK_SIZE, 0u8);
            }

            self.send_command(CMD, &chunk_args, false).await?;
            offset += CHUNK_SIZE;
            chunk_idx += 1;
            tokio::time::sleep(Duration::from_millis(8)).await;
        }

        // Phase 3: Retransmit listen
        let loop_deadline = std::time::Instant::now() + Duration::from_millis(15000);
        loop {
            let remaining = loop_deadline.saturating_duration_since(std::time::Instant::now());
            if remaining.is_zero() {
                break;
            }
            match tokio::time::timeout(Duration::from_millis(1000), rx.recv()).await {
                Ok(Some(frame)) if frame.command_id == CMD => {
                    if frame.payload.len() >= 3 && frame.payload[0] == 1 {
                        let idx = ((frame.payload[2] as u16) << 8) | (frame.payload[1] as u16);
                        let offset = idx as usize * CHUNK_SIZE;
                        if offset < blob.len() {
                            let chunk_len = std::cmp::min(CHUNK_SIZE, blob.len() - offset);
                            let mut chunk_args = Vec::with_capacity(7 + chunk_len);
                            chunk_args.push(1u8);
                            chunk_args.extend_from_slice(&file_size.to_le_bytes());
                            chunk_args.extend_from_slice(&idx.to_le_bytes());
                            chunk_args.extend_from_slice(&blob[offset..offset + chunk_len]);
                            if chunk_len < CHUNK_SIZE {
                                chunk_args.resize(7 + CHUNK_SIZE, 0u8);
                            }
                            self.send_command(CMD, &chunk_args, false).await?;
                        }
                    }
                }
                Err(_) => {
                    // Silence for 1 s — finished
                    break;
                }
                _ => {}
            }
        }

        Ok(true)
    }
}
