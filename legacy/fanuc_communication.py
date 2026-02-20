# FOCAS Communication Module
import threading
import time
import logging
from typing import Optional, Dict, Any, Callable
import ctypes
from pathlib import Path
from config import Config

logger = logging.getLogger(__name__)

class ODBST_struct(ctypes.Structure):
    _fields_ = [
        ("hdck", ctypes.c_short),
        ("tmmode", ctypes.c_short),
        ("aut", ctypes.c_short),  # 1 auto, 5 jog
        ("run", ctypes.c_short),  # 0 reset, 3 run, 2 stop
        ("motion", ctypes.c_short),
        ("mstb", ctypes.c_short),
        ("emergency", ctypes.c_short),
        ("alarm", ctypes.c_short),
        ("edit", ctypes.c_short)
    ]

class ODBM_struct(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_ushort),
        ("mcr_val", ctypes.c_int32),
        ("dec_val", ctypes.c_long)
    ]

class ODBEXEPRG_struct(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * 36),
        ("o_num", ctypes.c_uint32)
    ]

class FanucConnection:
    """Handles connection and communication with Fanuc CNC machine via FOCAS"""
    
    def __init__(self, ip_address: str, port: int = 8193, timeout: int = 10):
        self.ip_address = ip_address
        self.port = port
        self.timeout = timeout
        self.libh = ctypes.c_ushort(0)
        self.connected = False
        self.running = False
        self._lock = threading.Lock()
        
        # Data structures
        self.odbst = ODBST_struct()
        self.odbm1 = ODBM_struct()
        self.odbm2 = ODBM_struct()
        self.odbexeprg1 = ODBEXEPRG_struct()
        self.odbexeprg2 = ODBEXEPRG_struct()
        
        # Initialize FOCAS library if in production mode
        if Config.is_production():
            try:
                self.focas = ctypes.cdll.LoadLibrary("/usr/local/lib/libfwlib32.so")
                self._setup_focas_functions()
                ret = self.focas.cnc_startupprocess(0, b"focas.log")
                if ret != 0:
                    logger.error(f"Failed to startup FOCAS process: {ret}")
            except Exception as e:
                logger.error(f"Failed to load FOCAS library: {e}")
                self.focas = None
        else:
            self.focas = None
            logger.info("Running in development mode - FOCAS library not loaded")
    
    def _setup_focas_functions(self):
        """Setup FOCAS function signatures"""
        self.focas.cnc_startupprocess.restype = ctypes.c_short
        self.focas.cnc_exitprocess.restype = ctypes.c_short
        self.focas.cnc_allclibhndl3.restype = ctypes.c_short
        self.focas.cnc_freelibhndl.restype = ctypes.c_short
        self.focas.cnc_statinfo.restype = ctypes.c_short
        self.focas.cnc_setpath.restype = ctypes.c_short
        self.focas.cnc_exeprgname.restype = ctypes.c_short
        self.focas.cnc_rdmacro.restype = ctypes.c_short
    
    def connect(self) -> bool:
        """Establish connection to Fanuc CNC"""
        if not Config.is_production() or not self.focas:
            logger.info("Simulating Fanuc connection in development mode")
            self.connected = True
            return True
        
        with self._lock:
            try:
                ret = self.focas.cnc_allclibhndl3(
                    self.ip_address.encode(),
                    self.port,
                    self.timeout,
                    ctypes.byref(self.libh)
                )
                
                if ret == 0:
                    self.connected = True
                    logger.info(f"Successfully connected to Fanuc CNC at {self.ip_address}")
                    return True
                else:
                    logger.error(f"Failed to connect to Fanuc CNC: {ret}")
                    return False
                    
            except Exception as e:
                logger.error(f"Exception during Fanuc connection: {e}")
                return False
    
    def disconnect(self):
        """Disconnect from Fanuc CNC"""
        if not Config.is_production() or not self.focas:
            self.connected = False
            return
        
        with self._lock:
            if self.connected and self.libh:
                try:
                    ret = self.focas.cnc_freelibhndl(self.libh)
                    if ret == 0:
                        logger.info("Successfully disconnected from Fanuc CNC")
                    else:
                        logger.warning(f"Warning during disconnect: {ret}")
                except Exception as e:
                    logger.error(f"Exception during disconnect: {e}")
                finally:
                    self.connected = False
                    self.libh = ctypes.c_ushort(0)
    
    def read_status(self) -> Optional[Dict[str, Any]]:
        """Read CNC status information"""
        # In development mode, always return simulated data
        if Config.is_development():
            return {
                'mode': 1,  # AUTO
                'state': 3,  # RUN
                'emergency': 0,
                'alarm': 0,
                'motion': 1
            }
        
        if not self.connected:
            return None
        
        # Only attempt real FOCAS calls in production mode
        if not self.focas:
            logger.error("FOCAS library not available")
            return None
        
        try:
            ret = self.focas.cnc_statinfo(self.libh, ctypes.byref(self.odbst))
            if ret == 0:
                return {
                    'mode': self.odbst.aut,
                    'state': self.odbst.run,
                    'emergency': self.odbst.emergency,
                    'alarm': self.odbst.alarm,
                    'motion': self.odbst.motion
                }
            else:
                logger.error(f"Failed to read CNC status: {ret}")
                return None
                
        except Exception as e:
            logger.error(f"Exception reading CNC status: {e}")
            return None
    
    def read_tool_info(self, path: int = 1) -> Optional[Dict[str, Any]]:
        """Read tool information from specified path"""
        # In development mode, always return simulated data
        if Config.is_development():
            import random
            return {
                'tool_number': random.randint(1, 10),
                'program_number': random.randint(1000, 9999),
                'macro_value': random.uniform(0.1, 5.0)
            }
        
        if not self.connected:
            return None
        
        # Only attempt real FOCAS calls in production mode
        if not self.focas:
            logger.error("FOCAS library not available")
            return None
        
        try:
            # Set path
            ret = self.focas.cnc_setpath(self.libh, path)
            if ret != 0:
                logger.error(f"Failed to set path {path}: {ret}")
                return None
            
            # Read executing program
            odbexeprg = self.odbexeprg1 if path == 1 else self.odbexeprg2
            ret = self.focas.cnc_exeprgname(self.libh, ctypes.byref(odbexeprg))
            if ret != 0:
                logger.error(f"Failed to read program name for path {path}: {ret}")
                return None
            
            # Read macro variable
            odbm = self.odbm1 if path == 1 else self.odbm2
            ret = self.focas.cnc_rdmacro(
                self.libh, 
                Config.FANUC_CONFIG['macro_address'], 
                Config.FANUC_CONFIG['macro_length'], 
                ctypes.byref(odbm)
            )
            if ret != 0:
                logger.error(f"Failed to read macro for path {path}: {ret}")
                return None
            
            return {
                'tool_number': self._macro_to_float(odbm),
                'program_number': odbexeprg.o_num,
                'macro_value': self._macro_to_float(odbm)
            }
            
        except Exception as e:
            logger.error(f"Exception reading tool info for path {path}: {e}")
            return None
    
    def _macro_to_float(self, macro: ODBM_struct) -> float:
        """Convert macro structure to float value"""
        if macro.dec_val:
            return (macro.mcr_val * 1.0) / (10.0 ** macro.dec_val)
        else:
            return float(macro.mcr_val)

