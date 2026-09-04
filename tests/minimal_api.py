import argparse
import asyncio
import logging
import os
import sys

from divoom_lib.divoom import Divoom
from divoom_lib.utils import discovery

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("minimal_api_test")

async def main():
    """
    Connects to a Divoom device and sends a command to set the device's light to blue.
    """
    parser = argparse.ArgumentParser(description="Divoom Minimal API Test Script")
    parser.add_argument(
        "--address", help="BLE address / identifier of the target device")
    parser.add_argument("--name", default="Timoo",
                        help="Device name substring to search for (e.g., 'Timoo')")
    args = parser.parse_args()

    divoom = None
    try:
        if args.address:
            divoom = Divoom(mac=args.address, logger=logger)
        else:
            ble_device, device_id = await discovery.discover_device(name_substring=args.name, address=None)
            if not ble_device:
                logger.error(
                    f"No Bluetooth device found with name containing '{args.name}'. Exiting.")
                return
            divoom = Divoom(mac=device_id, logger=logger)

        await divoom.protocol.connect()
        logger.info(f"Successfully connected to {divoom.protocol.mac}!")

        logger.info("Sending green light command...")
        await divoom.display.light.show_light(color="00FF00", brightness=100)
        logger.info("Command sent successfully.")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if divoom and divoom.protocol.is_connected:
            await divoom.protocol.disconnect()
            logger.info("Disconnected from Divoom device.")

if __name__ == "__main__":
    import traceback
    import sys

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        try:
            sys.exit(0)
        except SystemExit:
            pass
    except Exception as e:
        logger.error("Unhandled exception in minimal_api_test: printing traceback:")
        traceback.print_exc()
        logger.error(f"Exception: {e}")
        sys.exit(1)