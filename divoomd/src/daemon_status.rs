//! Device connection status reply. Split out of `daemon.rs` to keep it under the
//! 500-line house limit.

use serde_json::{json, Value};

use crate::daemon::Daemon;
use crate::transport::DeviceTransport;

impl Daemon {
    pub(crate) async fn device_status(&self) -> Value {
        let connected = self.device.lock().await.is_some();
        let id_val = self.device_id.lock().await.clone();

        let (mac, lan_ip) = if let Some(ref dev) = *self.device.lock().await {
            match &**dev {
                #[cfg(feature = "ble")]
                DeviceTransport::Ble(_) => (
                    id_val.map(Value::String).unwrap_or(Value::Null),
                    Value::Null,
                ),
                DeviceTransport::Spp(_) => (
                    id_val.map(Value::String).unwrap_or(Value::Null),
                    Value::Null,
                ),
                DeviceTransport::Lan(l) => (Value::Null, Value::String(l.device_ip.clone())),
                DeviceTransport::Mock(_) => (
                    id_val.map(Value::String).unwrap_or(Value::Null),
                    Value::Null,
                ),
            }
        } else {
            (
                id_val.map(Value::String).unwrap_or(Value::Null),
                Value::Null,
            )
        };

        json!({
            "success": true,
            "connected": connected,
            "connection_state": if connected { "connected" } else { "disconnected" },
            "mac": mac,
            "lan_ip": lan_ip,
            "wall": false,
        })
    }
}
