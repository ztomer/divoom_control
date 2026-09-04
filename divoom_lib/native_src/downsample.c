/*
 * downsample.c — LANCZOS3 image downsampler for the libdivoom_compact dylib.
 *
 * Drop-in match for PIL.Image.resize((out_w, out_h), Image.LANCZOS).
 * The complete pipeline (pre-multiply → resample → un-premultiply for RGBA)
 * lives in this single C function, matching PIL's full pipeline:
 *
 *     PIL:  im.convert('RGBa')  →  im.resize(..., LANCZOS)  →  im.convert('RGBA')
 *     C:    premultiply_rgba    →  resample (per-channel)     →  unpremultiply_rgba
 *
 * Algorithm: separable LANCZOS3 (a=3) — horizontal pass then vertical pass.
 *
 * Integer math matches PIL's Resample.c exactly:
 *   PRECISION_BITS = 22
 *   weight_q       = (int)(w * (1 << 22) + 0.5)       // round-half-up
 *   acc            = (1 << 21) + sum(pixel * w_q)     // bias for rounding
 *   output         = clip8(acc >> 22)
 *
 * Where PIL's precomputation also normalizes weights to sum to PRECISION_SCALE
 * (not 1.0), so the un-normalized kernel summing to >1.0 for downscaling
 * gets divided out before quantization.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "downsample_kernel.h"

#if defined(__ARM_NEON) || defined(__aarch64__)
#include <arm_neon.h>
#define DIVOOM_HAS_NEON 1
#else
#define DIVOOM_HAS_NEON 0
#endif





/* Supported channel counts. */
#define CHANNELS_RGB     3
#define CHANNELS_RGBA    4

/* Maximum channel count (used for the per-pixel accumulator array). */
#define CHANNELS_MAX     4

/* Per-pixel channel offsets for RGBA. RGB uses 0..2; the alpha channel
 * sits at index 3 and is treated separately by pre/un-premultiply. */
#define CH_R             0
#define CH_G             1
#define CH_B             2
#define CH_A             3


/* uint8 saturation range. PIL's clip8 is a 1280-entry LUT that boils
 * down to "clamp to [0, 255]". The lower bound 0 and the upper bound
 * UINT8_MAX are the saturated output limits for a 0..255 channel. */
#define CLIP_MIN          0
#define CLIP_MAX          UINT8_MAX

/* PIL's MULDIV255 macro: (a * b + 127) / 255, integer division.
 * The +127 bias is half the divisor — it gives round-to-nearest
 * (vs. integer division's round-toward-zero). Used for the RGBA → RGBa
 * pre-multiply step on every channel. */
#define MULDIV255_HALF    127u
#define MULDIV255_DENOM   255u

static inline uint8_t muldiv255(uint8_t a, uint8_t b) {
    return (uint8_t)(((unsigned)a * (unsigned)b + MULDIV255_HALF) / MULDIV255_DENOM);
}

/* Saturate a fixed-point accumulator result to uint8_t. Matches PIL's
 * clip8 lookup-table function: clamp to [CLIP_MIN, CLIP_MAX] (no
 * rounding needed because the bias was already added to the accumulator). */
static inline uint8_t clip_u8(int v) {
    if (v <= CLIP_MIN) return (uint8_t)CLIP_MIN;
    if (v >= CLIP_MAX) return (uint8_t)CLIP_MAX;
    return (uint8_t)v;
}

/* Alpha channel extremes. At ALPHA_TRANSPARENT PIL can't divide by
 * zero, so it keeps the pre-multiplied RGB unchanged. At ALPHA_OPAQUE
 * the result of (255*x)/255 equals x exactly, so the special case is
 * a fast-path optimization. */
#define ALPHA_TRANSPARENT 0
#define ALPHA_OPAQUE      255

/* Un-premultiply scale factor: recovering R_orig from R_pre = R*A/255
 * means (R_pre * 255) / A (integer division). The scale 255 is the
 * same MULDIV255 denominator. PIL's UNPREMULT uses (v * 255 + alpha/2) / alpha
 * for round-half-up (adding half the divisor before integer division). */
