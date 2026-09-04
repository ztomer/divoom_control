import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from divoom_lib.divoom import Divoom
from divoom_lib import models

@pytest.mark.asyncio
async def test_divoom_write_lock_serializes_calls():
    """Test that concurrent writes are serialized by the write lock."""
    config = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice", use_ios_le_protocol=False)
    divoom = Divoom(config)
    divoom.client = AsyncMock()
    divoom.client.is_connected = True
    divoom.client.write_gatt_char = AsyncMock()
    
    write_order = []
    
    async def slow_write(uuid, data, response=False):
        write_order.append(("start", data))
        await asyncio.sleep(0.1)
        write_order.append(("end", data))
        return True
        
    divoom.client.write_gatt_char.side_effect = slow_write
    
    # Launch two concurrent sends
    task1 = asyncio.create_task(divoom.send_command("set brightness", [50]))
    task2 = asyncio.create_task(divoom.send_command("set brightness", [80]))
    
    await asyncio.gather(task1, task2)
    
    assert len(write_order) == 4
    assert write_order[0][0] == "start"
    assert write_order[1][0] == "end"
    assert write_order[2][0] == "start"
    assert write_order[3][0] == "end"

@pytest.mark.asyncio
async def test_divoom_rate_limiting():
    """Test that rate limiting enforces at least 50ms delay between consecutive writes."""
    config = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", device_name="MockDevice", use_ios_le_protocol=False)
    divoom = Divoom(config)
    divoom.client = AsyncMock()
    divoom.client.is_connected = True
    divoom.client.write_gatt_char = AsyncMock()
    
    write_times = []
    
    async def quick_write(uuid, data, response=False):
        write_times.append(time.time())
        return True
        
    divoom.client.write_gatt_char.side_effect = quick_write
    
    # Send three commands in quick succession
    await divoom.send_command("set brightness", [50])
    await divoom.send_command("set brightness", [60])
    await divoom.send_command("set brightness", [70])
    
    assert len(write_times) == 3
    diff1 = write_times[1] - write_times[0]
    diff2 = write_times[2] - write_times[1]
    
    # The rate limiter ensures at least 0.05 seconds (50ms) between writes
    assert diff1 >= 0.045
    assert diff2 >= 0.045
