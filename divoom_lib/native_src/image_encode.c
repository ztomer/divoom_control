/*
 * divoom_lib/native_src/image_encode.c
 *
 * C port of the pure-Python palette encoder in
 * divoom_lib/utils/divoom_image_encode.py. Used to push images /
 * animations to Divoom Timebox-Evo / Pixoo / Tivoo / Timoo / Ditoo
 * devices over Bluetooth.
 *
 * The wire format (verified live on Timoo, 2026-06-05):
 *
 *   Animation frame body (per frame):
 *     AA         (u8)  frame data start marker
 *     LLLL       (LE u16)  byte count of (AA + LLLL + TTTT + RR + NN
 *                          + COLOR_DATA + PIXEL_DATA), i.e. the
 *                          entire frame payload INCLUDING the 2
 *                          LLLL bytes themselves
 *     TTTT       (LE u16)  frame duration in milliseconds
 *     RR         (u8)  reset palette flag; 0x00 = reset on each frame
 *     NN         (u8)  num colors; 0 means 256 (per device protocol)
 *     COLOR_DATA (3N bytes) palette: 3 bytes per color (R G B)
 *     PIXEL_DATA (p bytes)  bit-packed pixel indices, LSB-first
 *                           into LSB-first bytes
 *
 *   Animation packets (0x49 wire command):
 *     All frame bodies are concatenated, then split into 200-byte
 *     chunks. Each chunk is prefixed with:
 *       TOTAL_LEN  (LE u16) total length of all concatenated frame data
 *       PACKET_NUM (u8)      0-based packet index
 *       200 bytes  the chunk (last may be <200)
 *
 * Byte-for-byte equivalence with the Python encoder is the design
 * contract: tests/test_native_image_encoder.py asserts this for
 * ≥100 random inputs. The dylib is loaded by
 * divoom_lib/native/image_encoder.py with a Python fallback to the
 * pure-Python encoder if the dylib is missing.
 */
#include <stdint.h>
#include <string.h>

/* ---------- constants ---------- */

#define DIVOOM_PALETTE_MAX  256
#define DIVOOM_FRAME_HEADER_SIZE  7    /* AA + LLLL + TTTT + RR + NN */
#define DIVOOM_PACKET_HEADER_SIZE 3    /* TOTAL_LEN_LE(2) + PACKET_NUM(1) */
#define DIVOOM_ANIMATION_CHUNK_SIZE 200
#define DIVOOM_HASH_TABLE_SIZE 512     /* power of 2, > 2 × PALETTE_MAX */

/* ---------- palette dedup with open-addressing hash table ---------- */

/* The hash key is a 24-bit RGB value; we pack it into a 32-bit word
 * for direct equality comparison. The table stores (rgb_key,
 * palette_index) pairs in a fixed-size open-addressing table. Empty
 * slots have rgb_key == 0xFFFFFFFF (an impossible RGB triple). */
typedef struct {
    uint32_t rgb_key;      /* 0xFFFFFFFF = empty slot */
    uint8_t  palette_idx;
} palette_entry_t;

static uint32_t rgb_to_key(uint8_t r, uint8_t g, uint8_t b) {
    return ((uint32_t)r << 16) | ((uint32_t)g << 8) | (uint32_t)b;
}

static inline uint32_t hash32(uint32_t x) {
    /* Thomas Wang's 32-bit integer hash; good distribution for
     * sequential RGB keys, no divides. */
    x = (x ^ 61) ^ (x >> 16);
    x = x + (x << 3);
    x = x ^ (x >> 4);
    x = x * 0x27d4eb2dU;
    x = x ^ (x >> 15);
    return x;
}

/* Add color (r,g,b) to palette. Returns palette index (0..255) on
 * success, or -1 if the palette is already full. The hash table is
 * updated in place. The palette itself is stored at out_palette[0..N*3-1]
 * in (R,G,B) byte order. */
