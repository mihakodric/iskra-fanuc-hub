"""Machine monitor with per-path tool change detection"""

import asyncio
import logging
import random
import time
from typing import Dict, Optional, List
from dataclasses import dataclass

from .fanuc_client import FanucClient, ToolData
from .mqtt_pub import MQTTPublisher

logger = logging.getLogger(__name__)


@dataclass
class PathState:
    """State for a single monitored path"""
    path: int
    current_tool: Optional[int] = None
    stable_tool: Optional[int] = None
    consecutive_reads: int = 0
    status: str = "ok"  # "ok" or "error"
    error_message: Optional[str] = None
    last_error_publish_time: float = 0


class MachineMonitor:
    """Monitors a single CNC machine with multiple paths"""
    
    def __init__(
        self,
        machine_id: str,
        ip: str,
        port: int,
        monitored_paths: List[int],
        fanuc_client: FanucClient,
        mqtt_publisher: MQTTPublisher,
        poll_interval_ms: int = 100,
        debounce_consecutive_reads: int = 2,
        heartbeat_interval_s: int = 2,
        reconnect_min_delay_s: float = 0.5,
        reconnect_max_delay_s: float = 30.0
    ):
        self.machine_id = machine_id
        self.ip = ip
        self.port = port
        self.monitored_paths = monitored_paths
        self.fanuc_client = fanuc_client
        self.mqtt_publisher = mqtt_publisher
        
        self.poll_interval_ms = poll_interval_ms
        self.debounce_consecutive_reads = debounce_consecutive_reads
        self.heartbeat_interval_s = heartbeat_interval_s
        self.reconnect_min_delay_s = reconnect_min_delay_s
        self.reconnect_max_delay_s = reconnect_max_delay_s
        
        # Path states
        self.path_states: Dict[int, PathState] = {
            path: PathState(path=path) for path in monitored_paths
        }
        
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        logger.info(f"[{self.machine_id}] Monitor initialized for {len(monitored_paths)} path(s)")
    
    async def start(self) -> None:
        """Start monitoring"""
        if self._running:
            logger.warning(f"[{self.machine_id}] Monitor already running")
            return
        
        self._running = True
        
        # Start connection manager
        self._tasks.append(asyncio.create_task(self._connection_manager()))
        
        # Start heartbeat
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        
        # Start monitor for each path
        for path in self.monitored_paths:
            task = asyncio.create_task(self._monitor_path(path))
            self._tasks.append(task)
        
        logger.info(f"[{self.machine_id}] Monitor started")
    
    async def stop(self) -> None:
        """Stop monitoring"""
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        # Disconnect from CNC
        await self.fanuc_client.disconnect()
        
        logger.info(f"[{self.machine_id}] Monitor stopped")
    
    async def _connection_manager(self) -> None:
        """Manage connection to CNC with exponential backoff"""
        retry_delay = self.reconnect_min_delay_s
        
        while self._running:
            try:
                if not self.fanuc_client.is_connected:
                    logger.info(f"[{self.machine_id}] Attempting connection to {self.ip}:{self.port}")
                    
                    success = await self.fanuc_client.connect()
                    
                    if success:
                        retry_delay = self.reconnect_min_delay_s  # Reset delay
                        logger.info(f"[{self.machine_id}] Connection successful")
                    else:
                        # Exponential backoff with jitter
                        jitter = random.uniform(0.8, 1.2)
                        delay = min(retry_delay * jitter, self.reconnect_max_delay_s)
                        logger.warning(f"[{self.machine_id}] Connection failed, retrying in {delay:.1f}s")
                        await asyncio.sleep(delay)
                        retry_delay = min(retry_delay * 2, self.reconnect_max_delay_s)
                else:
                    # Connected - wait before checking again
                    await asyncio.sleep(1.0)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.machine_id}] Connection manager error: {e}")
                await asyncio.sleep(1.0)
    
    async def _monitor_path(self, path: int) -> None:
        """Monitor a single path for tool changes"""
        state = self.path_states[path]
        poll_interval_s = self.poll_interval_ms / 1000.0
        
        logger.info(f"[{self.machine_id}] Starting path {path} monitor (poll interval: {self.poll_interval_ms}ms)")
        
        while self._running:
            try:
                # Wait for connection
                if not self.fanuc_client.is_connected:
                    await asyncio.sleep(0.5)
                    continue
                
                # Read tool
                tool_data = await self.fanuc_client.read_tool(path)
                
                if tool_data is None:
                    # Read failed
                    await self._handle_read_error(state, "Failed to read tool")
                    await asyncio.sleep(poll_interval_s)
                    continue
                
                # Read successful - clear error state
                if state.status == "error":
                    state.status = "ok"
                    state.error_message = None
                    logger.info(f"[{self.machine_id}] Path {path} recovered from error")
                
                # Check for tool change using debouncing
                await self._process_tool_read(state, tool_data.tool_number)
                
                # Wait for next poll
                await asyncio.sleep(poll_interval_s)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.machine_id}] Path {path} monitor error: {e}")
                await asyncio.sleep(poll_interval_s)
        
        logger.info(f"[{self.machine_id}] Path {path} monitor stopped")
    
    async def _process_tool_read(self, state: PathState, tool_number: int) -> None:
        """
        Process a tool read with debouncing logic
        
        Edge-triggered detection:
        - Requires N consecutive reads of the same new tool before confirming change
        - Only publishes when stable tool changes to a different stable tool
        """
        if tool_number == state.stable_tool:
            # Tool matches current stable tool - reset consecutive counter
            state.consecutive_reads = 0
            state.current_tool = tool_number
            
        elif tool_number == state.current_tool:
            # Same as last read - increment consecutive counter
            state.consecutive_reads += 1
            
            if state.consecutive_reads >= self.debounce_consecutive_reads:
                # Tool is now stable - this is a confirmed change
                old_tool = state.stable_tool
                state.stable_tool = tool_number
                
                # Publish tool change event (skip if this is first detection)
                if old_tool is not None:
                    logger.info(
                        f"[{self.machine_id}] Path {state.path} tool change: "
                        f"{old_tool} -> {state.stable_tool}"
                    )
                    
                    await self.mqtt_publisher.publish_tool_change(
                        machine_id=self.machine_id,
                        path=state.path,
                        ip=self.ip,
                        tool_previous=old_tool,
                        tool_current=state.stable_tool
                    )
                else:
                    logger.info(
                        f"[{self.machine_id}] Path {state.path} initial tool detected: "
                        f"{state.stable_tool}"
                    )
                
                # Reset counter
                state.consecutive_reads = 0
        else:
            # Different tool than last read - start new sequence
            state.current_tool = tool_number
            state.consecutive_reads = 1
            
            logger.debug(
                f"[{self.machine_id}] Path {state.path} tool read: {tool_number} "
                f"(consecutive: {state.consecutive_reads}/{self.debounce_consecutive_reads})"
            )
    
    async def _handle_read_error(self, state: PathState, error_message: str) -> None:
        """Handle read error for a path"""
        if state.status == "ok":
            # First error - mark as error and publish
            state.status = "error"
            state.error_message = error_message
            state.last_error_publish_time = time.time()
            
            logger.error(f"[{self.machine_id}] Path {state.path} error: {error_message}")
            
            await self.mqtt_publisher.publish_error(
                machine_id=self.machine_id,
                path=state.path,
                ip=self.ip,
                error_message=error_message
            )
        else:
            # Already in error state - only republish every 60 seconds
            current_time = time.time()
            if current_time - state.last_error_publish_time >= 60.0:
                state.last_error_publish_time = current_time
                await self.mqtt_publisher.publish_error(
                    machine_id=self.machine_id,
                    path=state.path,
                    ip=self.ip,
                    error_message=error_message
                )
    
    async def _heartbeat_loop(self) -> None:
        """Publish periodic heartbeat messages"""
        while self._running:
            try:
                # Build path status
                path_status = {}
                path_errors = {}
                
                for path, state in self.path_states.items():
                    path_status[path] = state.status
                    if state.error_message:
                        path_errors[path] = state.error_message
                
                # Publish heartbeat
                await self.mqtt_publisher.publish_heartbeat(
                    machine_id=self.machine_id,
                    ip=self.ip,
                    connected=self.fanuc_client.is_connected,
                    path_status=path_status,
                    path_errors=path_errors
                )
                
                # Wait for next heartbeat
                await asyncio.sleep(self.heartbeat_interval_s)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.machine_id}] Heartbeat error: {e}")
                await asyncio.sleep(self.heartbeat_interval_s)
