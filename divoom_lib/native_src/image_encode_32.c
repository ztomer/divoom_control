/*
 * divoom_lib/native_src/image_encode_32.c
 *
 * 32x32 Divoom device encoder.
 *
 * APK comparison (R35d): the APK uses the **same** AA-format frame encoding
 * for ALL screen sizes via `NDKMain.pixelEncode()`. The hass-divoom-derived
 * pre-frames (0x05/0x06), extended palette flag (RR=0x03), and 2-byte color
 * count are NOT in the APK.
 *
 * This file therefore uses the **standard** 7-byte frame header:
 *   AA + LLLL(LE u16) + TTTT(LE u16) + RR=0x00 + NN(u8)
 * matching image_encode.c's divoom_encode_animation_frame exactly.
 *
 * The pre-frame functions (divoom_write_pre_frame_1/2) are kept for C API
 * backward compatibility but are no longer called by the Python wrapper.
 *
 * Also provides the 0x8B 3-phase protocol chunker (per futpib animation.rs):
 *   - StartSeeding:   [0x00][file_size LE u32]
 *   - SendingData:    [0x01][file_size LE u32][offset_id LE u16][<=256 bytes]
 *   - TerminateSending: [0x02]
 *
 * Byte-for-byte equivalence with divoom_image_encode_32.py is the
 * design contract. tests/test_native_image_encoder.py asserts this.
 */
#include <stdint.h>
#include <string.h>

#define DIVOOM_PALETTE_MAX_32  256
/* Standard 7-byte frame header: AA + LLLL + TTTT + RR + NN (RR=0x00, NN=u8).
 * APK uses this same header for ALL screen sizes (R35d). */
#define DIVOOM_FRAME_HEADER_SIZE_32 7
#define DIVOOM_HASH_TABLE_SIZE_32 512
#define DIVOOM_8B_CHUNK_SIZE 256
#define DIVOOM_SCREENSIZE 32
#define DIVOOM_PIXEL_COUNT_32 (DIVOOM_SCREENSIZE * DIVOOM_SCREENSIZE)

/* ---------- palette dedup (open addressing, same as 16x16) ---------- */

typedef struct {
    uint32_t rgb_key;
    uint8_t  palette_idx;
} palette_entry_32_t;

static uint32_t rgb_to_key_32(uint8_t r, uint8_t g, uint8_t b) {
    return ((uint32_t)r << 16) | ((uint32_t)g << 8) | (uint32_t)b;
}

static inline uint32_t hash32_32(uint32_t x) {
    x = (x ^ 61) ^ (x >> 16);
    x = x + (x << 3);
    x = x ^ (x >> 4);
    x = x * 0x27d4eb2dU;
    x = x ^ (x >> 15);
    return x;
}

static int palette_add_32(
    palette_entry_32_t* table,
    uint8_t* out_palette,
    int* out_palette_n,
    uint8_t r, uint8_t g, uint8_t b
) {
    uint32_t key = rgb_to_key_32(r, g, b);
    uint32_t mask = DIVOOM_HASH_TABLE_SIZE_32 - 1;
    uint32_t idx = hash32_32(key) & mask;
    for (uint32_t probe = 0; probe < DIVOOM_HASH_TABLE_SIZE_32; probe++) {
        uint32_t slot = (idx + probe) & mask;
        if (table[slot].rgb_key == 0xFFFFFFFFU) {
            if (*out_palette_n >= DIVOOM_PALETTE_MAX_32) return -1;
            int pi = (*out_palette_n)++;
            table[slot].rgb_key = key;
            table[slot].palette_idx = (uint8_t)pi;
            out_palette[pi * 3 + 0] = r;
            out_palette[pi * 3 + 1] = g;
            out_palette[pi * 3 + 2] = b;
            return pi;
        }
        if (table[slot].rgb_key == key) {
            return (int)table[slot].palette_idx;
        }
    }
    return -1;
}

/* ---------- pre-frames for 32x32 (hass-divoom:348-350) ---------- */

static const uint8_t PRE_FRAME_1_BODY[5] = {0x00, 0x00, 0x05, 0x00, 0x00};
static const uint8_t PRE_FRAME_2_BODY[6] = {0x00, 0x00, 0x06, 0x00, 0x00, 0x00};

