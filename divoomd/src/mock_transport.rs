use crate::transport::BleResult;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct MockTransport {
    pub device_name: Arc<Mutex<Option<String>>>,
    pub sent_commands: SentCommands,
    pub simulated_responses: Arc<Mutex<HashMap<u8, Vec<u8>>>>,
    /// While set, every write fails and no response arrives: the panel a
    /// test needs to drive a handler down its device-failure path (P5.10).
    pub fail_writes: Arc<AtomicBool>,
    /// A test seam: while [`Self::hold_writes`]' guard lives, every write
    /// waits IN FLIGHT -- past the queue and the link's fences, on the wire --
    /// the way a real radio write does while the link drops underneath it.
    write_gate: Arc<tokio::sync::RwLock<()>>,
    /// How many writes are waiting at that gate right now.
    writes_waiting: Arc<AtomicUsize>,
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
            fail_writes: Arc::new(AtomicBool::new(false)),
            write_gate: Arc::new(tokio::sync::RwLock::new(())),
            writes_waiting: Arc::new(AtomicUsize::new(0)),
        }
    }

    /// Hold every later write in flight until the returned guard is dropped.
    pub async fn hold_writes(&self) -> tokio::sync::OwnedRwLockWriteGuard<()> {
        self.write_gate.clone().write_owned().await
    }

    /// Writes waiting in flight at [`Self::hold_writes`]' gate right now.
    #[must_use]
    pub fn writes_waiting(&self) -> usize {
        self.writes_waiting.load(Ordering::SeqCst)
    }

    /// Pass the write gate: immediately unless a test holds it.
    async fn on_the_wire(&self) {
        if self.write_gate.try_read().is_ok() {
            return;
        }
        self.writes_waiting.fetch_add(1, Ordering::SeqCst);
        drop(self.write_gate.read().await);
        self.writes_waiting.fetch_sub(1, Ordering::SeqCst);
    }

    /// Make every later write fail (and no response arrive), or stop doing so.
    pub fn set_failing(&self, failing: bool) {
        self.fail_writes.store(failing, Ordering::SeqCst);
    }

    fn failing(&self) -> bool {
        self.fail_writes.load(Ordering::SeqCst)
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

    /// The mock does no I/O: the command is recorded when the returned future
    /// is first polled, which completes at once unless a test holds the write
    /// gate ([`Self::hold_writes`]). Callers `.await` it exactly like the real
    /// transport's (`transport.rs` matches both arms with one `.await`).
    ///
    /// # Errors
    ///
    /// Only while [`Self::set_failing`] is on; the signature carries the real
    /// transport's error type so the two are interchangeable behind
    /// `DeviceTransport`.
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
        let this = self.clone();
        let args = args.to_vec();
        async move {
            this.on_the_wire().await;
            if this.failing() {
                return Err("mock panel: the write failed (injected)".into());
            }
            this.sent_commands.lock().unwrap().push((command_id, args));
            Ok(())
        }
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
        if self.failing() {
            return std::future::ready(None);
        }
        let resp = self
            .simulated_responses
            .lock()
            .unwrap()
            .get(&command_id)
            .cloned();
        std::future::ready(resp)
    }

    /// The mock's read, in the same three shapes as a real transport's
    /// (P2.8): the panel answered, the panel said nothing, or the LINK is
    /// gone (the mock's `fail_writes`, which is what a dropped link looks
    /// like to a caller).
    pub async fn send_command_and_wait(
        &self,
        command_id: u8,
        args: &[u8],
        timeout: Duration,
    ) -> crate::transport::Read {
        if let Err(e) = self.send_command(command_id, args, true).await {
            return crate::transport::Read::LinkFailed(e.to_string());
        }
        self.wait_for_response(command_id, timeout).await.map_or(
            crate::transport::Read::Silent,
            crate::transport::Read::Answered,
        )
    }

    /// Records the blob as one `0x8b` command; complete at once unless the
    /// write gate is held, like [`Self::send_command`].
    ///
    /// # Errors
    ///
    /// Only while [`Self::set_failing`] is on; the real transport's error
    /// type, for interchangeability.
    ///
    /// # Panics
    ///
    /// If a mutex guarding the shared state is poisoned -- another thread
    /// panicked while holding it.
    pub fn stream_animation_8b(
        &self,
        blob: &[u8],
    ) -> impl std::future::Future<Output = BleResult<bool>> + Send {
        let this = self.clone();
        let blob = blob.to_vec();
        async move {
            this.on_the_wire().await;
            if this.failing() {
                return Err("mock panel: the transfer failed (injected)".into());
            }
            this.sent_commands.lock().unwrap().push((0x8bu8, blob));
            Ok(true)
        }
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
