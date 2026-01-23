"""Tests for tool change detection and debouncing"""

import pytest
import asyncio
from app.monitor import MachineMonitor, PathState
from app.fake_fanuc_client import FakeFanucClient
from app.mqtt_pub import MQTTPublisher


class MockMQTTPublisher:
    """Mock MQTT publisher for testing"""
    
    def __init__(self):
        self.tool_changes = []
        self.errors = []
        self.heartbeats = []
        self._connected = True
    
    async def publish_tool_change(self, machine_id, path, ip, tool_previous, tool_current):
        self.tool_changes.append({
            'machine_id': machine_id,
            'path': path,
            'tool_previous': tool_previous,
            'tool_current': tool_current
        })
        return True
    
    async def publish_error(self, machine_id, path, ip, error_message):
        self.errors.append({
            'machine_id': machine_id,
            'path': path,
            'error': error_message
        })
        return True
    
    async def publish_heartbeat(self, machine_id, ip, connected, path_status, path_errors):
        self.heartbeats.append({
            'machine_id': machine_id,
            'connected': connected,
            'path_status': path_status
        })
        return True
    
    @property
    def is_connected(self):
        return self._connected


@pytest.mark.asyncio
async def test_tool_change_edge_triggered():
    """Test that tool changes are published exactly once per transition"""
    
    # Setup
    fake_client = FakeFanucClient("test_machine", "192.168.1.1")
    mock_mqtt = MockMQTTPublisher()
    
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="192.168.1.1",
        port=8193,
        monitored_paths=[1],
        fanuc_client=fake_client,
        mqtt_publisher=mock_mqtt,
        poll_interval_ms=50,
        debounce_consecutive_reads=2,
        heartbeat_interval_s=10
    )
    
    # Connect fake client
    await fake_client.connect()
    
    # Set initial tool
    fake_client.set_tool(1, 5)
    
    # Start monitor
    await monitor.start()
    
    # Wait for initial detection
    await asyncio.sleep(0.3)
    
    # Should have no tool changes yet (initial detection doesn't publish)
    assert len(mock_mqtt.tool_changes) == 0
    
    # Change tool
    fake_client.set_tool(1, 12)
    
    # Wait for debounce (2 reads at 50ms = 100ms minimum)
    await asyncio.sleep(0.3)
    
    # Should have exactly one tool change
    assert len(mock_mqtt.tool_changes) == 1
    assert mock_mqtt.tool_changes[0]['tool_previous'] == 5
    assert mock_mqtt.tool_changes[0]['tool_current'] == 12
    
    # Wait more - should not publish duplicate
    await asyncio.sleep(0.3)
    assert len(mock_mqtt.tool_changes) == 1
    
    # Change tool again
    fake_client.set_tool(1, 8)
    await asyncio.sleep(0.3)
    
    # Should have two total changes
    assert len(mock_mqtt.tool_changes) == 2
    assert mock_mqtt.tool_changes[1]['tool_previous'] == 12
    assert mock_mqtt.tool_changes[1]['tool_current'] == 8
    
    # Cleanup
    await monitor.stop()


@pytest.mark.asyncio
async def test_debounce_prevents_noise():
    """Test that debouncing prevents false tool changes from noise"""
    
    # Setup
    fake_client = FakeFanucClient("test_machine", "192.168.1.1")
    mock_mqtt = MockMQTTPublisher()
    
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="192.168.1.1",
        port=8193,
        monitored_paths=[1],
        fanuc_client=fake_client,
        mqtt_publisher=mock_mqtt,
        poll_interval_ms=50,
        debounce_consecutive_reads=3,  # Require 3 consecutive reads
        heartbeat_interval_s=10
    )
    
    await fake_client.connect()
    fake_client.set_tool(1, 5)
    
    await monitor.start()
    await asyncio.sleep(0.3)
    
    # Simulate noisy tool reads by manually manipulating path state
    path_state = monitor.path_states[1]
    
    # Process flicker: 5 -> 7 -> 5 -> 7
    await monitor._process_tool_read(path_state, 7)  # First read of 7
    await monitor._process_tool_read(path_state, 5)  # Back to 5 (resets counter)
    await monitor._process_tool_read(path_state, 7)  # First read of 7 again
    
    # Should have no tool changes due to flicker
    assert len(mock_mqtt.tool_changes) == 0
    
    # Now stable reads: 7, 7, 7
    await monitor._process_tool_read(path_state, 7)  # Second consecutive
    await monitor._process_tool_read(path_state, 7)  # Third consecutive
    
    # Now should have detected the change
    assert len(mock_mqtt.tool_changes) == 1
    assert mock_mqtt.tool_changes[0]['tool_current'] == 7
    
    await monitor.stop()


@pytest.mark.asyncio
async def test_dual_path_independence():
    """Test that path 1 and path 2 are monitored independently"""
    
    fake_client = FakeFanucClient("test_machine", "192.168.1.1")
    mock_mqtt = MockMQTTPublisher()
    
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="192.168.1.1",
        port=8193,
        monitored_paths=[1, 2],  # Monitor both paths
        fanuc_client=fake_client,
        mqtt_publisher=mock_mqtt,
        poll_interval_ms=50,
        debounce_consecutive_reads=2,
        heartbeat_interval_s=10
    )
    
    await fake_client.connect()
    fake_client.set_tool(1, 5)
    fake_client.set_tool(2, 10)
    
    await monitor.start()
    await asyncio.sleep(0.3)
    
    # Change path 1 only
    fake_client.set_tool(1, 12)
    await asyncio.sleep(0.3)
    
    # Should have one change for path 1
    assert len(mock_mqtt.tool_changes) == 1
    assert mock_mqtt.tool_changes[0]['path'] == 1
    assert mock_mqtt.tool_changes[0]['tool_current'] == 12
    
    # Change path 2 only
    fake_client.set_tool(2, 15)
    await asyncio.sleep(0.3)
    
    # Should have second change for path 2
    assert len(mock_mqtt.tool_changes) == 2
    assert mock_mqtt.tool_changes[1]['path'] == 2
    assert mock_mqtt.tool_changes[1]['tool_current'] == 15
    
    await monitor.stop()


@pytest.mark.asyncio
async def test_path_failure_isolation():
    """Test that one path failing doesn't stop monitoring other paths"""
    
    fake_client = FakeFanucClient("test_machine", "192.168.1.1")
    mock_mqtt = MockMQTTPublisher()
    
    # Set high fail rate to simulate read errors
    fake_client.set_fail_rate(0.9)  # 90% failure rate
    
    monitor = MachineMonitor(
        machine_id="test_machine",
        ip="192.168.1.1",
        port=8193,
        monitored_paths=[1, 2],
        fanuc_client=fake_client,
        mqtt_publisher=mock_mqtt,
        poll_interval_ms=50,
        debounce_consecutive_reads=2,
        heartbeat_interval_s=10
    )
    
    await fake_client.connect()
    fake_client.set_tool(1, 5)
    fake_client.set_tool(2, 10)
    
    await monitor.start()
    
    # Wait for some polling
    await asyncio.sleep(0.5)
    
    # Should have published error events
    assert len(mock_mqtt.errors) > 0
    
    # Heartbeat should show error status for some paths
    assert len(mock_mqtt.heartbeats) > 0
    
    await monitor.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
