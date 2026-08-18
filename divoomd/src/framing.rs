//! Basic + iOS-LE wire framing, ported byte-for-byte from `divoom_lib/framing.py`.
//! Parity is enforced by `tests/framing_parity.rs` against vectors generated from
//! the Python implementation (`scripts/codegen/gen_framing_vectors.py`).

use crate::models;

/// Encode a payload in the Basic protocol framing:
/// `[0x01][len_lo][len_hi][body...][cksum_lo][cksum_hi][0x02]`, where `len` counts
/// the body plus the 2 checksum bytes, and the checksum is `sum(len_lo..body) &
/// 0xFFFF`. With `escape`, body bytes 0x01/0x02/0x03 expand to their 2-byte escape
/// sequences.
pub fn encode_basic_payload(payload: &[u8], escape: bool) -> Vec<u8> {
    let mut body: Vec<u8> = Vec::with_capacity(if escape {
        payload.len() * 2
    } else {
        payload.len()
    });
    if escape {
        for &b in payload {
            match b {
                models::ESCAPE_BYTE_1 => body.extend_from_slice(&models::ESCAPE_SEQUENCE_1),
                models::ESCAPE_BYTE_2 => body.extend_from_slice(&models::ESCAPE_SEQUENCE_2),
                models::ESCAPE_BYTE_3 => body.extend_from_slice(&models::ESCAPE_SEQUENCE_3),
                _ => body.push(b),
            }
        }
    } else {
        body.extend_from_slice(payload);
    }

    let length_value = body.len() + models::MESSAGE_CHECKSUM_LENGTH;
    let mut out: Vec<u8> = Vec::with_capacity(body.len() + 6);
    out.push(models::MESSAGE_START_BYTE);
    out.push((length_value & 0xFF) as u8);
    out.push(((length_value >> 8) & 0xFF) as u8);
    out.extend_from_slice(&body);

    // checksum over everything after the start byte so far: [len_lo, len_hi, body...]
    let checksum: u32 = out[1..].iter().map(|&b| b as u32).sum::<u32>() & 0xFFFF;
    out.push((checksum & 0xFF) as u8);
    out.push(((checksum >> 8) & 0xFF) as u8);
    out.push(models::MESSAGE_END_BYTE);
    out
}

/// Encode a payload (command id is `payload[0]`) in the iOS-LE framing:
/// `[FE EF AA 55][len_lo][len_hi][pkt][cmd][data...][cksum_lo][cksum_hi][0x02]`,
/// where `len = total - 7`, only the low byte of `packet_number` is transmitted,
/// and the checksum is `sum(bytes[4..len-3]) & 0xFFFF`.
pub fn encode_ios_le_payload(payload: &[u8], packet_number: u32) -> Result<Vec<u8>, &'static str> {
    if payload.is_empty() {
        return Err("payload must contain at least the command id");
    }
    let n = payload.len();
    let total_len = n + 10;
    let mut out = vec![0u8; total_len];

    out[0..4].copy_from_slice(&models::IOS_LE_HEADER);
    let length_field = (total_len - 7) as u32;
    out[4] = (length_field & 0xFF) as u8;
    out[5] = ((length_field >> 8) & 0xFF) as u8;
    out[6] = (packet_number & 0xFF) as u8;
    out[7] = payload[0];
    if n > 1 {
        out[8..8 + n - 1].copy_from_slice(&payload[1..]);
    }

    let checksum: u32 = out[4..n + 7].iter().map(|&b| b as u32).sum::<u32>() & 0xFFFF;
    let idx = n + 7;
    out[idx] = (checksum & 0xFF) as u8;
    out[idx + 1] = ((checksum >> 8) & 0xFF) as u8;
    out[idx + 2] = models::MESSAGE_END_BYTE;
    Ok(out)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IosLeNotification {
    pub command_id: u8,
    pub payload: Vec<u8>,
    pub packet_number: u8,
    pub checksum: u16,
}

/// Parse an iOS-LE notification. Returns `None` on a short buffer, a bad header,
/// or a missing end marker. (The checksum is reported, not enforced — matching the
/// Python reference, which leaves RX checksum verification to a higher layer.)
pub fn parse_ios_le_notification(data: &[u8]) -> Option<IosLeNotification> {
    if data.len() < models::IOS_LE_MIN_DATA_LENGTH {
        return None;
    }
    if data[0..4] != models::IOS_LE_HEADER {
        return None;
    }
    if *data.last().unwrap() != models::MESSAGE_END_BYTE {
        return None;
    }
    let command_id = data[models::IOS_LE_COMMAND_IDENTIFIER];
    let packet_number = data[models::IOS_LE_PACKET_NUMBER];
    let end = data.len() - models::IOS_LE_CHECKSUM_LENGTH - 1; // == len - 3
    let payload = data[models::IOS_LE_DATA_OFFSET..end].to_vec();
    let lo = data[data.len() - 3] as u16;
    let hi = data[data.len() - 2] as u16;
    Some(IosLeNotification {
        command_id,
        payload,
        packet_number,
        checksum: lo | (hi << 8),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BasicMessage {
    pub command_id: u8,
    pub payload: Vec<u8>,
}

/// Parse zero or more Basic-protocol frames from `buf`, draining the consumed
/// bytes. Whatever remains in `buf` after the call is the unconsumed remainder (an
/// incomplete trailing frame, or empty). Mirrors `parse_basic_protocol_frames`:
/// resync on the start byte, drop frames with a corrupt over-long length, and
/// discard frames whose end byte or checksum don't validate.
pub fn parse_basic_protocol_frames(buf: &mut Vec<u8>) -> Vec<BasicMessage> {
    let mut messages = Vec::new();

    while buf.len() >= 7 {
        let start_index = match buf.iter().position(|&b| b == models::MESSAGE_START_BYTE) {
            Some(i) => i,
            None => {
                buf.clear();
                break;
            }
        };
        if start_index > 0 {
            buf.drain(0..start_index);
        }
        if buf.len() < 4 {
            break;
        }

        let length = (buf[1] as usize) | ((buf[2] as usize) << 8);
        let total_message_len = 4 + length;

        if total_message_len > models::MAX_BASIC_FRAME {
            buf.remove(0); // resync past this start byte
            continue;
        }
        if buf.len() < total_message_len {
            break;
        }

        let message: Vec<u8> = buf[..total_message_len].to_vec();
        buf.drain(0..total_message_len);

        if *message.last().unwrap() != models::MESSAGE_END_BYTE {
            continue;
        }

        let (command_id, payload): (u8, Vec<u8>) = if message.len() > 5
            && message[3] == models::ACK_PATTERN_BYTE_1
            && message[5] == models::ACK_PATTERN_BYTE_3
        {
            (message[4], message[6..message.len() - 3].to_vec())
        } else {
            (message[3], message[4..message.len() - 3].to_vec())
        };

        let calculated: u32 = message[1..message.len() - 3]
            .iter()
            .map(|&b| b as u32)
            .sum::<u32>()
            & 0xFFFF;
        let received =
            (message[message.len() - 3] as u32) | ((message[message.len() - 2] as u32) << 8);
        if received != calculated {
            continue;
        }

        messages.push(BasicMessage {
            command_id,
            payload,
        });
    }

    messages
}