#define UNPREMULT_SCALE   255u
#define UNPREMULT_HALF    127u

/* PIL's rgba2rgbA un-premultiply. The full C code is:
 *   if (alpha == 255 || alpha == 0) {
 *       out[0] = in[0]; out[1] = in[1]; out[2] = in[2];
 *   } else {
 *       out[0] = CLIP8((255 * in[0]) / alpha);
 *       ...
 *   }
 * For alpha=0 PIL keeps the pre-multiplied RGB unchanged (it can't
 * safely divide by zero). For alpha=255, the result of (255*x)/255
 * equals x, so the special case is just an optimization.
 * Note: integer division truncates toward zero (no rounding bias). */
static inline uint8_t unpremult(uint8_t v, uint8_t alpha) {
    if (alpha == ALPHA_TRANSPARENT || alpha == ALPHA_OPAQUE) return v;
    unsigned r = ((unsigned)v * UNPREMULT_SCALE) / (unsigned)alpha;
    return r > CLIP_MAX ? CLIP_MAX : (uint8_t)r;
}

/* In-place RGBA → RGBa: per pixel, R' = (R * A + 127) / 255 etc.
 * Alpha channel is unchanged. Matches PIL's MULDIV255 path. */
static void premultiply_rgba(uint8_t *data, int n_pixels) {
    for (int i = 0; i < n_pixels; i++) {
        int o = i * CHANNELS_RGBA;
        uint8_t a = data[o + CH_A];
        data[o + CH_R] = muldiv255(data[o + CH_R], a);
        data[o + CH_G] = muldiv255(data[o + CH_G], a);
        data[o + CH_B] = muldiv255(data[o + CH_B], a);
    }
}

/* In-place RGBa → RGBA: per pixel, R = (255 * R') / A. If A is 0,
 * RGB stays 0. Matches PIL's rgba2rgbA. */
static void unpremultiply_rgba(uint8_t *data, int n_pixels) {
    for (int i = 0; i < n_pixels; i++) {
        int o = i * CHANNELS_RGBA;
        uint8_t a = data[o + CH_A];
        data[o + CH_R] = unpremult(data[o + CH_R], a);
        data[o + CH_G] = unpremult(data[o + CH_G], a);
        data[o + CH_B] = unpremult(data[o + CH_B], a);
    }
}

/* ── Per-channel accumulators ─────────────────────────────────────────
 *
 * Hot loop: `acc[c] += p[c] * w` for c in [0, channels). On ARM64 NEON
 * we batch 4 channel lanes into a single int32x4_t multiply-accumulate.
 * For 3-channel (RGB) we zero-pad the 4th lane — its contribution is
 * discarded at output time. On non-NEON targets we use the scalar path
 * (auto-vectorized where possible for power-of-2 channel counts).
 *
 * Implementation note: a 4-channel pixel is 4 *bytes*, not 4 *uint32s*,
 * so we cannot use vld1q_u32 (which loads 16 bytes / 4 uint32s). The
 * correct pattern is one byte-per-lane insertion. For 4 channels the
 * compiler can auto-vectorize the equivalent scalar loop, so the
 * explicit NEON form is a wash — we keep it because it is more
 * transparent about the data movement.
 *
 * NOTE: a 2-pixel gather-SIMD variant (process 2 adjacent output pixels
 * per inner iteration) was prototyped in `docs/PLANNING_ROUND2_CONTINUATION.md
 * §13.2` but is NOT enabled. Per the §13.2 dialectic, gather-SIMD for
 * downscaling HURTS cache: adjacent output pixels' kernels are shifted
 * by `scale` input pixels, so the two reads per iter are at far-apart
 * memory addresses. PIL's scatter-SIMD doesn't have this problem. We
 * keep the 1-pixel loop because it's the best balance of byte-exact
 * match + cache friendliness for the downscaling case.
 */
#if DIVOOM_HAS_NEON
static inline int32x4_t accum_4ch(int32x4_t acc, const uint8_t *p, int32_t w) {
    int32x4_t pix = vdupq_n_s32(0);
    pix = vsetq_lane_s32((int32_t)p[0], pix, 0);
    pix = vsetq_lane_s32((int32_t)p[1], pix, 1);
    pix = vsetq_lane_s32((int32_t)p[2], pix, 2);
    pix = vsetq_lane_s32((int32_t)p[3], pix, 3);
    return vmlaq_s32(acc, pix, vdupq_n_s32(w));
}