static int write_pre_frame(
    const uint8_t* body, int body_len,
    uint8_t* out, int out_size
) {
    /* [AA][LLLL LE u16] + body. LLLL = 3 + body_len. */
    int total = 3 + body_len;
    if (out_size < total) return -1;
    out[0] = 0xAA;
    out[1] = (uint8_t)(total & 0xFF);
    out[2] = (uint8_t)((total >> 8) & 0xFF);
    memcpy(out + 3, body, body_len);
    return total;
}

int divoom_write_pre_frame_1(uint8_t* out, int out_size) {
    return write_pre_frame(PRE_FRAME_1_BODY, sizeof(PRE_FRAME_1_BODY),
                           out, out_size);
}

int divoom_write_pre_frame_2(uint8_t* out, int out_size) {
    return write_pre_frame(PRE_FRAME_2_BODY, sizeof(PRE_FRAME_2_BODY),
                           out, out_size);
}

/* ---------- 32x32 frame encoder ---------- */

int divoom_encode_animation_frame_32(
    const uint8_t* rgb, int w, int h,
    uint16_t time_ms,
    uint8_t* out_buf, int out_buf_size
) {
    if (w != DIVOOM_SCREENSIZE || h != DIVOOM_SCREENSIZE) return -1;
    if (rgb == NULL || out_buf == NULL) return -1;

    int num_pixels = w * h;
    if (num_pixels > 65535) return -1;

    int max_palette_bytes = DIVOOM_PALETTE_MAX_32 * 3;
    int max_pixel_bytes = (num_pixels * 8 + 7) / 8;
    int worst_size = DIVOOM_FRAME_HEADER_SIZE_32 + max_palette_bytes
                     + max_pixel_bytes;
    if (out_buf_size < worst_size) return -1;

    palette_entry_32_t table[DIVOOM_HASH_TABLE_SIZE_32];
    for (int i = 0; i < DIVOOM_HASH_TABLE_SIZE_32; i++) {
        table[i].rgb_key = 0xFFFFFFFFU;
        table[i].palette_idx = 0;
    }
    uint8_t palette[DIVOOM_PALETTE_MAX_32 * 3];
    int palette_n = 0;

    /* Per-pixel palette indices. MUST be a SEPARATE buffer — aliasing this onto
     * out_buf corrupted the output: the pixel packer writes into
     * out_buf[7 + 3*n ..] while still reading indices[i] from out_buf[i], so
     * once 7+3*n < i the not-yet-consumed indices were overwritten, producing
     * wrong pixel bytes (divergence from the Python reference, confirmed by a
     * dylib probe). w/h are guaranteed 32 here, so 1024 bytes on the stack. */
    uint8_t indices[DIVOOM_PIXEL_COUNT_32];

    const uint8_t* p = rgb;
    for (int i = 0; i < num_pixels; i++) {
        uint8_t r = p[0], g = p[1], b = p[2];
        int idx = palette_add_32(table, palette, &palette_n, r, g, b);
        if (idx < 0) return -1;
        indices[i] = (uint8_t)idx;
        p += 3;
    }

    int n = palette_n;
    int nb_bits = 1;
    if (n > 1) {
        int v = n - 1;
        int bits = 0;
        while (v > 0) { bits++; v >>= 1; }
        nb_bits = bits;
    }

    int pixel_data_bytes = (num_pixels * nb_bits + 7) / 8;
    int color_data_bytes = n * 3;
    int llll = DIVOOM_FRAME_HEADER_SIZE_32 + color_data_bytes + pixel_data_bytes;
    int total = llll;

    int header_and_palette_bytes = DIVOOM_FRAME_HEADER_SIZE_32 + color_data_bytes;
    uint8_t* pixel_data = out_buf + header_and_palette_bytes;
    if (header_and_palette_bytes + pixel_data_bytes > out_buf_size) return -1;

    int mask = (1 << nb_bits) - 1;
    {
        int byte_idx = 0;
        unsigned int acc = 0;   /* LSB-first bit accumulator, continuous across bytes */
        int acc_bits = 0;
        for (int i = 0; i < num_pixels; i++) {
            acc |= (unsigned int)(indices[i] & mask) << acc_bits;
            acc_bits += nb_bits;
            while (acc_bits >= 8) {
                pixel_data[byte_idx++] = (uint8_t)(acc & 0xFF);
                acc >>= 8;
                acc_bits -= 8;
            }
        }
        if (acc_bits > 0) {
            pixel_data[byte_idx++] = (uint8_t)(acc & 0xFF);
        }
    }

    /* Header: AA + LLLL(LE) + TTTT(LE) + RR=0x00 + NN(u8) — standard
     * AA format matching APK's pixelEncode() for ALL screen sizes. */
    uint8_t nn_byte = (n < DIVOOM_PALETTE_MAX_32) ? (uint8_t)n : 0;
    out_buf[0] = 0xAA;
    out_buf[1] = (uint8_t)(llll & 0xFF);
    out_buf[2] = (uint8_t)((llll >> 8) & 0xFF);
    out_buf[3] = (uint8_t)(time_ms & 0xFF);
    out_buf[4] = (uint8_t)((time_ms >> 8) & 0xFF);
    out_buf[5] = 0x00;  /* RR = 0x00 (reset palette) — matches APK */
    out_buf[6] = nn_byte;

    if (color_data_bytes > 0) {
        memcpy(out_buf + DIVOOM_FRAME_HEADER_SIZE_32, palette, color_data_bytes);
    }

    return total;
}

