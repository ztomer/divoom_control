use crate::transport::BleResult;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct MockTransport {
    pub device_name: Arc<Mutex<Option<String>>>,
    pub sent_commands: SentCommands,
    pub simulated_responses: Arc<Mutex<HashMap<u8, Vec<u8>>>>,
}

/// Shared record of every command byte-pair the mock has been asked to send.
type SentCommands = Arc<Mutex<Vec<(u8, Vec<u8>)>>>;

impl MockTransport {
    pub fn new() -> Self {
        Self {
            device_name: Arc::new(Mutex::new(Some("MockDitoo".to_string()))),
            sent_commands: Arc::new(Mutex::new(Vec::new())),
            simulated_responses: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn device_name(&self) -> Option<String> {
        self.device_name.lock().unwrap().clone()
    }

    pub fn set_cached_device_name(&self, name: String) {
        let mut n = self.device_name.lock().unwrap();
        *n = Some(name);
    }

    pub async fn send_command(
        &self,
        command_id: u8,
        args: &[u8],
        _write_with_response: bool,
    ) -> BleResult<()> {
        let mut cmd = self.sent_commands.lock().unwrap();
        cmd.push((command_id, args.to_vec()));
        Ok(())
    }

    pub async fn wait_for_response(&self, command_id: u8, _timeout: Duration) -> Option<Vec<u8>> {
        let resp = self.simulated_responses.lock().unwrap();
        resp.get(&command_id).cloned()
    }

    pub async fn send_command_and_wait(
        &self,
        command_id: u8,
        args: &[u8],
        timeout: Duration,
    ) -> Option<Vec<u8>> {
        let _ = self.send_command(command_id, args, true).await;
        self.wait_for_response(command_id, timeout).await
    }

    pub async fn stream_animation_8b(&self, blob: &[u8]) -> BleResult<bool> {
        let mut cmd = self.sent_commands.lock().unwrap();
        cmd.push((0x8bu8, blob.to_vec()));
        Ok(true)
    }

    pub async fn wait_for_any_response(
        &self,
        command_ids: &[u8],
        timeout: Duration,
    ) -> Option<(u8, Vec<u8>)> {
        for &cid in command_ids {
            if let Some(resp) = self.wait_for_response(cid, timeout).await {
                return Some((cid, resp));
            }
        }
        None
    }
}

impl Default for MockTransport {
    fn default() -> Self {
        Self::new()
    }
}
