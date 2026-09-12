/* gif_frames.js — decode an animated GIF into composed RGBA frames.
 *
 * Defect #2 (2026-09-12): every bench/ribbon/wall preview blits an
 * HTMLImageElement with ctx.drawImage, and WebKit never advances a GIF's
 * frames through that path, so animated art froze at frame 0 while the
 * device animated. Rather than overlay an <img> (a second renderer that
 * would drift from the canvas), the canvas stays the ONE renderer and
 * this decoder hands it the frame for "now".
 *
 * Scope: GIF87a/89a, global + local colour tables, interlace, transparency,
 * disposal 0-3, LZW. Output frames are fully composed (each is the complete
 * picture at that instant), so the renderer never needs the previous one.
 *
 * window.GifFrames.decode(dataUrl | Uint8Array) -> { width, height,
 *   frames: [{ rgba: Uint8ClampedArray, delay: ms }], total: ms } | null
 * (null when the bytes are not a GIF, or it has a single frame -- the
 * static path already handles those).
 */
(function () {
    "use strict";

    function bytesOf(src) {
        if (src instanceof Uint8Array) return src;
        if (typeof src !== "string") return null;
        const m = /^data:image\/gif(?:;[^,]*)?;base64,(.*)$/i.exec(src);
        if (!m) return null;
        try {
            const bin = atob(m[1]);
            const out = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
            return out;
        } catch (_) {
            return null;
        }
    }

    function readColorTable(b, pos, count) {
        const t = new Array(count);
        for (let i = 0; i < count; i++) {
            const o = pos + i * 3;
            t[i] = [b[o], b[o + 1], b[o + 2]];
        }
        return t;
    }

    // Concatenate the data sub-blocks starting at pos; returns [bytes, nextPos].
    function readSubBlocks(b, pos) {
        const chunks = [];
        let len = 0;
        while (pos < b.length) {
            const n = b[pos++];
            if (n === 0) break;
            chunks.push(b.subarray(pos, pos + n));
            len += n;
            pos += n;
        }
        const out = new Uint8Array(len);
        let o = 0;
        for (const c of chunks) { out.set(c, o); o += c.length; }
        return [out, pos];
    }

    function skipSubBlocks(b, pos) {
        while (pos < b.length) {
            const n = b[pos++];
            if (n === 0) break;
            pos += n;
        }
        return pos;
    }

    // Standard GIF LZW: variable code width, clear/end codes, KwKwK case.
    function lzwDecode(minCodeSize, data, pixelCount) {
        const out = new Uint8Array(pixelCount);
        const clear = 1 << minCodeSize;
        const end = clear + 1;
        let codeSize = minCodeSize + 1;
        let dictSize = end + 1;
        let prefix = new Int32Array(4096);
        let suffix = new Uint8Array(4096);
        let lengths = new Uint16Array(4096);
        for (let i = 0; i < clear; i++) { prefix[i] = -1; suffix[i] = i; lengths[i] = 1; }
        let bitBuf = 0, bitCnt = 0, pos = 0, outPos = 0, prev = -1;
        const stack = new Uint8Array(4097);
        while (outPos < pixelCount) {
            while (bitCnt < codeSize) {
                if (pos >= data.length) return out;
                bitBuf |= data[pos++] << bitCnt;
                bitCnt += 8;
            }
            const code = bitBuf & ((1 << codeSize) - 1);
            bitBuf >>>= codeSize;
            bitCnt -= codeSize;
            if (code === clear) {
                codeSize = minCodeSize + 1;
                dictSize = end + 1;
                prev = -1;
                continue;
            }
            if (code === end) break;
            let entry = code;
            let first;
            if (code >= dictSize) {
                // KwKwK: code not yet in the table = prev + first char of prev.
                if (prev < 0) return out;
                entry = prev;
                let s = 0;
                let c = prev;
                while (c >= 0) { stack[s++] = suffix[c]; c = prefix[c]; }
                first = stack[s - 1];
                // emit prev then first
                for (let i = s - 1; i >= 0 && outPos < pixelCount; i--) out[outPos++] = stack[i];
                if (outPos < pixelCount) out[outPos++] = first;
            } else {
                let s = 0;
                let c = entry;
                while (c >= 0) { stack[s++] = suffix[c]; c = prefix[c]; }
                first = stack[s - 1];
                for (let i = s - 1; i >= 0 && outPos < pixelCount; i--) out[outPos++] = stack[i];
            }
            if (prev >= 0 && dictSize < 4096) {
                prefix[dictSize] = prev;
                suffix[dictSize] = first;
                lengths[dictSize] = lengths[prev] + 1;
                dictSize++;
                if (dictSize === (1 << codeSize) && codeSize < 12) codeSize++;
            }
            prev = code;
        }
        return out;
    }

    function decode(src) {
        const b = bytesOf(src);
        if (!b || b.length < 13) return null;
        const sig = String.fromCharCode(b[0], b[1], b[2], b[3], b[4], b[5]);
        if (sig !== "GIF87a" && sig !== "GIF89a") return null;
        const width = b[6] | (b[7] << 8);
        const height = b[8] | (b[9] << 8);
        if (!width || !height) return null;
        const packed = b[10];
        const bgIndex = b[11];
        let pos = 13;
        let gct = null;
        if (packed & 0x80) {
            const n = 1 << ((packed & 0x07) + 1);
            gct = readColorTable(b, pos, n);
            pos += n * 3;
        }

        const frames = [];
        const canvas = new Uint8ClampedArray(width * height * 4); // composed picture
        let gce = { delay: 100, transparent: -1, disposal: 0 };
        let total = 0;

        while (pos < b.length) {
            const block = b[pos++];
            if (block === 0x3B) break; // trailer
            if (block === 0x21) { // extension
                const label = b[pos++];
                if (label === 0xF9 && b[pos] === 4) {
                    const flags = b[pos + 1];
                    const delayCs = b[pos + 2] | (b[pos + 3] << 8);
                    gce = {
                        // Browsers clamp sub-2cs delays to 10cs; match them.
                        delay: (delayCs < 2 ? 10 : delayCs) * 10,
                        transparent: (flags & 1) ? b[pos + 4] : -1,
                        disposal: (flags >> 2) & 7,
                    };
                    pos += 5;
                    if (b[pos] === 0) pos++;
                } else {
                    pos = skipSubBlocks(b, pos);
                }
                continue;
            }
            if (block !== 0x2C) return frames.length > 1 ? finish() : null; // unknown: stop
            const ix = b[pos] | (b[pos + 1] << 8);
            const iy = b[pos + 2] | (b[pos + 3] << 8);
            const iw = b[pos + 4] | (b[pos + 5] << 8);
            const ih = b[pos + 6] | (b[pos + 7] << 8);
            const ipk = b[pos + 8];
            pos += 9;
            let ct = gct;
            if (ipk & 0x80) {
                const n = 1 << ((ipk & 0x07) + 1);
                ct = readColorTable(b, pos, n);
                pos += n * 3;
            }
            const interlaced = !!(ipk & 0x40);
            const minCode = b[pos++];
            const [data, next] = readSubBlocks(b, pos);
            pos = next;
            if (!ct) continue;
            const idx = lzwDecode(minCode, data, iw * ih);

            // Disposal 3 needs the picture as it was before this frame.
            const before = gce.disposal === 3 ? canvas.slice() : null;

            // Interlaced rows come in four passes.
            const rowOrder = new Array(ih);
            if (interlaced) {
                let r = 0;
                for (const [start, step] of [[0, 8], [4, 8], [2, 4], [1, 2]]) {
                    for (let y = start; y < ih; y += step) rowOrder[r++] = y;
                }
            } else {
                for (let y = 0; y < ih; y++) rowOrder[y] = y;
            }
            for (let r = 0; r < ih; r++) {
                const y = iy + rowOrder[r];
                if (y >= height) continue;
                for (let x = 0; x < iw; x++) {
                    const px = ix + x;
                    if (px >= width) continue;
                    const ci = idx[r * iw + x];
                    if (ci === gce.transparent) continue;
                    const c = ct[ci];
                    if (!c) continue;
                    const o = (y * width + px) * 4;
                    canvas[o] = c[0]; canvas[o + 1] = c[1]; canvas[o + 2] = c[2]; canvas[o + 3] = 255;
                }
            }
            frames.push({ rgba: canvas.slice(), delay: gce.delay });
            total += gce.delay;

            // Dispose for the NEXT frame.
            if (gce.disposal === 2) {
                for (let r = 0; r < ih; r++) {
                    const y = iy + r;
                    if (y >= height) continue;
                    for (let x = 0; x < iw; x++) {
                        const px = ix + x;
                        if (px >= width) continue;
                        const o = (y * width + px) * 4;
                        canvas[o] = 0; canvas[o + 1] = 0; canvas[o + 2] = 0; canvas[o + 3] = 0;
                    }
                }
            } else if (gce.disposal === 3 && before) {
                canvas.set(before);
            }
            gce = { delay: 100, transparent: -1, disposal: 0 };
        }
        return finish();

        function finish() {
            if (frames.length < 2) return null;
            void bgIndex;
            return { width, height, frames, total: total || frames.length * 100 };
        }
    }

    /** The composed frame index for a moment `elapsedMs` into the loop. */
    function frameAt(anim, elapsedMs) {
        if (!anim || !anim.frames.length) return 0;
        let t = ((elapsedMs % anim.total) + anim.total) % anim.total;
        for (let i = 0; i < anim.frames.length; i++) {
            t -= anim.frames[i].delay;
            if (t < 0) return i;
        }
        return anim.frames.length - 1;
    }

    /**
     * Playback state for one preview surface. `attach(src)` decodes (null
     * for anything that is not a multi-frame GIF); `draw(ctx, w, h)` paints
     * the frame for "now" scaled to w x h, pixelated, and returns false when
     * there is nothing animated to draw (caller falls back to its static
     * path). Frames are composed into an offscreen canvas only when the
     * index changes, so an idle bench costs one drawImage per tick.
     */
    class Player {
        constructor() { this.anim = null; this.src = null; this.startedAt = 0; this.index = -1; this.off = null; }
        attach(src) {
            if (src === this.src) return !!this.anim;
            this.src = src;
            this.anim = decode(src);
            this.index = -1;
            this.startedAt = (typeof performance !== "undefined" ? performance.now() : Date.now());
            if (this.anim) {
                this.off = document.createElement("canvas");
                this.off.width = this.anim.width;
                this.off.height = this.anim.height;
            } else {
                this.off = null;
            }
            return !!this.anim;
        }
        clear() { this.anim = null; this.src = null; this.off = null; this.index = -1; }
        get active() { return !!this.anim; }
        frameIndex(nowMs) {
            return frameAt(this.anim, (nowMs === undefined ? (typeof performance !== "undefined" ? performance.now() : Date.now()) : nowMs) - this.startedAt);
        }
        draw(ctx, w, h, nowMs) {
            if (!this.anim || !this.off) return false;
            const i = this.frameIndex(nowMs);
            if (i !== this.index) {
                const f = this.anim.frames[i];
                this.off.getContext("2d").putImageData(new ImageData(f.rgba, this.anim.width, this.anim.height), 0, 0);
                this.index = i;
            }
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(this.off, 0, 0, w, h);
            return true;
        }
    }

    window.GifFrames = { decode, frameAt, Player, _lzwDecode: lzwDecode };
})();
