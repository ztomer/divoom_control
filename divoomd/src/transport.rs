#[cfg(feature = "ble")]
use crate::ble::BleTransport;

/// Shared device-I/O result type. Defined here (not in the ble-gated `ble`
/// module) so the transport method layer + MockTransport build without BLE;
/// `crate::ble` re-exports it for back-compat.
pub type BleResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub enum DeviceTransport {
    #[cfg(feature = "ble")]
    Ble(BleTransport),
    Spp(crate::spp::SppTransport),
    Lan(crate::lan::LanTransport),
    Mock(crate::mock_transport::MockTransport),
}

impl DeviceTransport {
    pub fn device_name(&self) -> Option<String> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.device_name(),
            DeviceTransport::Spp(s) => s.device_name(),
            DeviceTransport::Lan(_) => None,
            DeviceTransport::Mock(m) => m.device_name(),
        }
    }

    pub fn set_cached_device_name(&self, _name: String) {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.set_cached_device_name(_name),
            DeviceTransport::Spp(s) => s.set_cached_device_name(_name),
            DeviceTransport::Lan(_) => {}
            DeviceTransport::Mock(m) => m.set_cached_device_name(_name),
        }
    }

    pub async fn send_command(
        &self,
        command_id: u8,
        args: &[u8],
        write_with_response: bool,
    ) -> BleResult<()> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.send_command(command_id, args, write_with_response).await,
            DeviceTransport::Spp(s) => s
                .send_command(command_id, args, write_with_response)
                .await
                .map_err(|e| e.to_string().into()),
            DeviceTransport::Lan(_) => Err("send_command not supported on LAN".into()),
            DeviceTransport::Mock(m) => m.send_command(command_id, args, write_with_response).await,
        }
    }

    pub async fn wait_for_response(
        &self,
        command_id: u8,
        timeout: std::time::Duration,
    ) -> Option<Vec<u8>> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.wait_for_response(command_id, timeout).await,
            DeviceTransport::Spp(s) => s.wait_for_response(command_id, timeout).await,
            DeviceTransport::Lan(_) => None,
            DeviceTransport::Mock(m) => m.wait_for_response(command_id, timeout).await,
        }
    }

    pub async fn send_command_and_wait(
        &self,
        command_id: u8,
        args: &[u8],
        timeout: std::time::Duration,
    ) -> Option<Vec<u8>> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.send_command_and_wait(command_id, args, timeout).await,
            DeviceTransport::Spp(s) => s.send_command_and_wait(command_id, args, timeout).await,
            DeviceTransport::Lan(_) => None,
            DeviceTransport::Mock(m) => m.send_command_and_wait(command_id, args, timeout).await,
        }
    }

    pub async fn stream_animation_8b(&self, blob: &[u8]) -> BleResult<bool> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.stream_animation_8b(blob).await,
            DeviceTransport::Spp(s) => s
                .stream_animation_8b(blob)
                .await
                .map_err(|e| e.to_string().into()),
            DeviceTransport::Lan(_) => Err("stream_animation_8b not supported on LAN".into()),
            DeviceTransport::Mock(m) => m.stream_animation_8b(blob).await,
        }
    }

    pub fn lan(&self) -> Option<&crate::lan::LanTransport> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(_) => None,
            DeviceTransport::Spp(_) => None,
            DeviceTransport::Lan(l) => Some(l),
            DeviceTransport::Mock(_) => None,
        }
    }

    pub async fn wait_for_any_response(
        &self,
        command_ids: &[u8],
        timeout: std::time::Duration,
    ) -> Option<(u8, Vec<u8>)> {
        match self {
            #[cfg(feature = "ble")]
            DeviceTransport::Ble(b) => b.wait_for_any_response(command_ids, timeout).await,
            DeviceTransport::Spp(s) => s.wait_for_any_response(command_ids, timeout).await,
            DeviceTransport::Lan(_) => None,
            DeviceTransport::Mock(m) => m.wait_for_any_response(command_ids, timeout).await,
        }
    }
}
