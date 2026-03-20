"""Machine monitor with per-path tool change detection"""

import asyncio
import logging
import random
import time
from typing import Dict, Optional, List
from dataclasses import dataclass

from .fanuc_client import FanucClient, ToolReadResult
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
        reconnect_max_delay_s: float = 30.0,
        max_consecutive_all_path_failures: int = 100,
        max_uptime_hours: int = 24
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
        
        # Circuit breaker and uptime tracking
        self.consecutive_all_paths_failures = 0
        self.last_successful_read_time: Optional[float] = None
        self.connection_started_at: Optional[float] = None
        self.last_forced_reconnect_reason: Optional[str] = None
        
        # Configuration from monitoring config
        self.max_consecutive_all_path_failures = max_consecutive_all_path_failures
        self.max_uptime_hours = max_uptime_hours
        
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

        # Start single polling loop for all paths (legacy-compatible)
        self._tasks.append(asyncio.create_task(self._poll_all_paths_loop()))

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
                        self.connection_started_at = time.time()  # Track connection start time
                        self.consecutive_all_paths_failures = 0  # Reset failure counter
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
    
    async def _force_reconnect(self, reason: str) -> None:
        """
        Force a disconnect/reconnect cycle due to persistent failures or periodic health check
        
        Args:
            reason: Why the reconnection is being forced (e.g., "persistent_read_failure", "periodic_reconnect")
        """
        # Calculate failure duration if applicable
        duration_info = ""
        if self.last_successful_read_time:
            duration_s = time.time() - self.last_successful_read_time
            duration_info = f" (no successful reads for {duration_s:.1f}s)"
        
        # Calculate uptime if applicable
        uptime_info = ""
        if self.connection_started_at:
            uptime_h = (time.time() - self.connection_started_at) / 3600.0
            uptime_info = f" (uptime: {uptime_h:.1f}h)"
        
        logger.warning(
            f"[{self.machine_id}] Forcing reconnection - reason: {reason}, "
            f"consecutive_failures: {self.consecutive_all_paths_failures}"
            f"{duration_info}{uptime_info}"
        )
        
        # Publish error event to MQTT
        error_type = reason
        error_message = f"Forced reconnection: {reason}"
        if self.consecutive_all_paths_failures > 0:
            error_message += f" ({self.consecutive_all_paths_failures} consecutive failures)"
        
        await self.mqtt_publisher.publish_error(
            machine_id=self.machine_id,
            path=0,  # Machine-level error (not path-specific)
            ip=self.ip,
            error_message=error_message
        )
        
        # Disconnect - connection manager will handle reconnection
        await self.fanuc_client.disconnect()
        
        # Reset all tracking state
        self.consecutive_all_paths_failures = 0
        self.connection_started_at = None
        self.last_forced_reconnect_reason = reason
        
        # Reset all path states
        for state in self.path_states.values():
            state.status = "ok"
            state.error_message = None
            state.consecutive_reads = 0
        
        logger.info(f"[{self.machine_id}] Disconnected - connection manager will reconnect")
    

    async def _poll_all_paths_loop(self) -> None:
        """Poll all monitored paths in a single loop with circuit breaker and uptime limit"""
        poll_interval_s = self.poll_interval_ms / 1000.0
        logger.info(f"[{self.machine_id}] Starting unified path monitor (poll interval: {self.poll_interval_ms}ms)")
        
        # For progressive logging of circuit breaker threshold
        logged_thresholds = set()  # Track which % thresholds we've logged
        
        while self._running:
            try:
                # Wait for connection
                if not self.fanuc_client.is_connected:
                    await asyncio.sleep(0.5)
                    continue

                # Check for 24h uptime limit (periodic health reconnect)
                if self.connection_started_at:
                    uptime_hours = (time.time() - self.connection_started_at) / 3600.0
                    
                    # Log approaching deadline (at 23 hours)
                    if uptime_hours >= self.max_uptime_hours - 1.0 and uptime_hours < self.max_uptime_hours:
                        if 'uptime_warning' not in logged_thresholds:
                            logger.info(
                                f"[{self.machine_id}] Approaching periodic reconnect: "
                                f"{uptime_hours:.1f}h / {self.max_uptime_hours}h uptime"
                            )
                            logged_thresholds.add('uptime_warning')
                    
                    # Trigger periodic reconnect
                    if uptime_hours >= self.max_uptime_hours:
                        await self._force_reconnect("periodic_reconnect")
                        logged_thresholds.clear()  # Reset threshold logging
                        continue

                # Read all tools in one go (serial FOCAS access)
                tool_results = await self.fanuc_client.read_tools()
                
                # Track how many paths succeeded/failed
                successful_paths = 0
                failed_paths = 0
                
                for path in self.monitored_paths:
                    state = self.path_states[path]
                    tool_result = tool_results.get(path)
                    
                    if tool_result is None or tool_result.tool is None:
                        # Read failed
                        failed_paths += 1
                        error_code = tool_result.error_code if tool_result else -1
                        error_msg = f"Failed to read tool (FOCAS error: {error_code})"
                        await self._handle_read_error(state, error_msg, error_code)
                        continue

                    # Read successful
                    successful_paths += 1
                    
                    # Clear error state if path recovered
                    if state.status == "error":
                        state.status = "ok"
                        state.error_message = None
                        logger.info(f"[{self.machine_id}] Path {path} recovered from error")

                    # Check for tool change using debouncing
                    await self._process_tool_read(state, tool_result.tool)
                
                # Circuit breaker: Check if ALL paths failed
                if failed_paths > 0 and successful_paths == 0:
                    # All monitored paths failed - increment failure counter
                    self.consecutive_all_paths_failures += 1
                    
                    # Progressive logging at threshold percentages
                    pct = (self.consecutive_all_paths_failures / self.max_consecutive_all_path_failures) * 100
                    if pct >= 75 and '75%' not in logged_thresholds:
                        logger.info(
                            f"[{self.machine_id}] Circuit breaker at 75%: "
                            f"{self.consecutive_all_paths_failures}/{self.max_consecutive_all_path_failures} failures"
                        )
                        logged_thresholds.add('75%')
                    elif pct >= 50 and '50%' not in logged_thresholds:
                        logger.info(
                            f"[{self.machine_id}] Circuit breaker at 50%: "
                            f"{self.consecutive_all_paths_failures}/{self.max_consecutive_all_path_failures} failures"
                        )
                        logged_thresholds.add('50%')
                    elif pct >= 25 and '25%' not in logged_thresholds:
                        logger.info(
                            f"[{self.machine_id}] Circuit breaker at 25%: "
                            f"{self.consecutive_all_paths_failures}/{self.max_consecutive_all_path_failures} failures"
                        )
                        logged_thresholds.add('25%')
                    
                    # Trigger forced reconnection if threshold exceeded
                    if self.consecutive_all_paths_failures >= self.max_consecutive_all_path_failures:
                        await self._force_reconnect("persistent_read_failure")
                        logged_thresholds.clear()  # Reset threshold logging
                        continue
                        
                elif successful_paths > 0:
                    # At least one path succeeded - reset failure counter
                    if self.consecutive_all_paths_failures > 0:
                        logger.debug(
                            f"[{self.machine_id}] Circuit breaker reset: "
                            f"had {self.consecutive_all_paths_failures} consecutive failures, now cleared"
                        )
                    self.consecutive_all_paths_failures = 0
                    self.last_successful_read_time = time.time()
                    logged_thresholds.clear()  # Reset threshold logging on recovery

                # Wait for next poll
                await asyncio.sleep(poll_interval_s)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.machine_id}] Unified path monitor error: {e}")
                await asyncio.sleep(poll_interval_s)
        logger.info(f"[{self.machine_id}] Unified path monitor stopped")
    
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
    
    async def _handle_read_error(self, state: PathState, error_message: str, error_code: int = -1) -> None:
        """Handle read error for a path"""
        # Enhance error message with FOCAS error code
        full_error_message = error_message
        if error_code != -1:
            full_error_message = f"{error_message} (code: {error_code})"
        
        if state.status == "ok":
            # First failure for this path — downgrade to WARNING since some
            # CNC machines simply don't expose all paths (matches the legacy
            # basic_tool_reader "No data" fallback, not an alarm condition).
            state.status = "error"
            state.error_message = full_error_message
            state.last_error_publish_time = time.time()

            logger.warning(f"[{self.machine_id}] Path {state.path} unavailable: {full_error_message}")

            await self.mqtt_publisher.publish_error(
                machine_id=self.machine_id,
                path=state.path,
                ip=self.ip,
                error_message=full_error_message
            )
        else:
            # Already in error state - only republish every 60 seconds
            current_time = time.time()
            if current_time - state.last_error_publish_time >= 60.0:
                state.last_error_publish_time = current_time
                state.error_message = full_error_message  # Update stored message
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
                
                # Calculate uptime
                uptime_hours = None
                if self.connection_started_at:
                    uptime_hours = (time.time() - self.connection_started_at) / 3600.0
                
                # Publish heartbeat with circuit breaker state
                await self.mqtt_publisher.publish_heartbeat(
                    machine_id=self.machine_id,
                    ip=self.ip,
                    connected=self.fanuc_client.is_connected,
                    path_status=path_status,
                    path_errors=path_errors,
                    consecutive_failures=self.consecutive_all_paths_failures,
                    uptime_hours=uptime_hours,
                    last_successful_read_time=self.last_successful_read_time
                )
                
                # Wait for next heartbeat
                await asyncio.sleep(self.heartbeat_interval_s)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.machine_id}] Heartbeat error: {e}")
                await asyncio.sleep(self.heartbeat_interval_s)