static int palette_add(
    palette_entry_t* table,
    uint8_t* out_palette,
    int* out_palette_n,
    uint8_t r, uint8_t g, uint8_t b
) {
    uint32_t key = rgb_to_key(r, g, b);
    uint32_t mask = DIVOOM_HASH_TABLE_SIZE - 1;
    uint32_t idx = hash32(key) & mask;
    /* Linear probing — at most DIVOOM_HASH_TABLE_SIZE iterations. */
    for (uint32_t probe = 0; probe < DIVOOM_HASH_TABLE_SIZE; probe++) {
        uint32_t slot = (idx + probe) & mask;
        if (table[slot].rgb_key == 0xFFFFFFFFU) {
            /* Empty slot — add new color. */
            if (*out_palette_n >= DIVOOM_PALETTE_MAX) {
                return -1;  /* palette full */
            }
            int pi = (*out_palette_n)++;
            table[slot].rgb_key = key;
            table[slot].palette_idx = (uint8_t)pi;
            out_palette[pi * 3 + 0] = r;
            out_palette[pi * 3 + 1] = g;
            out_palette[pi * 3 + 2] = b;
            return pi;
        }
        if (table[slot].rgb_key == key) {
            /* Found existing color. */
            return (int)table[slot].palette_idx;
        }
    }
    /* Table completely full — should not happen with our reserved size
     * (512 > 2 × 256) but bail safely. */
    return -1;
}

/* ---------- core encoder: one animation frame ---------- */

/* Encode a single animation frame (0x49 frame body) into out_buf.
 *
 * On success: returns the number of bytes written, and the palette
 * (3 bytes/color) and bit-packed pixel data appear in out_buf in the
 * exact layout documented above.
 *
 * Returns -1 on:
 *   - more than 256 unique colors
 *   - out_buf_size too small to hold the result
 *   - w*h > some internal safety limit
 */
int divoom_encode_animation_frame(
    const uint8_t* rgb, int w, int h,
    uint16_t time_ms,
    uint8_t* out_buf, int out_buf_size
) {
    if (w <= 0 || h <= 0) return -1;
    if (rgb == NULL || out_buf == NULL) return -1;

    int num_pixels = w * h;
    if (num_pixels > 65535) return -1;  /* sanity */

    /* Worst case: 256 colors (palette 768 bytes) + 1 byte/pixel
     * (256 pixels in 256*8 bits) + 7-byte header.
     * For 16x16 = 256 pixels: max 7 + 768 + 256 = 1031 bytes. */
    int max_palette_bytes = DIVOOM_PALETTE_MAX * 3;
    int max_pixel_bytes = (num_pixels * 8 + 7) / 8;  /* 8 bits/pixel worst case */
    int worst_size = DIVOOM_FRAME_HEADER_SIZE + max_palette_bytes + max_pixel_bytes;
    if (out_buf_size < worst_size) return -1;

    /* ---- Palette dedup pass ---- */
    /* Hash table is stack-allocated — 512 × 8 bytes = 4 KB, fine. */
    palette_entry_t table[DIVOOM_HASH_TABLE_SIZE];
    for (int i = 0; i < DIVOOM_HASH_TABLE_SIZE; i++) {
        table[i].rgb_key = 0xFFFFFFFFU;
        table[i].palette_idx = 0;
    }
    /* Palette storage: 256 × 3 = 768 bytes, stack-allocated. */
    uint8_t palette[DIVOOM_PALETTE_MAX * 3];
    int palette_n = 0;

    /* Per-pixel palette indices. This MUST be a SEPARATE buffer, not aliased
     * onto out_buf: the pixel packer below writes into out_buf[7 + 3*n ..] while
     * still reading indices[i], so borrowing out_buf overwrote not-yet-consumed
     * indices once 7+3*n < i, corrupting the output (divergence from the Python
     * reference). num_pixels is bounded to 65535 above → 64 KB on the stack,
     * within the default 8 MB stack (22 KB for a 160x140 frame). */
    uint8_t indices[65535];

    const uint8_t* p = rgb;
    for (int i = 0; i < num_pixels; i++) {
        uint8_t r = p[0], g = p[1], b = p[2];
        int idx = palette_add(table, palette, &palette_n, r, g, b);
        if (idx < 0) return -1;  /* too many colors */
        indices[i] = (uint8_t)idx;
        p += 3;
    }

    int n = palette_n;
    int nb_bits = 1;
    if (n > 1) {
        /* ceil(log2(n)) without libm: find highest bit set. */
        int v = n - 1;
        int bits = 0;
        while (v > 0) { bits++; v >>= 1; }
        nb_bits = bits;
    }
    /* nb_bits is in [1, 8]. */

    int pixel_data_bytes = (num_pixels * nb_bits + 7) / 8;
    int color_data_bytes = n * 3;
    int llll = DIVOOM_FRAME_HEADER_SIZE + color_data_bytes + pixel_data_bytes;
    int total = llll;  /* == DIVOOM_FRAME_HEADER_SIZE + color_data_bytes + pixel_data_bytes */

    /* ---- Pack pixels into bytes, LSB-first into LSB-first bytes ---- */
    /* Write to out_buf AFTER the header+palette area. We compute
     * the pixel data offset and write pixels in-place. */
    int header_and_palette_bytes = DIVOOM_FRAME_HEADER_SIZE + color_data_bytes;
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
    /* byte_idx should equal pixel_data_bytes. */

    /* ---- Write header (7 bytes): AA + LLLL(LE) + TTTT(LE) + RR + NN ---- */
    /* NN: 0 means 256 (per device protocol). For <256 colors, NN=n. */
    uint8_t nn_byte = (n < DIVOOM_PALETTE_MAX) ? (uint8_t)n : 0;
    out_buf[0] = 0xAA;
    out_buf[1] = (uint8_t)(llll & 0xFF);
    out_buf[2] = (uint8_t)((llll >> 8) & 0xFF);
    out_buf[3] = (uint8_t)(time_ms & 0xFF);
    out_buf[4] = (uint8_t)((time_ms >> 8) & 0xFF);
    out_buf[5] = 0x00;  /* RR = reset palette */
    out_buf[6] = nn_byte;

    /* ---- Copy palette into output ---- */
    if (color_data_bytes > 0) {
        memcpy(out_buf + DIVOOM_FRAME_HEADER_SIZE, palette, color_data_bytes);
    }

    return total;
}

