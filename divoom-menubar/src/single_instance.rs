//! One `divoom-menubar` per user, and the newest one wins (D.HELPER, P1.18).
//!
//! On 2026-11-02 the owner's menu bar showed TWO Divoom status items: two
//! agents, pid 42068 and pid 30142, from the same binary. The app's only
//! guard was in the GUI -- `pgrep -x divoom-menubar` before spawning one --
//! and `pgrep` EXCLUDES ITS OWN ANCESTORS by default. "Launch Dashboard"
//! makes the GUI a child of the running agent, so the GUI's `pgrep` could not
//! see the very agent that launched it and spawned a second. A guard that
//! lives in one caller is a guard every other caller (a shell, a test, an
//! installer, an older app) walks around.
//!
//! So the rule lives in the binary, where no caller can miss it:
//!
//! * an agent runs only while it holds an exclusive `flock` on
//!   `<run dir>/divoom-menubar.lock` for its whole life (the kernel drops the
//!   lock when the process dies, however it dies, so a crash never strands
//!   it); and
//! * the holder listens on `<run dir>/divoom-menubar.sock`. A new agent that
//!   finds the lock held asks the holder to step down (`replace`), and waits
//!   for the lock. A relaunch or a reinstall therefore REPLACES the agent
//!   instead of adding one -- the newest binary is the one the user just
//!   installed.
//!
//! An incumbent that does not step down within the deadline is not
//! overruled: the new agent refuses to start ([`AcquireError::Incumbent`]),
//! because two status items is the failure this module exists to prevent.

use std::fs::{File, OpenOptions, TryLockError};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The request a new agent sends the incumbent.
const REPLACE: &str = "replace";
/// How often a waiting agent retries the lock and the incumbent's socket.
const RETRY: Duration = Duration::from_millis(50);

/// Why this agent may not run.
#[derive(Debug)]
pub enum AcquireError {
    /// The run directory, the lock file or the socket failed.
    Io(std::io::Error),
    /// Another agent holds the lock and did not step down within this long.
    Incumbent(Duration),
}

impl std::fmt::Display for AcquireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "the single-instance lock failed: {e}"),
            Self::Incumbent(d) => write!(
                f,
                "another divoom-menubar holds the lock and did not step down within {} ms",
                d.as_millis()
            ),
        }
    }
}

impl From<std::io::Error> for AcquireError {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}

/// The lock and the listening socket of the ONE running agent. Keep it alive
/// for the life of the process: dropping it is what lets a successor in.
pub struct Instance {
    lock: File,
    listener: UnixListener,
}

/// The lock file and the socket, in `dir`.
fn paths(dir: &Path) -> (PathBuf, PathBuf) {
    (
        dir.join("divoom-menubar.lock"),
        dir.join("divoom-menubar.sock"),
    )
}

/// Become the one agent: take the lock, asking an incumbent to step down and
/// waiting up to `yield_within` for it to go.
///
/// # Errors
/// [`AcquireError::Incumbent`] when another agent keeps the lock past the
/// deadline; [`AcquireError::Io`] when the run directory or socket fails.
pub fn acquire(dir: &Path, yield_within: Duration) -> Result<Instance, AcquireError> {
    std::fs::create_dir_all(dir)?;
    let (lock_path, sock_path) = paths(dir);
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&lock_path)?;
    let deadline = Instant::now() + yield_within;
    let mut asked = false;
    loop {
        match lock.try_lock() {
            Ok(()) => break,
            Err(TryLockError::Error(e)) => return Err(e.into()),
            Err(TryLockError::WouldBlock) => {}
        }
        // The incumbent may hold the lock a moment before its socket is up,
        // so the request is retried until it is delivered once.
        if !asked {
            asked = ask_to_step_down(&sock_path);
        }
        if Instant::now() >= deadline {
            return Err(AcquireError::Incumbent(yield_within));
        }
        std::thread::sleep(RETRY);
    }
    // The lock is ours, so any socket file left is a dead holder's.
    match std::fs::remove_file(&sock_path) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
    }
    let listener = UnixListener::bind(&sock_path)?;
    Ok(Instance { lock, listener })
}

