//! The wall's channel select: one panel's packet, built per panel.

use super::{DivoomWall, WallOutcome, LAN_SLOT_REFUSAL};
use crate::daemon::DeviceTransport;

impl DivoomWall {
    /// Switch every panel to `channel`, each with the packet one panel's
    /// select builds ([`crate::device_call::system::channel_select`], P6.3):
    /// the light channel is read back from EACH panel and re-sent switched on,
    /// so every panel keeps its own brightness and colour (D.WALLCH). It
    /// broadcast the table's default light -- white at 100 -- to every slot.
    pub async fn switch_channel(
        &self,
        channel: crate::packets::Channel,
        timeout: std::time::Duration,
    ) -> WallOutcome {
        self.each_slot(|_, dev| async move {
            if let DeviceTransport::Lan(_) = &*dev {
                return Err(LAN_SLOT_REFUSAL.to_string());
            }
            let packet = crate::device_call::system::channel_select(&dev, channel, timeout)
                .await
                .map_err(|reply| {
                    reply["error"]
                        .as_str()
                        .unwrap_or("the read failed")
                        .to_string()
                })?;
            dev.send_command(crate::packets::CMD_SET_LIGHT_MODE, &packet, true)
                .await
                .map_err(|e| e.to_string())
        })
        .await
    }
}
