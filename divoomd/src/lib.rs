//! divoomd — native (Rust) port of the Divoom daemon.
//!
//! Built in parallel to the authoritative Python daemon (`divoom_daemon/`); the
//! Python implementation stays ground truth and this is switched in only at 100%
//! socket + hardware parity. See docs/ROADMAP.md.
//!
//! Phase 2 (protocol core) lands here first: wire framing, then models, the BLE
//! notify/response correlation, and the command queue — each pinned to the Python
//! behavior by parity tests.

pub mod art;
pub mod art_codec;
pub mod art_hot;
pub mod autoprobe;
#[cfg(feature = "ble")]
pub mod ble;
#[cfg(feature = "ble")]
pub mod central;
pub mod cloud;
mod cloud_category;
pub mod cloud_cmds;
mod cloud_photo;
mod cloud_playlist;
pub mod cloud_store;
pub mod command_queue;
pub mod commands;
pub mod daemon;
#[cfg(feature = "ble")]
pub mod daemon_ble;
pub mod daemon_connect;
pub mod daemon_mock;
mod daemon_status;
pub mod device_call;
pub mod framing;
pub mod hot_state;
pub mod image_proc;
pub mod lan;
pub mod live_jobs;
#[cfg(target_os = "macos")]
pub mod macos_notifications;
pub mod mcp;
pub mod mcp_tools;
pub mod media;
pub mod mock_device_tests;
pub mod mock_transport;
pub mod models;
pub mod monthly_best;
pub mod native_encode;
#[cfg(target_os = "macos")]
pub mod notification_db;
#[cfg(target_os = "macos")]
pub mod notification_routing;
pub mod protocol;
pub mod response;
pub mod socket_server;
pub mod spp;
pub mod sync_artwork;
pub mod transport;
pub mod wall;
