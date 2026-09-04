#!/usr/bin/env python3
"""
R14 §1 — example: set the weather channel on a Divoom device.

Usage::

    python examples/set_weather.py --mac AA:BB:CC:DD:EE:FF --temperature 18 --weather clear
    python examples/set_weather.py --mac AA:BB:CC:DD:EE:FF --temperature -5 --weather snow
    python examples/set_weather.py --mac AA:BB:CC:DD:EE:FF --temperature 25      # weather unchanged

Weather types: clear, cloudy, thunderstorm, rain, snow, fog.
"""
import argparse
import asyncio
import logging
import sys

from divoom_lib import Divoom
from divoom_lib.models import WeatherType


WEATHER_NAMES = {
    "clear":        WeatherType.Clear,
    "cloudy":       WeatherType.CloudySky,
    "thunderstorm": WeatherType.Thunderstorm,
    "rain":         WeatherType.Rain,
    "snow":         WeatherType.Snow,
    "fog":          WeatherType.Fog,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set the Divoom device's weather channel.")
    parser.add_argument("--mac", required=True, help="BLE MAC address of the device")
    parser.add_argument("--temperature", type=int, required=True,
                        help="Temperature in Celsius (range: -127..128)")
    parser.add_argument("--weather", choices=sorted(WEATHER_NAMES.keys()), default="clear",
                        help="Weather condition (default: clear)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    divoom = Divoom(mac=args.mac, device_name="example-set-weather")
    try:
        await divoom.connect()
        weather_type = WEATHER_NAMES[args.weather]
        ok = await divoom.weather.set(args.temperature, weather_type)
        if ok:
            print(f"OK: sent weather={args.weather} ({weather_type}), "
                  f"temperature={args.temperature}°C")
            return 0
        else:
            print("ERROR: send_command returned False", file=sys.stderr)
            return 1
    finally:
        try:
            await divoom.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