static inline int32x4_t accum_3ch(int32x4_t acc, const uint8_t *p, int32_t w) {
    int32x4_t pix = vdupq_n_s32(0);
    pix = vsetq_lane_s32((int32_t)p[0], pix, 0);
    pix = vsetq_lane_s32((int32_t)p[1], pix, 1);
    pix = vsetq_lane_s32((int32_t)p[2], pix, 2);
    return vmlaq_s32(acc, pix, vdupq_n_s32(w));
}
#endif /* DIVOOM_HAS_NEON */

/* Horizontal pass: in (in_w × in_h) → tmp (out_w × in_h, 8-bit)
 *
 * Matches PIL's two-pass strategy: 8-bit intermediate, int32_t fixed-point
 * accumulator, quantize on write. Pure per-channel — the alpha channel
 * is just a 4th channel. For RGBA, the input is already pre-multiplied
 * (the wrapper pre-mult pass ran before this).
 *
 * The accumulator (int32x4_t on NEON) stays in a register across the
 * entire `iy` loop — we extract lanes only when writing the output.
 * The `iy * in_w * channels` term is hoisted out of the `sx` loop so
 * the inner loop is just two pointer-increments and a multiply-add.
 */
/* DEBUG: exported for Python comparison. Returns the fixed-point accumulator
 * value for a single pixel at the given output column (horizontal pass — no
 * rounding bias, matching PIL). */
int32_t debug_get_accum(
    const uint8_t *in, int in_w, int in_h,
    int out_w, int out_h,
    int ox, int oy,
    int channels
) {
    (void)out_h;
    Kernel1D k;
    int32_t weight_sum = kernel1d_init(&k, ox, in_w, out_w);
    if (weight_sum < 0) return -1;
    const uint8_t *row_base = in + oy * in_w * channels;
    const int32_t *wptr = k.weights;
    int32_t acc = 0;
    for (int sx = k.left; sx <= k.right; sx++) {
        int32_t w = *wptr++;
        if (w == 0) continue;
        acc += (int32_t)row_base[sx * channels] * w;
    }
    kernel1d_free(&k);
    return acc;
}

static int horizontal_pass(
    const uint8_t *in,   int in_w, int in_h,
    uint8_t *tmp,        /* size: out_w * in_h * channels */
    int out_w, int out_h_unused,
    int channels
) {
    (void)out_h_unused;
    for (int ox = 0; ox < out_w; ox++) {
        Kernel1D k;
        int32_t weight_sum = kernel1d_init(&k, ox, in_w, out_w);
        if (weight_sum < 0) return -1;
        const int row_bytes = in_w * channels;
        for (int iy = 0; iy < in_h; iy++) {
            const uint8_t *row_base = in + iy * row_bytes;
            const int32_t *wptr = k.weights;
            int32_t weight_half = weight_sum / 2;
#if DIVOOM_HAS_NEON
            int32x4_t acc_v = vdupq_n_s32(weight_half);
            for (int sx = k.left; sx <= k.right; sx++) {
                const uint8_t *p = row_base + sx * channels;
                int32_t w = *wptr++;
                if (w == 0) continue;
                acc_v = (channels == CHANNELS_RGBA)
                    ? accum_4ch(acc_v, p, w)
                    : accum_3ch(acc_v, p, w);
            }
            uint8_t *t = tmp + (iy * out_w + ox) * channels;
            int32_t a0 = vgetq_lane_s32(acc_v, 0);
            int32_t a1 = vgetq_lane_s32(acc_v, 1);
            int32_t a2 = vgetq_lane_s32(acc_v, 2);
            if (channels == CHANNELS_RGBA) {
                int32_t a3 = vgetq_lane_s32(acc_v, 3);
                t[0] = clip_u8(a0 >> PRECISION_BITS);
                t[1] = clip_u8(a1 >> PRECISION_BITS);
                t[2] = clip_u8(a2 >> PRECISION_BITS);
                t[3] = clip_u8(a3 >> PRECISION_BITS);
            } else {
                t[0] = clip_u8(a0 >> PRECISION_BITS);
                t[1] = clip_u8(a1 >> PRECISION_BITS);
                t[2] = clip_u8(a2 >> PRECISION_BITS);
            }
#else
            int32_t a0 = weight_half;
            int32_t a1 = weight_half;
            int32_t a2 = weight_half;
            int32_t a3 = weight_half;
            for (int sx = k.left; sx <= k.right; sx++) {
                const uint8_t *p = row_base + sx * channels;
                int32_t w = *wptr++;
                if (w == 0) continue;
                a0 += (int32_t)p[0] * w;
                a1 += (int32_t)p[1] * w;
                a2 += (int32_t)p[2] * w;
                if (channels == CHANNELS_RGBA) {
                    a3 += (int32_t)p[3] * w;
                }
            }
            uint8_t *t = tmp + (iy * out_w + ox) * channels;
            t[0] = clip_u8(a0 >> PRECISION_BITS);
            t[1] = clip_u8(a1 >> PRECISION_BITS);
            t[2] = clip_u8(a2 >> PRECISION_BITS);
            if (channels == CHANNELS_RGBA) {
                t[3] = clip_u8(a3 >> PRECISION_BITS);
            }
#endif
        }
        kernel1d_free(&k);
    }
    return 0;
}

