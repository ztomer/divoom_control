# Round 64 — Gallery: decode the rest (magic 8 / 12) + broken-image removal

Follow-up to Round 63. Symptom: "a lot more gallery images render now, but
not all." Root-caused with a live probe across **all 16 categories** (455
items) using the exact `get_animated_preview` decode chain.

## Findings (probe-first, ground truth)

Two independent gaps, both confirmed live against the real Divoom CDN:

1. **Packaging bug (broad).** `decode_cloud_frames` needs `Crypto`
   (magic 9/18/26) and `lzallright` (18/26), but **neither is a declared
   dependency**. The dev box only renders because `Crypto` happens to be
   installed globally in system python. A clean install / the DMG would render
   *zero* cloud items. This is silently masked on the maintainer's machine.
   - First probe (no Crypto in `.buildvenv`): **455/455 fail** with
     `No module named 'Crypto'`. After `pip install pycryptodome lzallright`:
     **29/455 fail** — all are magic 8 (19) and magic 12 (10).

2. **Format gap (the "not all").** `decode_cloud_frames` only handles
   magic 9 / 18 / 26. The remaining 29 items are:
   - **magic 8** (`W2.b.s`): AES-CBC container, strip 1 header byte,
     decrypt with the *same* key/IV as magic 9
     (`78hrey23y28ogs89` / `1234567890123456`), result = 768 bytes
     (16×16 RGB) → a static image. **Verified live**: decrypts to a clean
     16×16 image (extrema non-black).
   - **magic 12** (`W2.b.v`): AES-CBC container, header
     `[12][scrollMode][speed:2 BE]`, strip 4 bytes, decrypt → 3072-byte
     (64×16) **scroll/marquee** buffer (type 6). Verified live: decrypts to
     a 64×16 RGB buffer.
   Both fall through `decode_cloud_frames` → `decode_and_save_preview`
   returns False → no preview file → item shows the `pixoo.png` placeholder
   instead of art (reads as "not rendered").

3. **Stale black previews persist.** `fetch_gallery_asset` short-circuits on
   `has_preview()` — if a corrupt/all-black `.gif`/`.png` already exists on
   disk (e.g. from a pre-R63 broken run), it is reused forever and never
   re-decoded → permanent black tile. The corrupt-`.bin` recovery added in
   R63 does not cover this because the bad *preview* (not `.bin`) is what's
   cached.

## Workstreams (maps 1:1 to the requested plan)

### (1) Detect & remove broken images — runtime + load time
- **Load time** (`divoom_gui/gallery_download.py::fetch_gallery_asset`):
  add `validate_preview()` — open any existing `.gif/.png/.jpg`; if it fails
  to open OR is all-black/all-transparent, delete it (so the asset is
  re-decoded in the same pass). Replaces the blind `has_preview()` trust.
- **Runtime** (`divoom_gui/web_ui/gallery.js`): add an `onerror` handler on
  the `.gallery-item-preview` `<img>`; on a broken/empty src, **remove the
  tile** (per "remove them"), not just mark unavailable. Keep the distinct
  "permanently unavailable" state only for region-locked (`IsNew`) items.
- Add `media_decoder.is_black_image(path)` helper (shared by both).

### (2) Decode magic 8 and 12 (the "why some fail")
- Extend `divoom_lib/media_decoder.py::decode_cloud_frames` with magic 8 and
  12 branches (AES decrypt with the existing `_CLOUD_AES_KEY`/`_CLOUD_AES_IV`,
  already imported lazily). magic 8 → single 16×16 frame; magic 12 → a
  64×16 frame from the scroll buffer. Both flow through the existing
  `decode_and_save_preview` → `.gif`/`.png` path automatically.
- Add `pycryptodome` **and** `lzallright` to `pyproject.toml`
  dependencies (fixes the clean-install / DMG packaging bug). Verify the DMG
  build spec pulls install_requires.

### (3) Verify the problem does not recur
- Record the two live samples as fixtures
  (`tests/fixtures/gallery_magic8.bin`, `...magic12.bin`) and add tests:
  - `decode_cloud_frames` returns a non-black frame for magic 8 and 12.
  - `decode_and_save_preview` writes a preview file for both.
  - `validate_preview` drops an all-black file and re-decodes.
- Full pytest suite must stay green; `check_no_emoji.py` / `check_file_size.py`
  (500-LOC gate) clean.