/// Deliver `replace` to the incumbent and wait for its acknowledgement.
fn ask_to_step_down(sock_path: &Path) -> bool {
    let Ok(mut stream) = UnixStream::connect(sock_path) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
    if writeln!(stream, "{REPLACE}").is_err() {
        return false;
    }
    let mut ack = String::new();
    BufReader::new(stream).read_line(&mut ack).is_ok() && ack.trim() == "ok"
}

impl Instance {
    /// Answer successors on a background thread: on `replace`, acknowledge
    /// and call `step_down`, which must make this process exit. The lock is
    /// held until then, so the successor cannot start early.
    pub fn serve(self, step_down: impl Fn() + Send + 'static) {
        std::thread::spawn(move || {
            let Self { lock, listener } = self;
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { continue };
                let mut line = String::new();
                let mut reader = BufReader::new(&stream);
                if reader.read_line(&mut line).is_err() || line.trim() != REPLACE {
                    continue;
                }
                let _ = writeln!(stream, "ok");
                step_down();
            }
            drop(lock);
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;

    /// A private run directory per test, removed when the test ends.
    struct Dir(PathBuf);
    impl Dir {
        fn path(&self) -> &Path {
            &self.0
        }
    }
    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn dir() -> Dir {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static N: AtomicUsize = AtomicUsize::new(0);
        // /tmp, not $TMPDIR: a unix socket path must fit in 104 bytes.
        let p = PathBuf::from(format!(
            "/tmp/mbsi-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&p);
        Dir(p)
    }

    /// The rule itself: while one agent holds the instance, a second cannot
    /// start -- it is refused, not run beside it.
    #[test]
    fn a_second_agent_is_refused_while_the_first_will_not_step_down() {
        let d = dir();
        let first = acquire(d.path(), Duration::from_millis(200)).expect("first");
        // `first` never serves, so it never steps down.
        match acquire(d.path(), Duration::from_millis(300)) {
            Err(AcquireError::Incumbent(_)) => {}
            Ok(_) => panic!("two agents held the instance at once"),
            Err(e) => panic!("expected Incumbent, got {e}"),
        }
        drop(first);
    }

    /// A relaunch REPLACES the agent: the incumbent is asked to step down, and
    /// the successor runs once it has gone -- never alongside it.
    #[test]
    fn a_new_agent_replaces_the_incumbent() {
        let d = dir();
        let first = acquire(d.path(), Duration::from_millis(200)).expect("first");
        let (asked_tx, asked_rx) = mpsc::channel::<()>();
        let (gone_tx, gone_rx) = mpsc::channel::<()>();
        // Stand-in for the incumbent's process: it holds the instance until
        // it is told to step down, then "exits" (drops it).
        let holder = std::thread::spawn(move || {
            let (stop_tx, stop_rx) = mpsc::channel::<()>();
            // serve() owns the lock; to model the process exiting, the test
            // keeps a second handle it can drop. A real agent exits instead.
            let lock = first.lock.try_clone().expect("clone lock");
            first.serve(move || {
                let _ = stop_tx.send(());
            });
            stop_rx.recv().expect("asked");
            asked_tx.send(()).expect("report");
            lock.unlock().expect("unlock");
            gone_tx.send(()).expect("report");
        });
        let second = acquire(d.path(), Duration::from_secs(3)).expect("second replaces first");
        asked_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("the incumbent was asked to step down");
        gone_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("the incumbent went before the successor ran");
        holder.join().expect("holder");
        drop(second);
    }

    /// A socket file left by a dead agent does not block the next one.
    #[test]
    fn a_dead_agents_socket_does_not_block_the_next() {
        let d = dir();
        std::fs::create_dir_all(d.path()).expect("run dir");
        let (_, sock) = paths(d.path());
        drop(UnixListener::bind(&sock).expect("stale socket"));
        assert!(sock.exists(), "the stale socket file is in place");
        let inst =
            acquire(d.path(), Duration::from_millis(300)).expect("acquire over a stale socket");
        drop(inst);
    }
}
