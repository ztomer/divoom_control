//! Protocol constants, ported verbatim from `divoom_lib/models` (the authoritative
//! source — parallel-build strategy, see docs/ROADMAP.md). Values are
//! pinned by the framing parity tests against Python-generated vectors.

pub const MESSAGE_START_BYTE: u8 = 0x01;
pub const MESSAGE_END_BYTE: u8 = 0x02;
pub const MESSAGE_CHECKSUM_LENGTH: usize = 2;

// Basic-protocol TX escaping: 0x01 -> [3,4], 0x02 -> [3,5], 0x03 -> [3,6].
pub const ESCAPE_BYTE_1: u8 = 0x01;
pub const ESCAPE_BYTE_2: u8 = 0x02;
pub const ESCAPE_BYTE_3: u8 = 0x03;
pub const ESCAPE_SEQUENCE_1: [u8; 2] = [3, 4];
pub const ESCAPE_SEQUENCE_2: [u8; 2] = [3, 5];
pub const ESCAPE_SEQUENCE_3: [u8; 2] = [3, 6];

// iOS-LE framing.
pub const IOS_LE_HEADER: [u8; 4] = [0xFE, 0xEF, 0xAA, 0x55];
pub const IOS_LE_MIN_DATA_LENGTH: usize = 11;
pub const IOS_LE_DATA_OFFSET: usize = 8;
pub const IOS_LE_COMMAND_IDENTIFIER: usize = 7;
pub const IOS_LE_PACKET_NUMBER: usize = 6;
pub const IOS_LE_CHECKSUM_LENGTH: usize = 2;

// Basic-protocol RX: an "ACK pattern" frame carries the command id at byte 4
// (instead of 3) when byte[3]==0x04 and byte[5]==0x55.
pub const ACK_PATTERN_BYTE_1: u8 = 0x04;
pub const ACK_PATTERN_BYTE_3: u8 = 0x55;

// Response correlation (used by the notify/response layer, Phase 2 next step).
pub const GENERIC_ACK_COMMAND_ID: u8 = 0x33;
pub const GENERIC_ACK_COMMANDS: [u8; 5] = [0x45, 0x05, 0x8A, 0x46, 0x42];

// Upper bound on a single basic RX frame; a larger decoded length is a corrupt
// length field and triggers a resync (drop the start byte) instead of stalling.
pub const MAX_BASIC_FRAME: usize = 8192;
