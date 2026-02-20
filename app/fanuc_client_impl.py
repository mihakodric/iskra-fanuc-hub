"""Production FANUC client using legacy FanucConnection.

IMPORTANT – thread affinity:
The FOCAS library (libfwlib32.so) ties each handle to the OS thread that
called cnc_allclibhndl3.  All subsequent FOCAS calls (setpath, rdmacro …)
must execute on that SAME thread, otherwise the library returns EW_REJECT (-8).

The legacy basic_tool_reader.py works because it runs everything on the main
thread with no concurrency.  We replicate that by using a single-worker
ThreadPoolExecutor: every connect / disconnect / read goes to the same thread.
"""

import asyncio
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .fanuc_client import FanucClient, ToolData, ConnectionState, FanucError

# Inject legacy/ into sys.path so we can import FanucConnection directly
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'legacy')))
from fanuc_communication import FanucConnection

logger = logging.getLogger(__name__)


class FanucClientImpl(FanucClient):
    """
    Production FANUC client that wraps the legacy FanucConnection and ensures
    all FOCAS calls run on a single dedicated thread (thread-affinity requirement
    of the FOCAS C library).
    """

    def __init__(
        self,
        machine_id: str,
        ip: str,
        port: int,
        timeout: int = 10,
        # Kept for API compatibility with main.py but not needed —
        # FanucConnection reads macro_address from legacy Config internally.
        macro_address: int = None,
        macro_length: int = None,
        library_path: str = None,
    ):
        self.machine_id = machine_id
        self.ip = ip
        self.port = port
        self.timeout = timeout

        # Single-worker executor: ALL FOCAS calls run on this one thread.
        # This mirrors the synchronous main-thread execution of basic_tool_reader.py.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"focas-{machine_id}")

        self._conn = FanucConnection(ip_address=ip, port=port, timeout=timeout)
        self._connected = False
        self._state = ConnectionState.DISCONNECTED

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run(self, fn):
        """Submit fn to the dedicated FOCAS thread and return an awaitable."""
        return asyncio.get_event_loop().run_in_executor(self._executor, fn)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        def _connect():
            return self._conn.connect()

        result = await self._run(_connect)
        self._connected = result
        self._state = ConnectionState.CONNECTED if result else ConnectionState.ERROR
        return result

    async def disconnect(self) -> None:
        def _disconnect():
            self._conn.disconnect()

        await self._run(_disconnect)
        self._connected = False
        self._state = ConnectionState.DISCONNECTED

    # ------------------------------------------------------------------
    # Tool reading — identical call pattern to basic_tool_reader.py:
    #   path1_info = connection.read_tool_info(1)
    #   path2_info = connection.read_tool_info(2)
    # ------------------------------------------------------------------

    async def read_tool(self, path: int) -> Optional[ToolData]:
        """Read tool info for one path on the dedicated FOCAS thread."""
        def _read():
            info = self._conn.read_tool_info(path)
            if not info:
                return None
            tool_number = int(round(info['tool_number']))
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

        return await self._run(_read)

    async def read_tools(self) -> dict:
        """Read both paths sequentially — same order as basic_tool_reader.py."""
        results = {}
        for path in (1, 2):
            results[path] = await self.read_tool(path)
        return results

    # ------------------------------------------------------------------
    # Abstract base class properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def connection_state(self) -> ConnectionState:
        return self._state

    def __del__(self):
        self._executor.shutdown(wait=False)
