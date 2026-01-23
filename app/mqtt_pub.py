"""MQTT publisher wrapper with reconnection logic"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from asyncio_mqtt import Client, MqttError
import time

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """MQTT publisher with automatic reconnection"""
    
    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False
    ):
        self.host = host
        self.port = port
        self.username = username if username else None
        self.password = password if password else None
        self.tls = tls
        
        self._client: Optional[Client] = None
        self._connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._running = False
        
    async def start(self) -> None:
        """Start MQTT client with reconnection loop"""
        self._running = True
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info(f"MQTT publisher started, connecting to {self.host}:{self.port}")
    
    async def stop(self) -> None:
        """Stop MQTT client"""
        self._running = False
        
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except:
                pass
            self._client = None
        
        self._connected = False
        logger.info("MQTT publisher stopped")
    
    async def _reconnect_loop(self) -> None:
        """Reconnection loop with exponential backoff"""
        retry_delay = 1.0
        max_retry_delay = 60.0
        
        while self._running:
            try:
                # Create client
                logger.info(f"Connecting to MQTT broker {self.host}:{self.port}...")
                
                self._client = Client(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    tls_context=None  # TODO: Add TLS support if needed
                )
                
                await self._client.__aenter__()
                self._connected = True
                retry_delay = 1.0  # Reset delay on successful connection
                logger.info(f"Connected to MQTT broker {self.host}:{self.port}")
                
                # Keep connection alive
                while self._running and self._connected:
                    await asyncio.sleep(1)
                
            except MqttError as e:
                self._connected = False
                logger.error(f"MQTT connection error: {e}")
                
                if self._running:
                    logger.info(f"Retrying connection in {retry_delay:.1f}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)
                    
            except Exception as e:
                self._connected = False
                logger.error(f"Unexpected MQTT error: {e}")
                
                if self._running:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)
    
    async def publish_tool_change(
        self,
        machine_id: str,
        path: int,
        ip: str,
        tool_previous: int,
        tool_current: int
    ) -> bool:
        """
        Publish tool change event
        
        Args:
            machine_id: Machine identifier
            path: CNC path number
            ip: Machine IP address
            tool_previous: Previous tool number
            tool_current: Current tool number
            
        Returns:
            True if published successfully
        """
        topic = f"fanuc/{machine_id}/event/tool_change/path{path}"
        
        payload = {
            "machine_id": machine_id,
            "path": path,
            "ip": ip,
            "event": "tool_change",
            "tool_previous": tool_previous,
            "tool_current": tool_current,
            "ts_unix_ms": int(time.time() * 1000),
            "source": "rpi4-monitor"
        }
        
        return await self._publish(topic, payload, qos=1)
    
    async def publish_error(
        self,
        machine_id: str,
        path: int,
        ip: str,
        error_message: str
    ) -> bool:
        """
        Publish error event
        
        Args:
            machine_id: Machine identifier
            path: CNC path number
            ip: Machine IP address
            error_message: Error description
            
        Returns:
            True if published successfully
        """
        topic = f"fanuc/{machine_id}/event/error"
        
        payload = {
            "machine_id": machine_id,
            "path": path,
            "ip": ip,
            "error": error_message,
            "ts_unix_ms": int(time.time() * 1000),
            "source": "rpi4-monitor"
        }
        
        return await self._publish(topic, payload, qos=1)
    
    async def publish_heartbeat(
        self,
        machine_id: str,
        ip: str,
        connected: bool,
        path_status: Dict[int, str],
        path_errors: Dict[int, str]
    ) -> bool:
        """
        Publish heartbeat/state message
        
        Args:
            machine_id: Machine identifier
            ip: Machine IP address
            connected: Whether connected to CNC
            path_status: Dict mapping path number to status ("ok" or "error")
            path_errors: Dict mapping path number to error message (if any)
            
        Returns:
            True if published successfully
        """
        topic = f"fanuc/{machine_id}/state"
        
        payload = {
            "machine_id": machine_id,
            "ip": ip,
            "connected": connected,
            "ts_unix_ms": int(time.time() * 1000),
            "source": "rpi4-monitor"
        }
        
        # Add path status
        for path, status in path_status.items():
            payload[f"path{path}_status"] = status
            if status == "error" and path in path_errors:
                payload[f"path{path}_error"] = path_errors[path]
        
        return await self._publish(topic, payload, qos=0)
    
    async def _publish(self, topic: str, payload: Dict[str, Any], qos: int = 0) -> bool:
        """
        Publish message to MQTT broker
        
        Args:
            topic: MQTT topic
            payload: Message payload (will be JSON-encoded)
            qos: Quality of service level (0, 1, or 2)
            
        Returns:
            True if published successfully
        """
        if not self._connected or not self._client:
            logger.warning(f"Cannot publish to {topic} - not connected to MQTT broker")
            return False
        
        try:
            message = json.dumps(payload)
            await self._client.publish(topic, message.encode(), qos=qos)
            logger.debug(f"Published to {topic}: {message}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")
            self._connected = False  # Trigger reconnection
            return False
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MQTT broker"""
        return self._connected
