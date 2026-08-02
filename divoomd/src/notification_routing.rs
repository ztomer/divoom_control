//! App-bundle-id → device notification-slot routing rules.
//!
//! Split out of `macos_notifications.rs` (500-LOC house limit): the
//! load/save/match logic for `~/.config/divoom-control/notification_routing.json`
//! is self-contained and independently testable, no macOS-specific I/O beyond
//! plain file read/write.

pub const DEFAULT_ROUTING: &[(&str, u8)] = &[
    ("whatsapp", 6),
    ("facebook", 4),
    ("messenger", 13),
    ("instagram", 2),
    ("twitter", 5),
    ("snapchat", 3),
    ("line", 9),
    ("wechat", 10),
    ("kakao", 1),
    ("qq", 11),
    ("viber", 12),
    ("skype", 8),
    ("mobilesms", 7),
    ("messages", 7),
    ("mail", 7),
    ("com.apple.mail", 7),
];

pub fn get_routing_path() -> std::path::PathBuf {
    if let Ok(p) = std::env::var("DIVOOM_CONTROL_ROUTING") {
        std::path::PathBuf::from(p)
    } else if let Ok(home) = std::env::var("HOME") {
        std::path::PathBuf::from(home)
            .join(".config")
            .join("divoom-control")
            .join("notification_routing.json")
    } else {
        std::path::PathBuf::from("notification_routing.json")
    }
}

pub fn load_routing_rules() -> Vec<(String, u8)> {
    let p = get_routing_path();
    if !p.exists() {
        return DEFAULT_ROUTING
            .iter()
            .map(|(s, t)| (s.to_string(), *t))
            .collect();
    }
    let data = match std::fs::read_to_string(&p) {
        Ok(s) => s,
        Err(_) => {
            return DEFAULT_ROUTING
                .iter()
                .map(|(s, t)| (s.to_string(), *t))
                .collect()
        }
    };
    let raw: Result<Vec<Vec<serde_json::Value>>, _> = serde_json::from_str(&data);
    match raw {
        Ok(entries) => {
            let mut rules = Vec::new();
            for entry in entries {
                if entry.len() == 2 {
                    if let (Some(s), Some(t)) = (entry[0].as_str(), entry[1].as_u64()) {
                        rules.push((s.to_lowercase(), t as u8));
                    }
                }
            }
            if rules.is_empty() {
                DEFAULT_ROUTING
                    .iter()
                    .map(|(s, t)| (s.to_string(), *t))
                    .collect()
            } else {
                rules
            }
        }
        Err(_) => DEFAULT_ROUTING
            .iter()
            .map(|(s, t)| (s.to_string(), *t))
            .collect(),
    }
}

pub fn save_routing_rules(rules: &[(String, u8)]) -> Result<(), String> {
    let p = get_routing_path();
    if let Some(parent) = p.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let mut sorted = rules.to_vec();
    sorted.sort_by(|a, b| a.0.cmp(&b.0));

    let json_val = serde_json::Value::Array(
        sorted
            .iter()
            .map(|(s, t)| serde_json::json!([s, t]))
            .collect(),
    );
    let serialized = serde_json::to_string_pretty(&json_val).map_err(|e| e.to_string())? + "\n";
    std::fs::write(&p, serialized).map_err(|e| e.to_string())?;
    Ok(())
}

pub fn route_app(app_id: &str, rules: &[(String, u8)]) -> Option<u8> {
    if app_id.is_empty() {
        return None;
    }
    let a = app_id.to_lowercase();
    for (substr, app_type) in rules {
        if a.contains(substr) {
            return Some(*app_type);
        }
    }
    None
}
