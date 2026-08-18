//! Serialized device command queue with exclusive-mode locking — a behavioral
//! port of `the archived Python command_queue.py`.
//!
//! This is NOT a line-for-line port: the Python queue bridges thread-based RPC
//! callers onto a single asyncio loop (`run_coroutine_threadsafe` + concurrent
//! futures). In the Rust daemon everything is tokio, so that bridge disappears and
//! the queue is a clean async actor. What IS preserved (and tested) is the
//! observable behavior:
//!
//!   * FIFO ordering of device ops (one at a time);
//!   * exclusive mode: while a session owns the slot, only its matching-token items
//!     dispatch; others wait;
//!   * `acquire_now` rejects a STEAL immediately (the R53.x fix — a lock-acquire is
//!     not routed through the gate it would be blocked by), and is idempotent for
//!     the same token;
//!   * G3 idle auto-release: an owner that goes idle past `exclusive_timeout` is
//!     force-released so the rest of the queue drains;
//!   * per-item timeout: an item that waits longer than its timeout is rejected.
//!
//! A rejected item (timeout, stop, or queue-drop) resolves its receiver to
//! `Err(RecvError)` — i.e. "did not execute". The distinct reason is logged by the
//! caller's layer, mirroring how the daemon treats a failed device op.

use std::collections::VecDeque;
use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tokio::sync::{oneshot, Notify};

type BoxFut = Pin<Box<dyn Future<Output = ()> + Send>>;

/// Why an exclusive acquire was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AcquireError {
    /// A different session already owns the exclusive slot.
    HeldByAnother,
    /// The queue has been stopped.
    Stopped,
}

impl std::fmt::Display for AcquireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AcquireError::HeldByAnother => {
                write!(f, "device is exclusively held by another session")
            }
            AcquireError::Stopped => write!(f, "queue is stopped"),
        }
    }
}

struct Job {
    token: Option<String>,
    run: Box<dyn FnOnce() -> BoxFut + Send>,
    enqueued: Instant,
    timeout: Option<Duration>,
}

struct Inner {
    pending: VecDeque<Job>,
    owner: Option<String>,
    deadline: Option<Instant>,
    stopped: bool,
}

impl Inner {
    fn arm_deadline(&mut self, excl: Option<Duration>) {
        self.deadline = match (excl, &self.owner) {
            (Some(d), Some(_)) => Some(Instant::now() + d),
            _ => None,
        };
    }
}

/// What the worker decided to do this iteration (computed under the lock, acted on
/// after releasing it — the lock is never held across an `.await`).
enum Step {
    Run(Job),
    /// No dispatchable item; wait for a notify, optionally bounded by `deadline`.
    Wait(Option<Duration>),
    /// State changed (e.g. a force-release); re-evaluate immediately.
    Again,
    Stop,
}

#[derive(Clone)]
pub struct CommandQueue {
    inner: Arc<Mutex<Inner>>,
    notify: Arc<Notify>,
    exclusive_timeout: Option<Duration>,
    item_timeout: Option<Duration>,
}

impl CommandQueue {
    /// Create + start the queue. `exclusive_timeout` is the G3 idle-release window;
    /// `item_timeout` rejects an item that waits longer than this before dispatch.
    pub fn new(exclusive_timeout: Option<Duration>, item_timeout: Option<Duration>) -> Self {
        let q = CommandQueue {
            inner: Arc::new(Mutex::new(Inner {
                pending: VecDeque::new(),
                owner: None,
                deadline: None,
                stopped: false,
            })),
            notify: Arc::new(Notify::new()),
            exclusive_timeout,
            item_timeout,
        };
        let worker = q.clone();
        tokio::spawn(async move { worker.run_worker().await });
        q
    }

    /// Submit a device op. Returns a receiver for its result; a dropped/rejected
    /// item resolves the receiver to `Err(RecvError)`.
    pub fn submit<F, T>(&self, token: Option<String>, fut: F) -> oneshot::Receiver<T>
    where
        F: Future<Output = T> + Send + 'static,
        T: Send + 'static,
    {
        let (tx, rx) = oneshot::channel();
        let run: Box<dyn FnOnce() -> BoxFut + Send> = Box::new(move || {
            Box::pin(async move {
                let r = fut.await;
                let _ = tx.send(r);
            })
        });
        {
            let mut g = self.inner.lock().unwrap();
            if !g.stopped {
                g.pending.push_back(Job {
                    token,
                    run,
                    enqueued: Instant::now(),
                    timeout: self.item_timeout,
                });
            }
        }
        self.notify.notify_one();
        rx
    }

