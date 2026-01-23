"""Production FANUC client using FOCAS library via ctypes"""

import asyncio
import ctypes
import time
import logging
from typing import Optional
from pathlib import Path

from .fanuc_client import FanucClient, ToolData, ConnectionState, FanucError

logger = logging.getLogger(__name__)


# FOCAS structures (from legacy code)
class ODBST_struct(ctypes.Structure):
    """CNC status information structure"""
    _fields_ = [
        ("hdck", ctypes.c_short),
        ("tmmode", ctypes.c_short),
        ("aut", ctypes.c_short),      # 1 auto, 5 jog
        ("run", ctypes.c_short),      # 0 reset, 3 run, 2 stop
        ("motion", ctypes.c_short),
        ("mstb", ctypes.c_short),
        ("emergency", ctypes.c_short),
        ("alarm", ctypes.c_short),
        ("edit", ctypes.c_short)
    ]


class ODBM_struct(ctypes.Structure):
    """Macro variable structure"""
    _fields_ = [
        ("datano", ctypes.c_ushort),
        ("mcr_val", ctypes.c_int32),
        ("dec_val", ctypes.c_long)
    ]


class FanucClientImpl(FanucClient):
    """Production FANUC client using FOCAS library"""
    
    def __init__(
        self,
        machine_id: str,
        ip: str,
        port: int,
        library_path: str,
        macro_address: int,
        timeout: int = 10
    ):
        self.machine_id = machine_id
        self.ip = ip
        self.port = port
        self.library_path = library_path
        self.macro_address = macro_address
        self.timeout = timeout
        
        self.libh = ctypes.c_ushort(0)
        self._connected = False
        self._state = ConnectionState.DISCONNECTED
        self._lock = asyncio.Lock()
        
        # Load FOCAS library
        self.focas = None
        self._load_library()
    
    def _load_library(self) -> None:
        """Load FOCAS library"""
        try:
            self.focas = ctypes.cdll.LoadLibrary(self.library_path)
            self._setup_function_signatures()
            
            # Startup FOCAS process
            ret = self.focas.cnc_startupprocess(0, b"focas.log")
            if ret != 0:
                logger.error(f"[{self.machine_id}] Failed to startup FOCAS process: {ret}")
            else:
                logger.info(f"[{self.machine_id}] FOCAS library loaded from {self.library_path}")
                
        except Exception as e:
            logger.error(f"[{self.machine_id}] Failed to load FOCAS library: {e}")
            self.focas = None
    
    def _setup_function_signatures(self) -> None:
        """Setup FOCAS function signatures"""
        self.focas.cnc_startupprocess.restype = ctypes.c_short
        self.focas.cnc_exitprocess.restype = ctypes.c_short
        self.focas.cnc_allclibhndl3.restype = ctypes.c_short
        self.focas.cnc_freelibhndl.restype = ctypes.c_short
        self.focas.cnc_statinfo.restype = ctypes.c_short
        self.focas.cnc_setpath.restype = ctypes.c_short
        self.focas.cnc_rdmacro.restype = ctypes.c_short
    
    async def connect(self) -> bool:
        """Establish connection to FANUC CNC"""
        if not self.focas:
            logger.error(f"[{self.machine_id}] FOCAS library not available")
            return False
        
        async with self._lock:
            self._state = ConnectionState.CONNECTING
            
            try:
                # Run blocking FOCAS call in executor
                loop = asyncio.get_event_loop()
                ret = await loop.run_in_executor(
                    None,
                    self._connect_sync
                )
                
                if ret == 0:
                    self._connected = True
                    self._state = ConnectionState.CONNECTED
                    logger.info(f"[{self.machine_id}] Connected to {self.ip}:{self.port}")
                    return True
                else:
                    self._state = ConnectionState.ERROR
                    logger.error(f"[{self.machine_id}] Connection failed: FOCAS error {ret}")
                    return False
                    
            except Exception as e:
                self._state = ConnectionState.ERROR
                logger.error(f"[{self.machine_id}] Connection exception: {e}")
                return False
    
    def _connect_sync(self) -> int:
        """Synchronous connection (called in executor)"""
        ret = self.focas.cnc_allclibhndl3(
            self.ip.encode(),
            self.port,
            self.timeout,
            ctypes.byref(self.libh)
        )
        return ret
    
    async def disconnect(self) -> None:
        """Disconnect from FANUC CNC"""
        if not self._connected:
            return
        
        async with self._lock:
            try:
                if self.focas and self.libh:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        self.focas.cnc_freelibhndl,
                        self.libh
                    )
                    logger.info(f"[{self.machine_id}] Disconnected from {self.ip}")
            except Exception as e:
                logger.error(f"[{self.machine_id}] Disconnect exception: {e}")
            finally:
                self._connected = False
                self._state = ConnectionState.DISCONNECTED
                self.libh = ctypes.c_ushort(0)
    
    async def read_tool(self, path: int) -> Optional[ToolData]:
        """Read current tool number for specified path"""
        if not self._connected or not self.focas:
            return None
        
        async with self._lock:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._read_tool_sync,
                    path
                )
                return result
            except Exception as e:
                logger.error(f"[{self.machine_id}] Read tool exception for path {path}: {e}")
                return None
    
    def _read_tool_sync(self, path: int) -> Optional[ToolData]:
        """Synchronous tool read (called in executor)"""
        # Set path
        ret = self.focas.cnc_setpath(self.libh, path)
        if ret != 0:
            logger.error(f"[{self.machine_id}] Failed to set path {path}: FOCAS error {ret}")
            return None
        
        # Read macro variable
        odbm = ODBM_struct()
        ret = self.focas.cnc_rdmacro(
            self.libh,
            self.macro_address,
            10,  # macro_length always 10
            ctypes.byref(odbm)
        )
        
        if ret != 0:
            logger.error(f"[{self.machine_id}] Failed to read macro {self.macro_address} for path {path}: FOCAS error {ret}")
            return None
        
        # Convert macro to tool number using legacy algorithm
        tool_float = self._macro_to_float(odbm)
        tool_number = int(round(tool_float))
        
        logger.debug(f"[{self.machine_id}] Read path {path} tool: {tool_number}")
        
        return ToolData(
            tool_number=tool_number,
            path=path,
            timestamp_ms=int(time.time() * 1000)
        )
    
    def _macro_to_float(self, macro: ODBM_struct) -> float:
        """
        Convert macro structure to float value
        (From legacy focas.py Macro2Float implementation)
        """
        if macro.dec_val:
            return (macro.mcr_val * 1.0) / (10.0 ** macro.dec_val)
        else:
            return float(macro.mcr_val)
    
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