/* ---------- packetizer: split frame blob into 200-byte packets ---------- */

/* Wrap a chunk of frame data in a 0x49 packet header.
 *
 * Per RomRider reference (`_animAsDivoomMessages` in
 * node-divoom-timebox-evo/src/drawing/jimp_overloads.ts):
 *   - The 0x49 command is sent as a single command whose payload is
 *     the *entire* per-packet body below (the framing layer wraps
 *     it with the 0x49 command ID and the iOS-LE/basic protocol
 *     headers — the packet format itself is just the 3-byte header
 *     plus 200 bytes of data).
 *   - Packet header (3 bytes):
 *       TOTAL_LEN  (LE u16)  total bytes of the concatenated frame data
 *       PACKET_NUM (u8)      0-based packet index (1 byte, not 2)
 *   - Followed by 200 bytes of chunk data (last chunk may be shorter).
 *
 * Note: this is DIFFERENT from a basic-headers layout. The counter
 * is 1 byte (0-255), not 2. Confirmed via the live device test on
 * 2026-06-05: the BE + 2-byte-counter format silently fails
 * (device only displays the first frame); LE + 1-byte-counter
 * plays the full animation. */
static void write_animation_packet(
    uint8_t* out_packet,
    uint16_t total_len,
    uint8_t packet_num,
    const uint8_t* chunk,
    int chunk_size
) {
    /* LE u16 total_len */
    out_packet[0] = (uint8_t)(total_len & 0xFF);
    out_packet[1] = (uint8_t)((total_len >> 8) & 0xFF);
    /* u8 packet_num */
    out_packet[2] = packet_num;
    if (chunk_size > 0) {
        memcpy(out_packet + DIVOOM_PACKET_HEADER_SIZE, chunk, chunk_size);
    }
}

/* Pack a concatenated frame blob into a sequence of 0x49 packets.
 *
 * On success: returns the number of packets written. Each packet is
 * exactly DIVOOM_PACKET_HEADER_SIZE + chunk_size bytes long, where
 * the last chunk is <= DIVOOM_ANIMATION_CHUNK_SIZE.
 *
 * Returns -1 on:
 *   - frames_blob is NULL or total_len is 0
 *   - num_frames <= 0
 *   - out_buf_size too small
 */
