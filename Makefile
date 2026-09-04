.PHONY: native test test-hardware clean-native

# Build the native dylib (palette encoder, downsampler, framing).
native:
	bash scripts/build_libdivoom.sh

# Run the unit suite. conftest auto-rebuilds the dylib if missing/stale, so the
# dual-impl encoder tests (test_encoder_both_impls.py) exercise BOTH C + Python.
test: native
	python3 -m pytest -q

# Include the BLE hardware-integration tests (needs a real device + BT grant).
test-hardware: native
	python3 -m pytest -q --run-hardware

clean-native:
	rm -f divoom_lib/libdivoom_compact.dylib divoom_lib/libdivoom_compact.so divoom_lib/libdivoom_compact.dll
