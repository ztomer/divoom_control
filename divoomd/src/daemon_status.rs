//! Device connection status reply. Split out of `daemon.rs` to keep it under the
//! 500-line house limit.

use serde_json::{json, Value};

use crate::daemon::Daemon;
use crate::transport::DeviceTransport;

impl Daemon {
    /// `device_status`: one panel when `mac` names it. Without a mac, the
    /// panel a mac-less request would go to (the selected one while linked,
    /// else the single linked one); otherwise the fleet summary
    /// (`connected` = any linked, `mac` null, `devices` listed) -- a caller
    /// that did not say which panel gets told there are several.
    pub(crate) async fn device_status(&self, mac: Option<&str>) -> Value {
        let linked = self.fleet.linked().await;
        let target = match mac {
            Some(m) => self.fleet.get(m).await,
            None => self.fleet.resolve_target(None).await.ok(),
        };
        let id_val = target.as_ref().map(|d| d.id.clone());
        let transport = match target {
            Some(ref d) => d.transport().await,
            None => None,
        };
        let connected = if mac.is_some() {
            transport.is_some()
        } else {
            !linked.is_empty()
        };

        let (mac_out, lan_ip) = if let Some(ref dev) = transport {
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

        let devices: Vec<Value> = linked
            .iter()
            .map(|d| json!({"mac": d.id, "connected": true, "selected": self.fleet.is_selected(&d.id)}))
            .collect();
        json!({
            "success": true,
            "connected": connected,
            "connection_state": if connected { "connected" } else { "disconnected" },
            "mac": mac_out,
            "lan_ip": lan_ip,
            "wall": false,
            "devices": devices,
            "selected": self.fleet.selected_id(),
        })
    }
}