/* ---------- 0x8B 3-phase protocol helpers ---------- */

/* Control words per futpib animation.rs:6-11 */
#define CTRL_START_SENDING  0x00
#define CTRL_SENDING_DATA   0x01
#define CTRL_TERMINATE_SENDING 0x02

static void write_8b_start(
    uint8_t* out, uint32_t file_size
) {
    out[0] = CTRL_START_SENDING;
    out[1] = (uint8_t)(file_size & 0xFF);
    out[2] = (uint8_t)((file_size >> 8) & 0xFF);
    out[3] = (uint8_t)((file_size >> 16) & 0xFF);
    out[4] = (uint8_t)((file_size >> 24) & 0xFF);
}

static void write_8b_data(
    uint8_t* out,
    uint32_t file_size, uint16_t offset_id,
    const uint8_t* chunk, int chunk_size
) {
    out[0] = CTRL_SENDING_DATA;
    out[1] = (uint8_t)(file_size & 0xFF);
    out[2] = (uint8_t)((file_size >> 8) & 0xFF);
    out[3] = (uint8_t)((file_size >> 16) & 0xFF);
    out[4] = (uint8_t)((file_size >> 24) & 0xFF);
    out[5] = (uint8_t)(offset_id & 0xFF);
    out[6] = (uint8_t)((offset_id >> 8) & 0xFF);
    if (chunk_size > 0) {
        memcpy(out + 7, chunk, chunk_size);
    }
}

static void write_8b_terminate(uint8_t* out) {
    out[0] = CTRL_TERMINATE_SENDING;
}

/* Pack a concatenated frame blob into 0x8B SPP payloads.
 * Writes back-to-back into out_buf. Returns total bytes written.
 *
 * Layout:
 *   [StartSeeding 5B] [SendingData 7+<=256B] ... [TerminateSending 1B]
 *
 * out_buf_size should be at least 5 + 7*N_chunks + 1.
 */
int divoom_encode_animation_8b(
    const uint8_t* frames_blob,
    int total_len,
    uint8_t* out_buf,
    int out_buf_size
) {
    if (frames_blob == NULL || total_len <= 0) return -1;
    if (out_buf == NULL) return -1;

    int n_chunks = (total_len + DIVOOM_8B_CHUNK_SIZE - 1) / DIVOOM_8B_CHUNK_SIZE;
    int total_size = 5 + n_chunks * 7 + n_chunks * DIVOOM_8B_CHUNK_SIZE + 1;
    if (out_buf_size < total_size) return -1;

    uint32_t file_size = (uint32_t)total_len;
    int offset = 0;
    int out_off = 0;

    write_8b_start(out_buf + out_off, file_size);
    out_off += 5;

    /* offset_id is the sequential chunk INDEX (0,1,2,...), per the futpib
     * reference (create_network_packets_from) and the Python streamer
     * Animation.stream_animation_8b. The device positions chunk N at byte
     * N*DIVOOM_8B_CHUNK_SIZE (256), so the chunk size and index must agree —
     * an earlier version sent a byte offset here, which left gaps and stalled
     * the transfer. */
    for (int i = 0; i < n_chunks; i++) {
        int chunk_size = total_len - offset;
        if (chunk_size > DIVOOM_8B_CHUNK_SIZE) chunk_size = DIVOOM_8B_CHUNK_SIZE;
        write_8b_data(out_buf + out_off, file_size, (uint16_t)i,
                      frames_blob + offset, chunk_size);
        out_off += 7 + chunk_size;
        offset += chunk_size;
    }

    write_8b_terminate(out_buf + out_off);
    out_off += 1;

    return out_off;
}
