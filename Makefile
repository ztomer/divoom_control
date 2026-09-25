.PHONY: test test-hardware

# Run the unit suite.
#
# There is no `native` target any more: the C encoder dylib it built is gone
# (phase L4), and the encoders it held are Rust inside the daemon binary, so
# there is nothing to compile before running the tests. `cargo test` covers
# those.
test:
	python3 -m pytest -q

# Include the BLE hardware-integration tests (needs a real device + BT grant).
test-hardware: native
	python3 -m pytest -q --run-hardware

clean-native:
	rm -f divoom_lib/libdivoom_compact.dylib divoom_lib/libdivoom_compact.so divoom_lib/libdivoom_compact.dll
