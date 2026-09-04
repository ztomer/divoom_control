#include <string.h>

// NEON is used to copy each 16-pixel (48-byte) tile row on ARM (Apple silicon
// + aarch64 Linux). On other targets (x86_64 Linux/macOS) we fall back to a
// byte-identical memcpy, so the library is portable. <arm_neon.h> only exists
// on ARM toolchains, so the include must be guarded too.
#if defined(__ARM_NEON) || defined(__aarch64__)
#include <arm_neon.h>
#define DIVOOM_HAVE_NEON 1
#endif

// ── Image Layout Constants ──────────────────────────────────────────
#define TILE_SIZE          16
#define CHANNELS_RGB       3
#define TILE_ROW_BYTES     (TILE_SIZE * CHANNELS_RGB)

// ── SIMD Vector Constants ──────────────────────────────────────────
#define VEC_SIZE_BYTES     16
#define VEC_OFFSET_0       0
#define VEC_OFFSET_1       16
#define VEC_OFFSET_2       32

// ── Divoom Protocol Constants ───────────────────────────────────────
#define MESSAGE_START_BYTE 0x01
#define MESSAGE_END_BYTE   0x02
#define ESCAPE_BYTE_1      0x01
#define ESCAPE_BYTE_2      0x02
#define ESCAPE_BYTE_3      0x03

#define ESCAPE_PREFIX      0x03
#define ESCAPE_VAL_1       0x04
#define ESCAPE_VAL_2       0x05
#define ESCAPE_VAL_3       0x06

#define LENGTH_BYTES_SIZE  2
#define CHECKSUM_LENGTH    2

// ── iOS-LE Protocol Constants ──────────────────────────────────────
#define IOS_LE_HEADER_BYTE_0 0xFE
#define IOS_LE_HEADER_BYTE_1 0xEF
#define IOS_LE_HEADER_BYTE_2 0xAA
#define IOS_LE_HEADER_BYTE_3 0x55
#define IOS_LE_LENGTH_OFFSET 7


void compact_tiles(const unsigned char* frame_data, int frame_data_len, 
                   unsigned char* output_pixels, int row_count, int column_count) {
    int width = column_count * TILE_SIZE;
    int height = row_count * TILE_SIZE;
    int max_out_pos = width * height * CHANNELS_RGB;

    int tile_idx = 0;
    for (int grid_y = 0; grid_y < row_count; grid_y++) {
        for (int grid_x = 0; grid_x < column_count; grid_x++) {
            for (int y = 0; y < TILE_SIZE; y++) {
                int in_pos = (tile_idx * TILE_SIZE + y) * TILE_ROW_BYTES;
                int out_x = grid_x * TILE_SIZE;
                int out_y = grid_y * TILE_SIZE + y;
                int out_pos = (out_y * width + out_x) * CHANNELS_RGB;
                
                // Copy an entire 16-pixel row (48 bytes). NEON on ARM; a
                // byte-identical memcpy everywhere else.
                if (in_pos + TILE_ROW_BYTES <= frame_data_len && out_pos + TILE_ROW_BYTES <= max_out_pos) {
#ifdef DIVOOM_HAVE_NEON
                    uint8x16_t v0 = vld1q_u8(frame_data + in_pos + VEC_OFFSET_0);
                    uint8x16_t v1 = vld1q_u8(frame_data + in_pos + VEC_OFFSET_1);
                    uint8x16_t v2 = vld1q_u8(frame_data + in_pos + VEC_OFFSET_2);

                    vst1q_u8(output_pixels + out_pos + VEC_OFFSET_0, v0);
                    vst1q_u8(output_pixels + out_pos + VEC_OFFSET_1, v1);
                    vst1q_u8(output_pixels + out_pos + VEC_OFFSET_2, v2);
#else
                    memcpy(output_pixels + out_pos, frame_data + in_pos, TILE_ROW_BYTES);
#endif
                }
            }
            tile_idx++;
        }
    }
}

