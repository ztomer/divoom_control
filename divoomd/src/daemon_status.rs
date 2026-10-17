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

        // P3.1: what each panel IS, resolved here once from what it
        // advertises, so no client has to guess size from a name again.
        let mut devices: Vec<Value> = Vec::with_capacity(linked.len());
        for d in &linked {
            devices.push(self.device_entry(d).await);
        }
        let mut reply = json!({
            "success": true,
            "connected": connected,
            "connection_state": if connected { "connected" } else { "disconnected" },
            "mac": mac_out,
            "lan_ip": lan_ip,
            "wall": false,
            "devices": devices,
            "selected": self.fleet.selected_id(),
        });
        if transport.is_some() {
            merge(&mut reply, &panel_of(transport.as_deref()).fields());
        }
        reply
    }
}

impl Daemon {
    /// One panel as every listing shows it: its id, link state, whether it is
    /// the active one, and what it is (`crate::panel_model::Panel::fields`).
    /// `device_status` and `get_topology` both build entries here, so a panel
    /// cannot be described two ways.
    pub(crate) async fn device_entry(&self, d: &crate::device::Device) -> Value {
        let mut e = json!({
            "mac": d.id,
            "connected": d.is_connected().await,
            "selected": self.fleet.is_selected(&d.id),
        });
        merge(&mut e, &panel_of(d.transport().await.as_deref()).fields());
        e
    }
}

/// The model of the panel behind `transport`. A LAN panel advertises no name,
/// so it is `unknown` rather than guessed.
fn panel_of(transport: Option<&DeviceTransport>) -> crate::panel_model::Panel {
    crate::panel_model::from_name(transport.and_then(DeviceTransport::device_name).as_deref())
}

pub fn merge(into: &mut Value, fields: &Value) {
    if let (Some(dst), Some(src)) = (into.as_object_mut(), fields.as_object()) {
        for (k, v) in src {
            dst.insert(k.clone(), v.clone());
        }
    }
}
