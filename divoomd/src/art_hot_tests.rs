//! Hot-channel manifest parsing and download-cache behaviour.
//!
//! Split from `art_hot.rs` at the 500-line cap.

use super::*;

#[test]
fn json_u32_accepts_number_and_string() {
    assert_eq!(json_u32(Some(&json!(1112))), 1112); // numeric (VendorId shape)
    assert_eq!(json_u32(Some(&json!("1112"))), 1112); // quoted string (Version shape)
    assert_eq!(json_u32(Some(&json!(" 1103 "))), 1103); // padded string
    assert_eq!(json_u32(Some(&json!("nope"))), 0);
    assert_eq!(json_u32(None), 0);
}

// Regression: the hot API returns `Version` as a STRING ("1112") and
// `VendorId` as a NUMBER. Parsing Version with as_u64() zeroed every version,
// so the 0x9B manifest advertised newestVersion=0 and pick_file never matched
// the device's request — uploads served 0 files. This asserts versions parse.
#[test]
fn parse_manifest_reads_string_versions() {
    let data = json!({
        "VendorList": [{
            "VendorId": 40_005_454,
            "FileList": [
                {"FileId": "a.bin", "Version": "1103", "Sha1": "aa"},
                {"FileId": "b.bin", "Version": "1112", "Sha1": "bb"},
            ],
        }],
    });
    let files = parse_hot_manifest(&data);
    assert_eq!(files.len(), 2);
    assert_eq!(files[0].vendor_id, 40_005_454);
    assert_eq!(
        files[0].version, 1103,
        "string Version must parse, not zero"
    );
    assert_eq!(files[1].version, 1112);

    // With bodies present, the device's request for v1103 must resolve.
    // BLE-only: `pick_file` answers a device asking for a file over the
    // hot-upload transport, so without that transport there is no such
    // question. The parse half above -- the actual served=0 defect -- runs
    // in BOTH configurations, because a string Version parses the same
    // either way.
    #[cfg(feature = "ble")]
    {
        let mut with_bodies = files;
        for f in &mut with_bodies {
            f.body = vec![0u8; 4];
        }
        let picked = pick_file(&with_bodies, 40_005_454, 1103);
        assert!(picked.is_some(), "pick_file must match a held version");
        assert_eq!(picked.unwrap().version, 1103);
    }
}

// A cache hit must reuse the downloaded set (from_cache=true) and NOT touch
// the network — this is what stops N same-size devices re-downloading.
#[tokio::test]
async fn load_hot_files_returns_cached_without_refetch() {
    clear_manifest_cache();
    let dt = 99u32; // synthetic device_type — no real CDN entry
    let cached = Arc::new(vec![HotFile {
        vendor_id: 1,
        file_id: "x.bin".into(),
        version: 5,
        sha1: String::new(),
        body: vec![1, 2, 3, 4],
    }]);
    manifest_cache()
        .lock()
        .unwrap()
        .insert(dt, (std::time::Instant::now(), cached.clone()));

    // reqwest::Client is unused on a hit; if the cache missed this would hit
    // the network for device_type 99 and return an error/empty instead.
    let (got, dl, from_cache) =
        load_hot_files(&reqwest::Client::new(), dt, &HotProgress::default())
            .await
            .expect("cache hit must succeed without network");
    assert!(from_cache, "should report a cache hit");
    assert_eq!(dl, 1);
    assert_eq!(got.len(), 1);
    assert_eq!(got[0].file_id, "x.bin");
    clear_manifest_cache();
}

/// RFC 3174's own vectors: the digest the manifest compares uploads against
/// must be the standard SHA-1, not something merely 40 hex characters long.
#[test]
fn sha1_matches_the_rfc_3174_vectors() {
    use super::sha1_digest_hex;
    assert_eq!(
        sha1_digest_hex(b"abc"),
        "a9993e364706816aba3e25717850c26c9cd0d89d"
    );
    assert_eq!(
        sha1_digest_hex(b""),
        "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    );
    assert_eq!(
        sha1_digest_hex(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
        "84983e441c3bd26ebaae4aa1f95129e5e54670f1"
    );
}
