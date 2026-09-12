//! Device connection status reply. Split out of `daemon.rs` to keep it under the
//! 500-line house limit.

use serde_json::{json, Value};

use crate::daemon::Daemon;
use crate::transport::DeviceTransport;

impl Daemon {
    /// `device_status`: one panel when `mac` names it, else the current
    /// device. A proxy bound to a panel asks about THAT panel, not about
    /// whichever connected last.
    pub(crate) async fn device_status(&self, mac: Option<&str>) -> Value {
        let current = self.fleet.resolve(mac).await;
        let id_val = current.as_ref().map(|d| d.id.clone());
        let transport = match current {
            Some(ref d) => d.transport().await,
            None => None,
        };
        let connected = transport.is_some();

        let (mac, lan_ip) = if let Some(ref dev) = transport {
            match &**dev {
                #[cfg(feature = "ble")]
                DeviceTransport::Ble(_) => (id_val.map_or(Value::Null, Value::String), Value::Null),
                DeviceTransport::Spp(_) => (id_val.map_or(Value::Null, Value::String), Value::Null),
                DeviceTransport::Lan(l) => (Value::Null, Value::String(l.device_ip.clone())),
                DeviceTransport::Mock(_) => {
                    (id_val.map_or(Value::Null, Value::String), Value::Null)
                }
            }
        } else {
            (id_val.map_or(Value::Null, Value::String), Value::Null)
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
