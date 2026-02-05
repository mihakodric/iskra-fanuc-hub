"""Fake FANUC client for development mode"""

import asyncio
import random
import time
import logging
from typing import Optional

from .fanuc_client import FanucClient, ToolData, ConnectionState

logger = logging.getLogger(__name__)


class FakeFanucClient(FanucClient):
    """Simulated FANUC client for development/testing"""
    
    def __init__(self, machine_id: str, ip: str, port: int = 8193):
        self.machine_id = machine_id
        self.ip = ip
        self.port = port
        self._connected = False
        self._state = ConnectionState.DISCONNECTED
        
        # Simulation state
        self._current_tools = {1: 1, 2: 1}  # Path -> tool number
        self._fail_rate = 0.0  # Probability of simulated failure
        self._connection_fail_count = 0
        
    async def connect(self) -> bool:
        """Simulate connection to CNC"""
        self._state = ConnectionState.CONNECTING
        logger.info(f"[{self.machine_id}] Simulating connection to {self.ip}:{self.port}")
        
        # Simulate connection delay
        await asyncio.sleep(0.1)
        
        # Simulate occasional connection failures
        if random.random() < 0.1:  # 10% failure rate
            self._connection_fail_count += 1
            logger.warning(f"[{self.machine_id}] Simulated connection failure #{self._connection_fail_count}")
            self._state = ConnectionState.ERROR
            return False
        
        self._connected = True
        self._state = ConnectionState.CONNECTED
        self._connection_fail_count = 0
        logger.info(f"[{self.machine_id}] Simulated connection successful")
        return True
    
    async def disconnect(self) -> None:
        """Simulate disconnection"""
        if self._connected:
            logger.info(f"[{self.machine_id}] Simulating disconnection from {self.ip}")
            await asyncio.sleep(0.05)
            self._connected = False
            self._state = ConnectionState.DISCONNECTED
    
    async def read_tool(self, path: int) -> Optional[ToolData]:
        """Simulate reading tool number"""
        if not self._connected:
            logger.error(f"[{self.machine_id}] Cannot read tool - not connected")
            return None
        
        # Simulate read delay
        await asyncio.sleep(0.01)
        
        # Simulate occasional read failures
        if random.random() < self._fail_rate:
            logger.error(f"[{self.machine_id}] Simulated read failure for path {path}")
            return None
        
        # Occasionally change tool (5% chance per read)
        if random.random() < 0.05:
            old_tool = self._current_tools[path]
            # Change to a different tool
            new_tool = random.choice([t for t in [2000, 2100, 2220, 2400] if t != old_tool])
            self._current_tools[path] = new_tool
            logger.debug(f"[{self.machine_id}] Simulated tool change path {path}: {old_tool} -> {new_tool}")
        
        return ToolData(
            tool_number=self._current_tools[path],
            path=path,
            timestamp_ms=int(time.time() * 1000)
        )
    
    @property
    def is_connected(self) -> bool:
        """Check if connected"""
        return self._connected
    
    @property
    def connection_state(self) -> ConnectionState:
        """Get connection state"""
        return self._state
    
    def set_fail_rate(self, rate: float) -> None:
        """Set simulated failure rate for testing (0.0 to 1.0)"""
        self._fail_rate = max(0.0, min(1.0, rate))
        logger.info(f"[{self.machine_id}] Set simulated failure rate to {self._fail_rate:.1%}")
    
    def set_tool(self, path: int, tool_number: int) -> None:
        """Manually set tool number for testing"""
        self._current_tools[path] = tool_number
        logger.info(f"[{self.machine_id}] Manually set path {path} tool to {tool_number}")
