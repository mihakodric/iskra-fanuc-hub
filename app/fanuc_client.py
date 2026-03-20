"""FANUC client interface and data structures"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict
from enum import Enum


class ConnectionState(Enum):
    """Connection state"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ToolReadResult:
    """Result of a tool read operation including error codes"""
    tool: Optional[int]        # Tool number if successful, None on error
    error_code: Optional[int]  # FOCAS error code (0 = success, non-zero = error)
    path: int                  # CNC path number
    timestamp_ms: int          # Unix timestamp in milliseconds


@dataclass
class ToolData:
    """Tool information from CNC (legacy compatibility)"""
    tool_number: int
    path: int
    timestamp_ms: int


@dataclass
class FanucError:
    """FOCAS error information"""
    code: int
    message: str
    path: Optional[int] = None


class FanucClient(ABC):
    """Abstract interface for FANUC CNC communication"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to FANUC CNC
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from FANUC CNC"""
        pass
    
    @abstractmethod
    async def read_tool(self, path: int) -> ToolReadResult:
        """
        Read current tool number for specified path
        
        Args:
            path: CNC path number (1 or 2)
            
        Returns:
            ToolReadResult with tool number and error code
            - tool: int if successful, None on error
            - error_code: 0 on success, FOCAS error code on failure
        """
        pass
    
    @abstractmethod
    async def read_tools(self) -> Dict[int, ToolReadResult]:
        """
        Read tool numbers for all configured paths
        
        Returns:
            Dictionary mapping path number to ToolReadResult
        """
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to CNC"""
        pass
    
    @property
    @abstractmethod
    def connection_state(self) -> ConnectionState:
        """Get current connection state"""
        pass
