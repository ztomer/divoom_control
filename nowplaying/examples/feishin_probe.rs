fn main() {
    match nowplaying::feishin::unavailable() {
        Some(r) => println!("feishin unavailable: {}", r.reason()),
        None => println!("feishin: credentials found, server reachable path OK"),
    }
    match nowplaying::feishin::current_track() {
        Some(t) => println!(
            "feishin track: {} (artwork {:?} bytes)",
            t.display(),
            t.artwork.as_ref().map(|a| a.len())
        ),
        None => println!("feishin: getNowPlaying returned no entry"),
    }
}
