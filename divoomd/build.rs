//! Build script: on macOS, embed `daemon_info.plist` into the binary as a
//! `__TEXT,__info_plist` section. A loose helper binary needs its own embedded
//! Info.plist (with NSBluetoothAlwaysUsageDescription) for macOS TCC to
//! attribute/prompt a Bluetooth grant when the GUI .app spawns it — otherwise
//! CoreBluetooth is silently denied (no prompt). No-op on Linux/Windows.

fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        let dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();
        let plist = format!("{dir}/daemon_info.plist");
        if std::path::Path::new(&plist).exists() {
            println!("cargo:rustc-link-arg=-Wl,-sectcreate,__TEXT,__info_plist,{plist}");
        }
        println!("cargo:rerun-if-changed=daemon_info.plist");
    }
}
