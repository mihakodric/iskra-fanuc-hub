"""FANUC client interface and data structures"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class ConnectionState(Enum):
    """Connection state"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ToolData:
    """Tool information from CNC"""
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
    async def read_tool(self, path: int) -> Optional[ToolData]:
        """
        Read current tool number for specified path
        
        Args:
            path: CNC path number (1 or 2)
            
        Returns:
            ToolData if successful, None on error
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
