//! AES-128-CBC decrypt (Divoom cloud container key/IV, magic 9/18/26).

/// AES-CBC decrypt with the Divoom cloud key/IV.
///
/// The key and IV are public constants in the APK, so there is no secret
/// here; the cipher is the `RustCrypto` `aes` + `cbc` crates (the reference algorithm
/// used to be hand-rolled in this file, untested until 2026-09-21). No
/// padding is stripped: the container reader takes only the plaintext
/// length it knows, and a ciphertext that is not whole blocks is `None`.
#[must_use]
pub fn aes_cbc_decrypt(data: &[u8]) -> Option<Vec<u8>> {
    use aes::cipher::{block_padding::NoPadding, BlockDecryptMut, KeyIvInit};
    if data.is_empty() {
        return None;
    }
    let mut buf = data.to_vec();
    let decryptor =
        cbc::Decryptor::<aes::Aes128>::new(b"78hrey23y28ogs89".into(), b"1234567890123456".into());
    let n = decryptor
        .decrypt_padded_mut::<NoPadding>(&mut buf)
        .ok()?
        .len();
    buf.truncate(n);
    Some(buf)
}

#[cfg(test)]
mod tests {
    use super::aes_cbc_decrypt;

    fn unhex(s: &str) -> Vec<u8> {
        (0..s.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("hex"))
            .collect()
    }

    /// A vector made with `openssl enc -aes-128-cbc -nopad` under the cloud
    /// key/IV: 48 bytes of plaintext, three blocks, no padding to strip.
    #[test]
    fn decrypts_an_openssl_vector_under_the_cloud_key() {
        let ct = unhex(
            "5ce8e1737d6e4429505c2593c9b388ae746e9fdc38d0f678b1c3ff2fad61e143\
             b1a97d60b925d78b12df98a9dff2aef5",
        );
        let pt = aes_cbc_decrypt(&ct).expect("decrypts");
        assert_eq!(pt, b"The quick brown fox jumps over the lazy dog!!!!!");
    }

    /// Not a whole number of blocks, or nothing at all, is not a container.
    #[test]
    fn a_partial_block_or_nothing_is_refused() {
        let mut ct = unhex("5ce8e1737d6e4429505c2593c9b388ae746e9fdc38d0f678b1c3ff2fad61e143");
        ct.extend_from_slice(&[1, 2, 3]);
        assert_eq!(aes_cbc_decrypt(&ct), None);
        assert_eq!(aes_cbc_decrypt(&[]), None);
    }
}
