import asyncio
import logging
import os
import sys

from divoom_lib.divoom import Divoom
from divoom_lib.utils import discovery
from divoom_lib.utils import cache

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("integration_test_runner")

# List of tests to run
tests_to_run = []

def test_case(func):
    """Decorator to register a test case."""
    tests_to_run.append(func)
    return func

@test_case
async def test_set_and_get_brightness():
    """
    Tests setting and then getting the device brightness to verify it was set correctly.
    """
    logger.info("--- Running test: test_set_and_get_brightness ---")
    divoom = None
    original_brightness = None
    try:
        # Discover and connect
        ble_device, device_id = await discovery.discover_device(name_substring="Timoo")
        if not ble_device:
            raise ConnectionError("No Divoom device found.")
        
        logger.info(f"Found device: {device_id}")
        divoom = Divoom(mac=device_id, logger=logger)
        await divoom.protocol.connect()
        logger.info(f"Successfully connected to {divoom.protocol.mac}!")

        # 1. Get initial brightness
        logger.info("Getting initial brightness...")
        initial_brightness = await divoom.system.get_brightness()
        if initial_brightness is None:
            raise AssertionError("Failed to get initial brightness.")
        original_brightness = initial_brightness
        logger.info(f"Initial brightness is: {original_brightness}")

        # 2. Set new brightness
        new_brightness = 50
        if new_brightness == original_brightness:
            new_brightness = 75
        
        logger.info(f"Setting brightness to {new_brightness}...")
        await divoom.system.set_brightness(new_brightness)
        logger.info("Set brightness command sent.")
        
        await asyncio.sleep(3)

        # 3. Get brightness again and verify
        logger.info("Getting brightness again to verify...")
        current_brightness = await divoom.system.get_brightness()
        if current_brightness is None:
            raise AssertionError("Failed to get current brightness.")
        logger.info(f"Current brightness is: {current_brightness}")
        
        assert current_brightness == new_brightness, f"Brightness was not set correctly. Expected {new_brightness}, got {current_brightness}."
        
        return True, "Test passed."

    except Exception as e:
        logger.error(f"Test failed with an exception: {e}", exc_info=True)
        return False, str(e)
    finally:
        # 4. Restore original brightness and disconnect
        if divoom and divoom.protocol.is_connected:
            if original_brightness is not None:
                logger.info(f"Restoring original brightness to {original_brightness}...")
                await divoom.device.set_brightness(original_brightness)
            await divoom.protocol.disconnect()
            logger.info("Disconnected from Divoom device.")

async def main():
    """
    Main function to run all registered test cases.
    This script is used instead of pytest or unittest because those frameworks
    interfere with the bleak library's async notification handling.
    """
    logger.info("Starting Divoom Integration Test Suite")
    results = {}
    all_passed = True

    for test_func in tests_to_run:
        test_name = test_func.__name__
        passed, message = await test_func()
        results[test_name] = {"passed": passed, "message": message}
        if passed:
            logger.info(f"[  OK  ] {test_name}")
        else:
            logger.error(f"[ FAIL ] {test_name}: {message}")
            all_passed = False
    
    logger.info("\n--- Test Summary ---")
    for name, result in results.items():
        status = "OK" if result["passed"] else "FAIL"
        logger.info(f"[{status:^6s}] {name}")

    if not all_passed:
        logger.error("\nSome tests failed.")
        sys.exit(1)
    else:
        logger.info("\nAll tests passed!")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
