# image_vectors.json is frozen reference data

`image_vectors.json` (192 palette-encoder cases: `frame`, `static`, `frame32`) is
the recorded output of the C encoder `libdivoom_compact`, captured densely (13
sizes x 6 colour counts, plus the time axis) and cross-checked against the
Python reference. `src/image_encode.rs` asserts every case byte for byte.

It is not regenerated. The oracle was the C library, which was deleted in L4
(9a1cade); `scripts/codegen/gen_image_vectors.py` needed that dylib and could
not run, so it was retired. Regenerating from a reimplementation would replace
the C's recorded behaviour with the port's own, which is the circularity the
vectors exist to prevent. The two refusals (zero dimension: the C refuses, the
Python reference emits a degenerate frame) are recorded as `"refused": true`.

Checked when it was retired (2026-11-07): the pure-Python encoders in
`examples/divoom_legacy/utils/` reproduce all 190 non-refused cases exactly.

To re-derive from the original C: `git ls-tree -r 9a1cade^ --name-only | grep native_src`.