### (4) Iterate every category to verify all images render
- **Create the missing tooling**: `scripts/verify_gallery_render.py` — an
  offscreen-render harness that, for **all 16 categories**, downloads each
  asset, runs the full `get_animated_preview` decode chain, renders every
  decoded frame to a per-category **contact sheet** PNG, and asserts **zero
  all-black frames**. This is the headless "render every item" check (the
  `media_decoder` pipeline is the single source of truth that feeds the UI,
  so decoding it == what the UI shows — no unix-socket GUI driver needed).
- Run it and confirm 0 black frames across all 16 categories.

## Files touched
- `pyproject.toml` — add `pycryptodome`, `lzallright` deps.
- `divoom_lib/media_decoder.py` — magic 8/12 in `decode_cloud_frames`;
  new `is_black_image` helper.
- `divoom_gui/gallery_download.py` — `validate_preview`, drop stale/black
  previews at load time.
- `divoom_gui/web_ui/gallery.js` — `<img onerror>` removes the tile.
- `tests/fixtures/gallery_magic{8,12}.bin` — recorded samples.
- `tests/test_gallery_sync_coverage.py` (extend) + new decode tests.
- `scripts/verify_gallery_render.py` — new offscreen contact-sheet harness.
- `docs/SESSION_HANDOFF.md`, `CHANGELOG.md` — per repo convention.

## Rollout
Fix lands on `main`; ship as a patch release (v0.22.20) via `scripts/release.sh`
once tests + the all-category harness are green.

## Outcome

All four workstreams done; green across the board.

- **(1) Detect & remove broken images.** `media_decoder.is_black_image(path)`
  added (CONSERVATIVE: broken = unreadable / degenerate (0-size) / fully-
  transparent; solid-color & near-black **art is valid, NOT dropped** — an
  over-strict uniform-color check was reverted after the harness produced a
  false positive on `*coding*` near-black animation). `gallery_download.
  fetch_gallery_asset` now runs `preview_valid()` which drops a cached preview
  if `is_black_image` (and unlinks the `.bin`), then re-downloads + decodes
  it in the same pass. `web_ui/gallery.js`: `removeTile(item)` added; the
  preview `<img>` has an `onerror` handler that removes the tile when a broken
  cached preview fails to load; the decode-failed path now removes the tile
  (previously left a dead `is-unavailable` skeleton).
- **(2) Decode magic 8 & 12.** `decode_cloud_frames` gained magic 8 (static
  AES image — strip 1 header byte, decrypt with `_CLOUD_AES_KEY/_CLOUD_AES_IV`
  → 16×16) and magic 12 (scroll buffer `[12][scrollMode][speed:2 BE]`, strip
  4, decrypt → 64×16) branches; `CLOUD_CONTAINER_MAGICS = (8, 9, 12, 18, 26)`.
  `pyproject.toml` + `requirements.txt` now declare `pycryptodome` and
  `lzallright`; `divoom.spec` force-collects `Crypto`/`lzallright` so
  PyInstaller bundles them (clean-install DMG now has Crypto).
- **(3) Verify no recurrence.** Fixtures `tests/fixtures/gallery_magic{8,12}.bin`
  recorded live; `test_media_decoder_cloud.py` covers magic 8/12 decode +
  `decode_and_save_preview` + `is_black_image`; `test_gallery_sync_coverage.py`
  adds 3 drop/redownload cases. Full suite green (2715 passed / 94 skipped;
  the 4 numpy-gated modules are excluded on this box — pre-existing env gap).
  Emoji + 500-LOC gates clean.
- **(4) Iterate every category.** `scripts/verify_gallery_render.py` built —
  for all 16 categories it downloads each asset, runs the full
  `get_animated_preview` decode chain, renders decode-cycle frames to per-category
  contact sheets in `/tmp/gallery_sheets/cat_<c>.png`, and asserts zero all-black
  frames. **Final run: 455 items across 16 categories, 0 UNDECODABLE, 0 blank
  frames** (the pre-fix run was 29 undecodable — exactly the magic 8/12 items).

**Status: code + tests + gates complete, version bumped to 0.22.20, CHANGELOG/
SESSION_HANDOFF updated. NOT YET RELEASED** — user asked to "fix", not ship, and
they can re-check the live gallery. Cut v0.22.20 via `scripts/release.sh` once
the live render is confirmed.
