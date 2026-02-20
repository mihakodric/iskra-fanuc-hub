"""Production FANUC client using legacy FanucConnection (no direct FOCAS access)"""

import asyncio
import time
import logging
from typing import Optional

from .fanuc_client import FanucClient, ToolData, ConnectionState, FanucError

# Inject legacy/ into sys.path for direct import
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'legacy')))
from fanuc_communication import FanucConnection

logger = logging.getLogger(__name__)


class FanucClientImpl(FanucClient):
    """
    Production FANUC client that wraps the legacy FanucConnection exactly as
    basic_tool_reader.py does. All FOCAS access goes through FanucConnection
    so the retry / path-setting logic stays in one place.
    """

    def __init__(
        self,
        machine_id: str,
        ip: str,
        port: int,
        timeout: int = 10,
        # macro_address / macro_length kept for API compatibility but are
        # applied to FanucConnection which reads them from Config internally.
        macro_address: int = None,
        macro_length: int = None,
        library_path: str = None,
    ):
        self.machine_id = machine_id
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._conn = FanucConnection(ip_address=ip, port=port, timeout=timeout)
        self._connected = False
        self._state = ConnectionState.DISCONNECTED

    # ------------------------------------------------------------------
    # Connection management – mirrors basic_tool_reader.py connection block
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        async with self._lock:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._conn.connect
            )
            self._connected = result
            self._state = (
                ConnectionState.CONNECTED if result else ConnectionState.ERROR
            )
            return result

    async def disconnect(self) -> None:
        async with self._lock:
            await asyncio.get_event_loop().run_in_executor(
                None, self._conn.disconnect
            )
            self._connected = False
            self._state = ConnectionState.DISCONNECTED

    # ------------------------------------------------------------------
    # Tool reading – identical pattern to basic_tool_reader.read_tool_info()
    # ------------------------------------------------------------------

    async def read_tool(self, path: int) -> Optional[ToolData]:
        """
        Read tool info for a single path, delegating to FanucConnection.read_tool_info()
        exactly as basic_tool_reader.py does:

            path1_info = connection.read_tool_info(1)
            path2_info = connection.read_tool_info(2)
        """
        async with self._lock:
            def _read():
                info = self._conn.read_tool_info(path)
                if not info:
                    logger.warning(
                        f"[{self.machine_id}] No data returned for path {path}"
                    )
                    return None
                tool_number = int(round(info["tool_number"]))
                logger.debug(
                    f"[{self.machine_id}] Path {path} → T{tool_number} "
                    f"(prog={info.get('program_number', 'N/A')} "
                    f"macro={info.get('macro_value', 'N/A')})"
                )
                return ToolData(
                    tool_number=tool_number,
                    path=path,
                    timestamp_ms=int(time.time() * 1000),
                )

            return await asyncio.get_event_loop().run_in_executor(None, _read)

    async def read_tools(self) -> dict:
        """Read both paths – same order as basic_tool_reader.py."""
        results = {}
        for path in (1, 2):
            results[path] = await self.read_tool(path)
        return results

    # ------------------------------------------------------------------
    # Properties required by the abstract base class
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def connection_state(self) -> ConnectionState:
        return self._state
