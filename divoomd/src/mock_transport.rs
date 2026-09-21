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
    #[must_use]
    pub fn new() -> Self {
        Self {
            device_name: Arc::new(Mutex::new(Some("MockDitoo".to_string()))),
            sent_commands: Arc::new(Mutex::new(Vec::new())),
            simulated_responses: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    #[must_use]
    /// # Panics
    ///
    /// If the mutex guarding this value is poisoned -- another thread panicked
    /// while holding it, so the value cannot be trusted.
    pub fn device_name(&self) -> Option<String> {
        self.device_name.lock().unwrap().clone()
    }

    /// # Panics
    ///
    /// If the mutex guarding this value is poisoned -- another thread panicked
    /// while holding it, so the value cannot be trusted.
    pub fn set_cached_device_name(&self, name: String) {
        let mut n = self.device_name.lock().unwrap();
        *n = Some(name);
    }

    /// The mock does no I/O: the command is recorded now and the returned
    /// future is already complete. Callers `.await` it exactly like the real
    /// transport's (`transport.rs` matches both arms with one `.await`).
    ///
    /// # Errors
    ///
    /// Never; the signature carries the real transport's error type so the
    /// two are interchangeable behind `DeviceTransport`.
    ///
    /// # Panics
    ///
    /// If a mutex guarding the shared state is poisoned -- another thread
    /// panicked while holding it.
    pub fn send_command(
        &self,
        command_id: u8,
        args: &[u8],
        _write_with_response: bool,
    ) -> impl std::future::Future<Output = BleResult<()>> + Send {
        self.sent_commands
            .lock()
            .unwrap()
            .push((command_id, args.to_vec()));
        std::future::ready(Ok(()))
    }

    /// The simulated response for `command_id`, if one was staged; complete
    /// immediately, like [`Self::send_command`].
    ///
    /// # Panics
    ///
    /// If the mutex guarding this value is poisoned -- another thread panicked
    /// while holding it, so the value cannot be trusted.
    pub fn wait_for_response(
        &self,
        command_id: u8,
        _timeout: Duration,
    ) -> impl std::future::Future<Output = Option<Vec<u8>>> + Send {
        let resp = self
            .simulated_responses
            .lock()
            .unwrap()
            .get(&command_id)
            .cloned();
        std::future::ready(resp)
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

    /// Records the blob as one `0x8b` command; complete immediately, like
    /// [`Self::send_command`].
    ///
    /// # Errors
    ///
    /// Never; the real transport's error type, for interchangeability.
    ///
    /// # Panics
    ///
    /// If a mutex guarding the shared state is poisoned -- another thread
    /// panicked while holding it.
    pub fn stream_animation_8b(
        &self,
        blob: &[u8],
    ) -> impl std::future::Future<Output = BleResult<bool>> + Send {
        self.sent_commands
            .lock()
            .unwrap()
            .push((0x8bu8, blob.to_vec()));
        std::future::ready(Ok(true))
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