class FanucMonitor(threading.Thread):
    """Background thread to monitor Fanuc CNC machine"""
    
    def __init__(self, connection: FanucConnection, update_callback: Optional[Callable] = None):
        super().__init__(daemon=True)
        self.connection = connection
        self.update_callback = update_callback
        self.running = False
        self._stop_event = threading.Event()
        self.current_tool = None
        self.current_program = None
        self.machine_status = None
        self.tool_monitoring_active = False
        self.last_tool_change_time = 0
        
        # Get tool monitoring configuration
        self.monitored_tool = Config.TOOL_MONITORING_CONFIG['monitored_tool']
        self.record_only_monitored_tool = Config.TOOL_MONITORING_CONFIG['record_only_monitored_tool']
        self.tool_change_debounce = Config.TOOL_MONITORING_CONFIG['tool_change_debounce']
        
    def run(self):
        """Main monitoring loop"""
        self.running = True
        retry_count = 0
        max_retries = Config.FANUC_CONFIG['retry_attempts']
        
        logger.info("Starting Fanuc monitoring thread")
        
        while not self._stop_event.is_set():
            try:
                # Try to connect if not connected
                if not self.connection.connected:
                    if self.connection.connect():
                        retry_count = 0
                    else:
                        retry_count += 1
                        if retry_count >= max_retries:
                            logger.error(f"Failed to connect after {max_retries} attempts")
                            time.sleep(Config.FANUC_CONFIG['retry_delay'] * 5)
                            retry_count = 0
                        else:
                            time.sleep(Config.FANUC_CONFIG['retry_delay'])
                        continue
                
                # Read machine status
                status = self.connection.read_status()
                if status:
                    self.machine_status = status
                    
                    # Read tool information for both paths
                    tool_info_path1 = self.connection.read_tool_info(1)
                    tool_info_path2 = self.connection.read_tool_info(2)
                    
                    # Check for tool changes
                    self._check_tool_changes(tool_info_path1, tool_info_path2)
                    
                    # Call update callback if provided
                    if self.update_callback:
                        self.update_callback({
                            'status': status,
                            'path1_tool': tool_info_path1,
                            'path2_tool': tool_info_path2,
                            'timestamp': time.time()
                        })
                
                time.sleep(0.1)  # 100ms polling interval
                
            except Exception as e:
                logger.error(f"Error in Fanuc monitoring loop: {e}")
                time.sleep(1)
        
        logger.info("Fanuc monitoring thread stopped")
        self.connection.disconnect()
    
    def _check_tool_changes(self, path1_info, path2_info):
        """Check for tool changes and trigger events"""
        current_time = time.time()
        
        # Check path 1 for tool changes
        if path1_info:
            new_tool = path1_info.get('tool_number')
            if new_tool != self.current_tool:
                # Debounce tool changes to avoid rapid switching
                if current_time - self.last_tool_change_time > self.tool_change_debounce:
                    old_tool = self.current_tool
                    self.current_tool = new_tool
                    self.last_tool_change_time = current_time
                    
                    # Only log at INFO level if it involves the monitored tool
                    if (old_tool == self.monitored_tool or 
                        new_tool == self.monitored_tool or 
                        not self.record_only_monitored_tool):
                        logger.info(f"Tool change detected: {old_tool} -> {self.current_tool}")
                    else:
                        logger.debug(f"Tool change detected: {old_tool} -> {self.current_tool} (not monitored)")
                    
                    # Check if we should start/stop monitoring based on tool
                    if self.record_only_monitored_tool:
                        if self.current_tool == self.monitored_tool:
                            if not self.tool_monitoring_active:
                                self.tool_monitoring_active = True
                                logger.info(f"Started monitoring tool {self.monitored_tool}")
                                self._notify_tool_monitoring_change(True)
                        else:
                            if self.tool_monitoring_active:
                                self.tool_monitoring_active = False
                                logger.info(f"Stopped monitoring - tool {self.current_tool} is not monitored tool {self.monitored_tool}")
                                self._notify_tool_monitoring_change(False)
                    else:
                        # Monitor all tools
                        self.tool_monitoring_active = True
    
    def _notify_tool_monitoring_change(self, active: bool):
        """Notify about tool monitoring state changes"""
        if self.update_callback:
            self.update_callback({
                'type': 'tool_monitoring_change',
                'active': active,
                'tool': self.current_tool,
                'monitored_tool': self.monitored_tool,
                'timestamp': time.time()
            })
    
    def should_record_data(self) -> bool:
        """Check if data should be recorded based on current tool"""
        if not self.record_only_monitored_tool:
            return True  # Record for all tools
        
        should_record = self.tool_monitoring_active and (self.current_tool == self.monitored_tool)
        
        # Only log when there's a change in recording status or when specifically requested
        if hasattr(self, '_last_should_record') and self._last_should_record != should_record:
            logger.info(f"Recording status changed: {should_record} (monitoring_active: {self.tool_monitoring_active}, current_tool: {self.current_tool}, monitored_tool: {self.monitored_tool})")
        elif not hasattr(self, '_last_should_record'):
            logger.debug(f"Initial recording status: {should_record} (monitoring_active: {self.tool_monitoring_active}, current_tool: {self.current_tool}, monitored_tool: {self.monitored_tool})")
        
        self._last_should_record = should_record
        return should_record
    
    def set_monitored_tool(self, tool_number: int):
        """Update the monitored tool number"""
        old_tool = self.monitored_tool
        self.monitored_tool = tool_number
        logger.info(f"Monitored tool changed from {old_tool} to {tool_number}")
        
        # Re-evaluate monitoring state
        if self.record_only_monitored_tool:
            if self.current_tool == self.monitored_tool:
                if not self.tool_monitoring_active:
                    self.tool_monitoring_active = True
                    self._notify_tool_monitoring_change(True)
            else:
                if self.tool_monitoring_active:
                    self.tool_monitoring_active = False
                    self._notify_tool_monitoring_change(False)
    
    def set_debounce_time(self, debounce_time: float):
        """Update the debounce time for tool change detection"""
        old_debounce = self.tool_change_debounce
        self.tool_change_debounce = debounce_time
        logger.info(f"Debounce time changed from {old_debounce}s to {debounce_time}s")
    
    def stop(self):
        """Stop the monitoring thread"""
        self.running = False
        self._stop_event.set()
    
    def get_current_status(self) -> Dict[str, Any]:
        """Get current machine status"""
        return {
            'connected': self.connection.connected,
            'current_tool': self.current_tool,
            'current_program': self.current_program,
            'machine_status': self.machine_status,
            'running': self.running,
            'monitored_tool': self.monitored_tool,
            'tool_monitoring_active': self.tool_monitoring_active,
            'record_only_monitored_tool': self.record_only_monitored_tool,
            'should_record': self.should_record_data()
        }
