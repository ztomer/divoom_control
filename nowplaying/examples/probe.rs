//! `cargo run -p nowplaying --example probe` — what is playing right now.
//!
//! A render-one style harness: one command, real data, no app required. This is
//! the loop used to develop against the live system.
fn main() {
    match nowplaying::unavailable() {
        Some(reason) => {
            println!("unavailable: {}", reason.reason());
            std::process::exit(1);
        }
        None => println!("availability: OK"),
    }
    match nowplaying::current_track() {
        Ok(None) => println!("nothing playing"),
        Ok(Some(t)) => {
            println!("source : {}", t.source);
            println!(
                "playing: {}",
                if t.is_playing { "yes" } else { "NO (paused)" }
            );
            println!("display: {}", t.display());
            println!("title  : {:?}", t.title);
            println!("artist : {:?}", t.artist);
            println!("album  : {:?}", t.album);
            match &t.artwork {
                None => println!("artwork: none"),
                Some(a) => {
                    println!(
                        "artwork: {} bytes, sniffed {:?} ({})",
                        a.len(),
                        a.format,
                        a.format.mime()
                    );
                    if a.mime_is_a_lie() {
                        println!(
                            "         declared {:?} — DISAGREES with the bytes",
                            a.declared_mime.as_deref().unwrap_or("?")
                        );
                    }
                }
            }
        }
        Err(e) => {
            println!("error: {e}");
            std::process::exit(2);
        }
    }
}
