#!/usr/bin/env python3
"""spp_bridge.py — Subprocess bridge for Divoom Bluetooth Classic SPP.
Pipes hex-JSON messages between divoomd (Rust) and BTSppTransport (Python/IOBluetooth).
"""
import sys
import os
import json
import asyncio
import logging
from pathlib import Path

# Add project root to python path so divoom_lib resolves
sys.path.append(str(Path(__file__).resolve().parents[1]))

from divoom_lib.bt_spp_transport import BTSppTransport

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("divoom_spp_bridge")

async def read_stdin_loop(transport: BTSppTransport):
    # Setup async stdin reader
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = json.loads(line.decode().strip())
            cmd = req.get("command")
            if cmd == "write":
                payload = req.get("payload", [])
                framing = req.get("framing", "basic")
                packet_number = req.get("packet_number", 0)
                await transport.send(payload, framing=framing, packet_number=packet_number)
            elif cmd == "disconnect":
                break
        except Exception as e:
            logger.error(f"Error handling stdin command: {e}")
            print(json.dumps({"type": "error", "error": str(e)}), flush=True)

async def read_notifications_loop(transport: BTSppTransport):
    while True:
        try:
            # BTSppTransport puts dictionary with command_id and payload into notification_queue
            notif = await transport.notification_queue.get()
            print(json.dumps({
                "type": "notification",
                "command_id": notif["command_id"],
                "payload": list(notif["payload"])
            }), flush=True)
            transport.notification_queue.task_done()
        except Exception as e:
            logger.error(f"Error in notification loop: {e}")
            break

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mac", required=True)
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--kind", default="default")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    transport = BTSppTransport(
        mac_address=args.mac.replace(":", "-"),
        channel_id=args.channel,
        device_kind=args.kind,
        device_name=args.name
    )

    try:
        await transport.connect()
        print(json.dumps({"type": "connected", "mtu": transport.mtu}), flush=True)
    except Exception as e:
        print(json.dumps({"type": "disconnected", "error": str(e)}), flush=True)
        sys.exit(1)

    try:
        await asyncio.gather(
            read_stdin_loop(transport),
            read_notifications_loop(transport)
        )
    finally:
        await transport.disconnect()
        print(json.dumps({"type": "disconnected"}), flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
