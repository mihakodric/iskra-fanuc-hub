"""Production FANUC client using legacy FanucConnection (no direct FOCAS access)"""

import asyncio
import ctypes
from ctypes import c_short, c_ushort
import time
import logging
from typing import Optional
from pathlib import Path


from .fanuc_client import FanucClient, ToolData, ConnectionState, FanucError

# Inject legacy/ into sys.path for direct import
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'legacy')))
from fanuc_communication import FanucConnection
from config import Config as LegacyConfig

logger = logging.getLogger(__name__)




class FanucClientImpl(FanucClient):

    async def read_tools(self) -> dict:
        # Read both paths in sequence, legacy style
        results = {}
        for path in (1, 2):
            results[path] = await self.read_tool(path)
        return results

    async def connect(self) -> bool:
        async with self._lock:
            result = await asyncio.get_event_loop().run_in_executor(None, self._conn.connect)
            self._connected = result
            self._state = ConnectionState.CONNECTED if result else ConnectionState.ERROR
            return result

    async def disconnect(self) -> None:
        async with self._lock:
            await asyncio.get_event_loop().run_in_executor(None, self._conn.disconnect)
            self._connected = False
            self._state = ConnectionState.DISCONNECTED

    def __init__(
        self,
        machine_id: str,
        ip: str,
        port: int,
        library_path: str,
        macro_address: int,
        macro_length: int = 10,
        timeout: int = 10
    ):
        self.machine_id = machine_id
        self.ip = ip
        self.port = port
        self.library_path = library_path
        self.macro_address = macro_address
        self.macro_length = macro_length
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._conn = FanucConnection(ip_address=ip, port=port, timeout=timeout)
        # Patch the legacy FanucConnection to use correct macro address/length
        if hasattr(self._conn, 'macro_address'):
            self._conn.macro_address = macro_address
        if hasattr(self._conn, 'macro_length'):
            self._conn.macro_length = macro_length
        self._connected = False
        self._state = ConnectionState.DISCONNECTED

    async def read_tool(self, path: int):
        """Return tool info for a single path using legacy FanucConnection."""
        async with self._lock:
            def _read():
                info = self._conn.read_tool_info(path)
                if not info:
                    return None
                return ToolData(
                    tool_number=int(round(info['tool_number'])),
                    path=path,
                    timestamp_ms=int(time.time() * 1000)
                )
            return await asyncio.get_event_loop().run_in_executor(None, _read)

    def _read_tool_sync(self, path: int) -> Optional[ToolData]:
        # This matches the legacy basic_tool_reader/fanuc_communication.py logic exactly
        # Set path before reading (required for multi-path machines, harmless for single-path)
        if self._has_setpath:
            ret = self.focas.cnc_setpath(self.libh, path)
            if ret != 0:
                logger.error(f"[{self.machine_id}] Failed to set path {path}: FOCAS error {ret}")
                return None

        # Use the same structure allocation as legacy
        odbm1 = ODBM_struct()
        odbexeprg1 = type('ODBEXEPRG_struct', (ctypes.Structure,), {
            '_fields_': [
                ("name", ctypes.c_char * 36),
                ("o_num", ctypes.c_uint32)
            ]
        })()

        # Read executing program (legacy always does this after setpath)
        ret = self.focas.cnc_exeprgname(self.libh, ctypes.byref(odbexeprg1))
        if ret != 0:
            logger.error(f"[{self.machine_id}] Failed to read program name for path {path}: FOCAS error {ret}")
            # Not fatal, continue to macro read

        # Read macro variable
        ret = self.focas.cnc_rdmacro(
            self.libh,
            self.macro_address,
            10,  # macro_length always 10
            ctypes.byref(odbm1)
        )
        if ret != 0:
            logger.error(f"[{self.machine_id}] Failed to read macro {self.macro_address} for path {path}: FOCAS error {ret}")
            return None

        # Convert macro to tool number using legacy algorithm
        tool_float = self._macro_to_float(odbm1)
        tool_number = int(round(tool_float))
        program_number = getattr(odbexeprg1, "o_num", None)

        logger.debug(f"[{self.machine_id}] Read path {path} tool: {tool_number} program: {program_number}")

        return ToolData(
            tool_number=tool_number,
            path=path,
            timestamp_ms=int(time.time() * 1000)
        )
    
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to CNC"""
        return self._connected
    
    @property
    def connection_state(self) -> ConnectionState:
        """Get current connection state"""
        return self._state
    
    def __del__(self):
        """Cleanup on deletion"""
        if self.focas and self._connected:
            try:
                self.focas.cnc_freelibhndl(self.libh)
            except:
                pass