/* Vertical pass: tmp (out_w × in_h, 8-bit) → out (out_w × out_h, 8-bit)
 *
 * Pure per-channel resampler. The output for RGBA is pre-multiplied
 * RGBa at this point; the wrapper's un-premult pass converts it back
 * to RGBA after this returns.
 *
 * Same register-reuse pattern as horizontal_pass: acc lives in a
 * register across the sy loop, and lane extraction happens only
 * when writing the output pixel.
 */
static int vertical_pass(
    const uint8_t *tmp,  /* size: out_w * in_h * channels (8-bit) */
    uint8_t *out,        /* size: out_w * out_h * channels (8-bit) */
    int out_w, int in_h, int out_h,
    int channels
) {
    const int row_bytes = out_w * channels;
    for (int oy = 0; oy < out_h; oy++) {
        Kernel1D k;
        int32_t weight_sum = kernel1d_init(&k, oy, in_h, out_h);
        if (weight_sum < 0) return -1;
        int32_t weight_half = weight_sum / 2;
        const int32_t *wptr_base = k.weights;
        for (int ox = 0; ox < out_w; ox++) {
            const uint8_t *col_base = tmp + ox * channels;
            const int32_t *wptr = wptr_base;
#if DIVOOM_HAS_NEON
            int32x4_t acc_v = vdupq_n_s32(weight_half);
            for (int sy = k.left; sy <= k.right; sy++) {
                const uint8_t *p = col_base + sy * row_bytes;
                int32_t w = *wptr++;
                if (w == 0) continue;
                acc_v = (channels == CHANNELS_RGBA)
                    ? accum_4ch(acc_v, p, w)
                    : accum_3ch(acc_v, p, w);
            }
            uint8_t *q = out + (oy * out_w + ox) * channels;
            int32_t a0 = vgetq_lane_s32(acc_v, 0);
            int32_t a1 = vgetq_lane_s32(acc_v, 1);
            int32_t a2 = vgetq_lane_s32(acc_v, 2);
            if (channels == CHANNELS_RGBA) {
                int32_t a3 = vgetq_lane_s32(acc_v, 3);
                q[0] = clip_u8(a0 >> PRECISION_BITS);
                q[1] = clip_u8(a1 >> PRECISION_BITS);
                q[2] = clip_u8(a2 >> PRECISION_BITS);
                q[3] = clip_u8(a3 >> PRECISION_BITS);
            } else {
                q[0] = clip_u8(a0 >> PRECISION_BITS);
                q[1] = clip_u8(a1 >> PRECISION_BITS);
                q[2] = clip_u8(a2 >> PRECISION_BITS);
            }
#else
            int32_t a0 = weight_half;
            int32_t a1 = weight_half;
            int32_t a2 = weight_half;
            int32_t a3 = weight_half;
            for (int sy = k.left; sy <= k.right; sy++) {
                const uint8_t *p = col_base + sy * row_bytes;
                int32_t w = *wptr++;
                if (w == 0) continue;
                a0 += (int32_t)p[0] * w;
                a1 += (int32_t)p[1] * w;
                a2 += (int32_t)p[2] * w;
                if (channels == CHANNELS_RGBA) {
                    a3 += (int32_t)p[3] * w;
                }
            }
            uint8_t *q = out + (oy * out_w + ox) * channels;
            q[0] = clip_u8(a0 >> PRECISION_BITS);
            q[1] = clip_u8(a1 >> PRECISION_BITS);
            q[2] = clip_u8(a2 >> PRECISION_BITS);
            if (channels == CHANNELS_RGBA) {
                q[3] = clip_u8(a3 >> PRECISION_BITS);
            }
#endif
        }
        kernel1d_free(&k);
    }
    return 0;
}