    /// Convenience: submit and await the result. `None` means the item did not run.
    pub async fn run<F, T>(&self, token: Option<String>, fut: F) -> Option<T>
    where
        F: Future<Output = T> + Send + 'static,
        T: Send + 'static,
    {
        self.submit(token, fut).await.ok()
    }

    /// Acquire the exclusive slot immediately (OFF the dispatch queue). Rejects a
    /// foreign owner with `HeldByAnother`; idempotent for the same token (re-arms
    /// the idle deadline). This is the steal-reject fix: routing acquire through the
    /// gated queue would block a competing session for the whole idle window and
    /// then let it silently steal.
    pub fn acquire_now(&self, token: &str) -> Result<(), AcquireError> {
        let mut g = self.inner.lock().unwrap();
        if g.stopped {
            return Err(AcquireError::Stopped);
        }
        if let Some(o) = &g.owner {
            if o != token {
                return Err(AcquireError::HeldByAnother);
            }
        }
        g.owner = Some(token.to_string());
        g.arm_deadline(self.exclusive_timeout);
        drop(g);
        self.notify.notify_one();
        Ok(())
    }

    /// Release the exclusive slot if `token` owns it.
    pub fn release(&self, token: &str) {
        let mut g = self.inner.lock().unwrap();
        if g.owner.as_deref() == Some(token) {
            g.owner = None;
            g.deadline = None;
            drop(g);
            self.notify.notify_one();
        }
    }

    /// Current exclusive owner (test/observability helper).
    pub fn owner(&self) -> Option<String> {
        self.inner.lock().unwrap().owner.clone()
    }

    /// Return whether a device op with the given token is allowed to proceed:
    ///   - no exclusive owner → any token allowed
    ///   - exclusive owner matches token → allowed
    ///   - exclusive owner exists and token doesn't match → HeldByAnother
    ///
    /// Called by device_call dispatch BEFORE acquiring the device transport lock,
    /// mirroring Python's `_cmd_queue.run(token, ...)` gate.
    pub fn check_allowed(&self, token: Option<&str>) -> Result<(), AcquireError> {
        let g = self.inner.lock().unwrap();
        if g.stopped {
            return Err(AcquireError::Stopped);
        }
        match &g.owner {
            None => Ok(()),
            Some(o) if token == Some(o.as_str()) => Ok(()),
            Some(_) => Err(AcquireError::HeldByAnother),
        }
    }

    /// Stop the worker; pending items are dropped (their receivers error).
    pub fn stop(&self) {
        {
            let mut g = self.inner.lock().unwrap();
            g.stopped = true;
            g.pending.clear();
        }
        self.notify.notify_one();
    }

    fn next_step(&self) -> Step {
        let mut g = self.inner.lock().unwrap();
        if g.stopped {
            return Step::Stop;
        }
        let now = Instant::now();
        // Expire timed-out items from the FRONT (matches Python). Dropping a Job
        // drops its sender -> the caller's receiver errors ("did not execute").
        while let Some(front) = g.pending.front() {
            let expired = front
                .timeout
                .map(|t| now.duration_since(front.enqueued) >= t)
                .unwrap_or(false);
            if expired {
                g.pending.pop_front();
            } else {
                break;
            }
        }
        if g.pending.is_empty() {
            return Step::Wait(None);
        }
        if let Some(owner) = g.owner.clone() {
            if let Some(idx) = g
                .pending
                .iter()
                .position(|j| j.token.as_deref() == Some(owner.as_str()))
            {
                g.arm_deadline(self.exclusive_timeout); // owner made progress
                return Step::Run(g.pending.remove(idx).unwrap());
            }
            // No item for the owner: honor the idle deadline, else wait for it.
            match g.deadline {
                Some(dl) => {
                    let rem = dl.saturating_duration_since(now);
                    if rem.is_zero() {
                        g.owner = None;
                        g.deadline = None;
                        Step::Again
                    } else {
                        Step::Wait(Some(rem))
                    }
                }
                None => Step::Wait(None),
            }
        } else {
            Step::Run(g.pending.pop_front().unwrap())
        }
    }

    async fn run_worker(self) {
        loop {
            match self.next_step() {
                Step::Stop => break,
                Step::Again => {} // state changed (force-release); re-evaluate now
                Step::Wait(None) => self.notify.notified().await,
                Step::Wait(Some(rem)) => {
                    tokio::select! {
                        _ = self.notify.notified() => {}
                        _ = tokio::time::sleep(rem) => {}
                    }
                }
                Step::Run(job) => {
                    (job.run)().await;
                    // Re-arm the idle deadline on completion (Python parity): a single
                    // long op shouldn't let the deadline lapse mid-session.
                    let mut g = self.inner.lock().unwrap();
                    if g.owner.is_some() {
                        g.arm_deadline(self.exclusive_timeout);
                    }
                }
            }
        }
    }
}
