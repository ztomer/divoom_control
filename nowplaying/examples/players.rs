//! `cargo run -p nowplaying --example players` — who is out there, and who is
//! actually playing.
fn main() {
    let players = nowplaying::players();
    if players.is_empty() {
        println!("no media players discovered");
        return;
    }
    println!("{:<22} {:<14} PLAYING", "PLAYER", "REACHED VIA");
    for p in &players {
        let state = match p.is_playing {
            Some(true) => "yes",
            Some(false) => "no",
            None => "unknown",
        };
        println!("{:<22} {:<14} {}", p.name, format!("{:?}", p.via), state);
    }
    if let Some(h) = nowplaying::feishin::hint() {
        println!(
            "
hint: {h}"
        );
    }
}