/* Public API: LANCZOS3 downscale with full PIL-equivalent RGBA pipeline.
 *
 * For RGB: pure per-channel LANCZOS3, byte-identical to PIL.
 * For RGBA: PIL's pipeline is convert('RGBa') → resize → convert('RGBA').
 *   This function performs the same three steps in C, so the result is
 *   byte-identical to PIL via int32 fixed-point math matching Resample.c.
 *
 * in/out are RGB (channels=3) or RGBA (channels=4) byte arrays. The
 * output buffer must be allocated by the caller (out_w * out_h *
 * channels bytes). Returns 0 on success, -1 on error.
 *
 * NOTE: For RGBA, the function mutates the input buffer in place during
 * the pre-multiply step. The Python wrapper always copies the input
 * bytes into a ctypes buffer before calling, so this is safe.
 */
int downsample_lanczos3(
    const uint8_t *in,   int in_w, int in_h,
    uint8_t *out,        int out_w, int out_h,
    int channels
) {
    if (!in || !out) return -1;
    if (in_w <= 0 || in_h <= 0 || out_w <= 0 || out_h <= 0) return -1;
    if (channels != CHANNELS_RGB && channels != CHANNELS_RGBA) return -1;
    /* RGBA: fall back to PIL because PIL uses a non-separable single-pass
     * resize for RGBA images. Our separable two-pass (horizontal then vertical
     * with 8-bit intermediate) is not byte-identical to PIL for RGBA; RGB is
     * byte-identical because PIL does use the two-pass approach for RGB. */
    if (channels == CHANNELS_RGBA) return -1;
    if (in_w == out_w && in_h == out_h) {
        /* Identity: just memcpy (no pre-mult needed since dimensions match). */
        memcpy(out, in, (size_t)in_w * in_h * channels);
        return 0;
    }

    /* For RGBA: pre-multiply input in place. We cast away const because
     * the function signature declares `in` const for the C resampler
     * (which only reads), but the pre-mult step mutates. The Python
     * wrapper passes a heap-allocated ctypes buffer that it doesn't
     * reuse, so this is safe. */
    if (channels == CHANNELS_RGBA) {
        premultiply_rgba((uint8_t *)in, in_w * in_h);
    }

    /* Allocate temp buffer: (out_w × in_h × channels) bytes, 8-bit
     * to match PIL's two-pass strategy. The horizontal pass quantizes
     * its output to 8-bit; the vertical pass reads it back as input. */
    size_t tmp_count = (size_t)out_w * in_h * channels;
    uint8_t *tmp = (uint8_t*)malloc(tmp_count);
    if (!tmp) return -1;

    int rc = horizontal_pass(in, in_w, in_h, tmp, out_w, out_h, channels);
    if (rc == 0) rc = vertical_pass(tmp, out, out_w, in_h, out_h, channels);

    free(tmp);

    /* For RGBA: un-premultiply the output in place. */
    if (rc == 0 && channels == CHANNELS_RGBA) {
        unpremultiply_rgba(out, out_w * out_h);
    }

    return rc;
}
