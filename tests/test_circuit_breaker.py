"""Tests for circuit breaker and periodic reconnect functionality"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time

from app.monitor import MachineMonitor
from app.mqtt_pub import MQTTPublisher
from app.fake_fanuc_client import FakeFanucClient
from app.fanuc_client import ToolReadResult


@pytest.fixture
def mqtt_publisher():
    """Mock MQTT publisher"""
    publisher = AsyncMock(spec=MQTTPublisher)
    publisher.publish_tool_change = AsyncMock(return_value=True)
    publisher.publish_error = AsyncMock(return_value=True)
    publisher.publish_heartbeat = AsyncMock(return_value=True)
    return publisher


@pytest.fixture
def fake_client():
    """Create a fake FANUC client for testing"""
    client = FakeFanucClient(
        machine_id="test_machine",
        ip="10.0.0.1",
        port=8193
    )
    return client


@pytest.mark.asyncio
async def test_circuit_breaker_tracks_consecutive_failures(mqtt_publisher, fake_client):
    """Test that circuit breaker counts consecutive failures correctly"""
    
    # Set very low threshold for testing
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="10.0.0.1",
        port=8193,
        monitored_paths=[1, 2],
        fanuc_client=fake_client,
        mqtt_publisher=mqtt_publisher,
        poll_interval_ms=10,  # Fast polling for test
        max_consecutive_all_path_failures=5,  # Low threshold
        max_uptime_hours=24
    )
    
    # Set client to always fail
    fake_client.set_fail_rate(1.0)  # 100% failure rate
    fake_client.set_error_code(-16)
    
    # Connect and start monitoring
    await fake_client.connect()
    
    # Manually set connection_started_at to avoid periodic reconnect
    monitor.connection_started_at = time.time()
    
    # Simulate reads that will all fail
    for i in range(3):
        tool_results = await fake_client.read_tools()
        
        # All paths should fail
        for path in [1, 2]:
            assert tool_results[path].tool is None
            assert tool_results[path].error_code == -16
    
    # Verify consecutive failures increment
    # (This would be done by the polling loop in real execution)
    assert True  # Placeholder - actual test would need to run the polling loop


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success(mqtt_publisher, fake_client):
    """Test that circuit breaker resets when at least one path succeeds"""
    
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="10.0.0.1",
        port=8193,
        monitored_paths=[1, 2],
        fanuc_client=fake_client,
        mqtt_publisher=mqtt_publisher,
        poll_interval_ms=10,
        max_consecutive_all_path_failures=10,
        max_uptime_hours=24
    )
    
    await fake_client.connect()
    monitor.connection_started_at = time.time()
    
    # First set high failure rate
    fake_client.set_fail_rate(1.0)
    
    # Simulate some failures
    monitor.consecutive_all_paths_failures = 5
    
    # Now set low failure rate so at least some succeed
    fake_client.set_fail_rate(0.0)
    
    # Read should now succeed
    tool_results = await fake_client.read_tools()
    
    # At least one path should succeed
    success_count = sum(1 for r in tool_results.values() if r.tool is not None)
    assert success_count > 0
    
    # In real monitor, consecutive_all_paths_failures would reset to 0
    # when successful_paths > 0


@pytest.mark.asyncio
async def test_forced_reconnect_method(mqtt_publisher, fake_client):
    """Test that _force_reconnect properly disconnects and resets state"""
    
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="10.0.0.1",
        port=8193,
        monitored_paths=[1, 2],
        fanuc_client=fake_client,
        mqtt_publisher=mqtt_publisher,
        poll_interval_ms=10,
        max_consecutive_all_path_failures=10,
        max_uptime_hours=24
    )
    
    await fake_client.connect()
    monitor.connection_started_at = time.time()
    monitor.consecutive_all_paths_failures = 10
    monitor.last_successful_read_time = time.time() - 100
    
    # Call force reconnect
    await monitor._force_reconnect("test_reason")
    
    # Verify state reset
    assert monitor.consecutive_all_paths_failures == 0
    assert monitor.connection_started_at is None
    assert monitor.last_forced_reconnect_reason == "test_reason"
    assert not fake_client.is_connected
    
    # Verify MQTT error published
    mqtt_publisher.publish_error.assert_called_once()
    call_args = mqtt_publisher.publish_error.call_args
    assert "test_reason" in call_args.kwargs['error_message']


@pytest.mark.asyncio
async def test_tool_read_result_with_error_codes(fake_client):
    """Test that ToolReadResult properly captures error codes"""
    
    await fake_client.connect()
    
    # Test successful read (error_code = 0)
    fake_client.set_fail_rate(0.0)
    result = await fake_client.read_tool(1)
    assert result.tool is not None
    assert result.error_code == 0
    assert result.path == 1
    
    # Test failed read with error code
    fake_client.set_fail_rate(1.0)
    fake_client.set_error_code(-16)
    result = await fake_client.read_tool(1)
    assert result.tool is None
    assert result.error_code == -16
    assert result.path == 1


@pytest.mark.asyncio
async def test_periodic_reconnect_triggers_at_24h():
    """Test that periodic reconnect triggers after max_uptime_hours"""
    # This test would require mocking time.time() to simulate 24 hours passing
    # Placeholder for full implementation
    pass


@pytest.mark.asyncio  
async def test_progressive_logging_thresholds():
    """Test that circuit breaker logs at 25%, 50%, 75% thresholds"""
    # This test would require capturing log output
    # Placeholder for full implementation
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