int divoom_encode_animation_packets(
    const uint8_t* frames_blob,
    int total_len,
    uint8_t* out_buf,
    int out_buf_size
) {
    if (frames_blob == NULL || total_len <= 0) return -1;
    if (out_buf == NULL || out_buf_size < DIVOOM_PACKET_HEADER_SIZE) return -1;

    uint16_t total_len_u16 = (uint16_t)total_len;  /* protocol uses u16 */
    uint16_t packet_num = 0;
    int packets_written = 0;
    int offset = 0;

    while (offset < total_len) {
        int chunk_size = total_len - offset;
        if (chunk_size > DIVOOM_ANIMATION_CHUNK_SIZE) {
            chunk_size = DIVOOM_ANIMATION_CHUNK_SIZE;
        }
        if (packets_written * (DIVOOM_PACKET_HEADER_SIZE
            + DIVOOM_ANIMATION_CHUNK_SIZE)
            + DIVOOM_PACKET_HEADER_SIZE + chunk_size > out_buf_size) {
            return -1;
        }
        /* The caller is expected to provide a single contiguous
         * output buffer; we write each packet back-to-back. */
        write_animation_packet(
            out_buf + packets_written * (DIVOOM_PACKET_HEADER_SIZE
                + DIVOOM_ANIMATION_CHUNK_SIZE),
            total_len_u16,
            packet_num,
            frames_blob + offset,
            chunk_size
        );
        packets_written++;
        packet_num++;
        offset += chunk_size;
    }
    return packets_written;
}

/* ---------- static image encoder (0x44, byte-correct but Timoo
 *             firmware ignores 0x44; kept for other devices) ---------- */

int divoom_encode_static_image(
    const uint8_t* rgb, int w, int h,
    uint8_t* out_buf, int out_buf_size
) {
    if (w <= 0 || h <= 0) return -1;
    if (rgb == NULL || out_buf == NULL) return -1;

    int num_pixels = w * h;
    if (num_pixels > 65535) return -1;

    int max_palette_bytes = DIVOOM_PALETTE_MAX * 3;
    int max_pixel_bytes = (num_pixels * 8 + 7) / 8;
    int worst_size = DIVOOM_FRAME_HEADER_SIZE + max_palette_bytes + max_pixel_bytes;
    if (out_buf_size < worst_size) return -1;

    /* ---- Palette dedup (same as animation frame) ---- */
    palette_entry_t table[DIVOOM_HASH_TABLE_SIZE];
    for (int i = 0; i < DIVOOM_HASH_TABLE_SIZE; i++) {
        table[i].rgb_key = 0xFFFFFFFFU;
        table[i].palette_idx = 0;
    }
    uint8_t palette[DIVOOM_PALETTE_MAX * 3];
    int palette_n = 0;

    /* Separate index buffer — see divoom_encode_animation_frame for why aliasing
     * onto out_buf corrupts the packed pixel data. */
    uint8_t indices[65535];

    const uint8_t* p = rgb;
    for (int i = 0; i < num_pixels; i++) {
        uint8_t r = p[0], g = p[1], b = p[2];
        int idx = palette_add(table, palette, &palette_n, r, g, b);
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
    /* Static header is 7 bytes: AA + LLLL(LE u16) + 000000(3) + NN — identical to
     * the animation-frame header (the 000000 stands in for TTTT(2)+RR(1)). It was
     * 6 here, which made the NN palette-count byte written at out_buf[6] get
     * CLOBBERED by the `memcpy(out_buf + static_header_size, palette, ...)` below
     * (palette landed on byte 6) and undercounted LLLL by 1 — diverging from the
     * Python reference (which is verified-correct). */
    int static_header_size = 7;
    int llll = static_header_size + color_data_bytes + pixel_data_bytes;
    int total = llll;

    int header_and_palette_bytes = static_header_size + color_data_bytes;
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

    uint8_t nn_byte = (n < DIVOOM_PALETTE_MAX) ? (uint8_t)n : 0;
    out_buf[0] = 0xAA;
    out_buf[1] = (uint8_t)(llll & 0xFF);
    out_buf[2] = (uint8_t)((llll >> 8) & 0xFF);
    out_buf[3] = 0x00;  /* 000000 first byte */
    out_buf[4] = 0x00;  /* 000000 second byte */
    out_buf[5] = 0x00;  /* 000000 third byte */
    out_buf[6] = nn_byte;

    if (color_data_bytes > 0) {
        memcpy(out_buf + static_header_size, palette, color_data_bytes);
    }

    return total;
}