int encode_basic_payload(const unsigned char* payload, int payload_len, int escape, unsigned char* out_msg) {
    int out_idx = 0;
    
    // Start byte
    out_msg[out_idx++] = MESSAGE_START_BYTE;
    
    // Save index for length field
    int len_idx = out_idx;
    out_idx += LENGTH_BYTES_SIZE;
    
    int payload_start_idx = out_idx;
    
    if (escape) {
        for (int i = 0; i < payload_len; i++) {
            unsigned char b = payload[i];
            if (b == ESCAPE_BYTE_1) {
                out_msg[out_idx++] = ESCAPE_PREFIX;
                out_msg[out_idx++] = ESCAPE_VAL_1;
            } else if (b == ESCAPE_BYTE_2) {
                out_msg[out_idx++] = ESCAPE_PREFIX;
                out_msg[out_idx++] = ESCAPE_VAL_2;
            } else if (b == ESCAPE_BYTE_3) {
                out_msg[out_idx++] = ESCAPE_PREFIX;
                out_msg[out_idx++] = ESCAPE_VAL_3;
            } else {
                out_msg[out_idx++] = b;
            }
        }
    } else {
        for (int i = 0; i < payload_len; i++) {
            out_msg[out_idx++] = payload[i];
        }
    }
    
    int escaped_len = out_idx - payload_start_idx;
    
    // Write length field (escaped_len + checksum_len)
    int length_val = escaped_len + CHECKSUM_LENGTH;
    unsigned char len_lo = length_val & 0xFF;
    unsigned char len_hi = (length_val >> 8) & 0xFF;
    out_msg[len_idx] = len_lo;
    out_msg[len_idx + 1] = len_hi;
    
    // Calculate 16-bit checksum
    unsigned int checksum = len_lo + len_hi;
    for (int i = payload_start_idx; i < out_idx; i++) {
        checksum += out_msg[i];
    }
    checksum &= 0xFFFF;
    
    // Write checksum
    out_msg[out_idx++] = checksum & 0xFF;
    out_msg[out_idx++] = (checksum >> 8) & 0xFF;
    
    // End byte
    out_msg[out_idx++] = MESSAGE_END_BYTE;
    
    return out_idx;
}

int encode_ios_le_payload(const unsigned char* payload, int payload_len, int packet_number, unsigned char* out_msg) {
    if (payload_len <= 0) return 0;
    
    int out_idx = 0;
    
    // Write iOS-LE header
    out_msg[out_idx++] = IOS_LE_HEADER_BYTE_0;
    out_msg[out_idx++] = IOS_LE_HEADER_BYTE_1;
    out_msg[out_idx++] = IOS_LE_HEADER_BYTE_2;
    out_msg[out_idx++] = IOS_LE_HEADER_BYTE_3;
    
    // Save index for length field
    int len_idx = out_idx;
    out_idx += LENGTH_BYTES_SIZE;
    
    int checksum_start_idx = out_idx;
    
    // Write packet number
    unsigned char packet_number_byte = packet_number & 0xFF;
    out_msg[out_idx++] = packet_number_byte;
    
    // Write command identifier
    unsigned char command_identifier = payload[0];
    out_msg[out_idx++] = command_identifier;
    
    // Write data bytes
    for (int i = 1; i < payload_len; i++) {
        out_msg[out_idx++] = payload[i];
    }
    
    int checksum_end_idx = out_idx;
    
    // Write length field (total_len - IOS_LE_LENGTH_OFFSET)
    int length_val = out_idx + CHECKSUM_LENGTH + 1 - IOS_LE_LENGTH_OFFSET;
    unsigned char len_lo = length_val & 0xFF;
    unsigned char len_hi = (length_val >> 8) & 0xFF;
    out_msg[len_idx] = len_lo;
    out_msg[len_idx + 1] = len_hi;
    
    // Calculate checksum
    unsigned int checksum = len_lo + len_hi;
    for (int i = checksum_start_idx; i < checksum_end_idx; i++) {
        checksum += out_msg[i];
    }
    checksum &= 0xFFFF;
    
    // Write checksum
    out_msg[out_idx++] = checksum & 0xFF;
    out_msg[out_idx++] = (checksum >> 8) & 0xFF;
    
    // Write end marker
    out_msg[out_idx++] = MESSAGE_END_BYTE;
    
    return out_idx;
}




