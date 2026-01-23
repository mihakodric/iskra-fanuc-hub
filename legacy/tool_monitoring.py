# Tool Detection and Monitoring Module
import threading
import time
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

class ToolDetector:
    """Detects when tools are actively working based on machine parameters"""
    
    def __init__(self, fanuc_monitor=None):
        self.fanuc_monitor = fanuc_monitor
        self.current_tool = None
        self.tool_active = False
        self.last_activity_time = None
        self.detection_callbacks = []
        
        # Detection thresholds from config
        self.spindle_speed_threshold = Config.TOOL_DETECTION_CONFIG['spindle_speed_threshold']
        self.feed_rate_threshold = Config.TOOL_DETECTION_CONFIG['feed_rate_threshold']
        self.detection_delay = Config.TOOL_DETECTION_CONFIG['detection_delay']
        
    def add_detection_callback(self, callback: Callable):
        """Add callback to be called when tool activity is detected"""
        self.detection_callbacks.append(callback)
    
    def check_tool_activity(self, machine_data: Dict[str, Any]) -> bool:
        """Check if tool is currently active based on machine parameters"""
        if Config.is_development():
            # Simulate tool activity in development mode
            import random
            return random.choice([True, False])
        
        if not machine_data:
            return False
        
        status = machine_data.get('status', {})
        path1_tool = machine_data.get('path1_tool', {})
        path2_tool = machine_data.get('path2_tool', {})
        
        # Check if machine is in AUTO mode and RUNNING
        if status.get('mode') == 1 and status.get('state') == 3:
            # Check spindle speed and feed rate (would need additional FOCAS calls)
            # For now, assume active if machine is running
            tool_active = True
            current_tool = path1_tool.get('tool_number') or path2_tool.get('tool_number')
            
            if tool_active and current_tool:
                self._handle_tool_activity(current_tool)
                return True
        
        return False
    
    def _handle_tool_activity(self, tool_number):
        """Handle detected tool activity"""
        now = time.time()
        
        # Check for tool change
        if self.current_tool != tool_number:
            old_tool = self.current_tool
            self.current_tool = tool_number
            
            # Notify callbacks of tool change
            for callback in self.detection_callbacks:
                try:
                    callback({
                        'type': 'tool_change',
                        'old_tool': old_tool,
                        'new_tool': tool_number,
                        'timestamp': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.error(f"Error in tool detection callback: {e}")
        
        # Update activity status
        if not self.tool_active:
            self.tool_active = True
            self.last_activity_time = now
            
            # Notify callbacks of tool activity start
            for callback in self.detection_callbacks:
                try:
                    callback({
                        'type': 'tool_activity_start',
                        'tool_number': tool_number,
                        'timestamp': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.error(f"Error in tool detection callback: {e}")
        
        self.last_activity_time = now
    
    def check_tool_inactivity(self):
        """Check if tool has been inactive for too long"""
        if self.tool_active and self.last_activity_time:
            inactive_time = time.time() - self.last_activity_time
            
            if inactive_time > self.detection_delay:
                self.tool_active = False
                
                # Notify callbacks of tool activity stop
                for callback in self.detection_callbacks:
                    try:
                        callback({
                            'type': 'tool_activity_stop',
                            'tool_number': self.current_tool,
                            'inactive_time': inactive_time,
                            'timestamp': datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.error(f"Error in tool detection callback: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current tool detection status"""
        return {
            'current_tool': self.current_tool,
            'tool_active': self.tool_active,
            'last_activity_time': self.last_activity_time,
            'inactive_time': time.time() - self.last_activity_time if self.last_activity_time else None
        }

class IntegratedMonitor(threading.Thread):
    """Integrated monitoring system that coordinates Fanuc and data acquisition"""
    
    def __init__(self, fanuc_monitor=None, daq_manager=None):
        super().__init__(daemon=True)
        self.fanuc_monitor = fanuc_monitor
        self.daq_manager = daq_manager
        self.tool_detector = ToolDetector(fanuc_monitor)
        
        self.running = False
        self._stop_event = threading.Event()
        self.status_callbacks = []
        
        # Recording state
        self.auto_recording = False
        self.current_recording_model = None
        self.current_recording_set = None
        
        # Setup tool detection callbacks
        self.tool_detector.add_detection_callback(self._handle_tool_event)
    
    def add_status_callback(self, callback: Callable):
        """Add callback for status updates"""
        self.status_callbacks.append(callback)
    
    def enable_auto_recording(self, model_name: str, set_name: str):
        """Enable automatic recording when tool activity is detected"""
        self.auto_recording = True
        self.current_recording_model = model_name
        self.current_recording_set = set_name
        logger.info(f"Auto-recording enabled for {model_name}/{set_name}")
    
    def disable_auto_recording(self):
        """Disable automatic recording"""
        self.auto_recording = False
        if self.daq_manager and self.daq_manager.recording_active:
            self.daq_manager.stop_recording()
        logger.info("Auto-recording disabled")
    
    def _handle_tool_event(self, event_data):
        """Handle tool detection events"""
        event_type = event_data.get('type')
        
        # Handle tool monitoring state changes
        if event_type == 'tool_monitoring_change':
            if event_data.get('active') and self.auto_recording:
                # Start data acquisition when monitored tool becomes active
                if self.daq_manager and not self.daq_manager.recording_active:
                    success = self.daq_manager.start_recording(
                        self.current_recording_model,
                        self.current_recording_set
                    )
                    if success:
                        logger.info(f"Auto-started recording for monitored tool {event_data.get('tool')}")
                    else:
                        logger.error("Failed to auto-start recording")
                else:
                    logger.debug(f"DAQ already recording or DAQ manager not available - recording_active: {self.daq_manager.recording_active if self.daq_manager else 'None'}")
            
            elif not event_data.get('active') and Config.RECORDING_CONFIG['auto_stop_on_tool_change']:
                # Stop data acquisition when monitored tool becomes inactive
                if self.daq_manager and self.daq_manager.recording_active:
                    self.daq_manager.stop_recording()
                    logger.info(f"Auto-stopped recording - tool {event_data.get('tool')} is not monitored")
                else:
                    logger.debug(f"DAQ not recording or DAQ manager not available - recording_active: {self.daq_manager.recording_active if self.daq_manager else 'None'}")
        
        elif event_type == 'tool_activity_start' and self.auto_recording:
            # Only start if we should record for current tool
            if self.fanuc_monitor and self.fanuc_monitor.should_record_data():
                if self.daq_manager and not self.daq_manager.recording_active:
                    success = self.daq_manager.start_recording(
                        self.current_recording_model,
                        self.current_recording_set
                    )
                    if success:
                        logger.info(f"Auto-started recording for tool {event_data.get('tool_number')}")
                    else:
                        logger.error("Failed to auto-start recording")
                else:
                    logger.debug(f"DAQ already recording or DAQ manager not available")
            else:
                # Only log if this is about the monitored tool
                if self.fanuc_monitor and self.fanuc_monitor.current_tool == self.fanuc_monitor.monitored_tool:
                    should_record = self.fanuc_monitor.should_record_data()
                    logger.debug(f"Not starting recording for monitored tool - should_record: {should_record}")
                else:
                    logger.debug("Not starting recording - tool is not monitored")
                    
        elif event_type == 'tool_activity_stop' and Config.RECORDING_CONFIG['auto_stop_on_tool_change']:
            # Stop data acquisition when tool becomes inactive
            if self.daq_manager and self.daq_manager.recording_active:
                self.daq_manager.stop_recording()
                logger.info(f"Auto-stopped recording for tool {event_data.get('tool_number')}")
            else:
                logger.debug("DAQ not recording - no need to stop")
        
        elif event_type == 'tool_change':
            # Handle tool change - logging is done in fanuc_communication.py
            # Notify status callbacks
            for callback in self.status_callbacks:
                try:
                    callback(event_data)
                except Exception as e:
                    logger.error(f"Error in status callback: {e}")
    
    def run(self):
        """Main monitoring loop"""
        self.running = True
        logger.info("Starting integrated monitoring system")
        
        while not self._stop_event.is_set():
            try:
                # Get Fanuc data if available
                fanuc_data = None
                if self.fanuc_monitor:
                    status = self.fanuc_monitor.get_current_status()
                    if status.get('connected'):
                        fanuc_data = {
                            'status': status.get('machine_status'),
                            'path1_tool': {'tool_number': status.get('current_tool')},
                            'path2_tool': {},
                            'timestamp': time.time()
                        }
                
                # Check tool activity
                if fanuc_data:
                    self.tool_detector.check_tool_activity(fanuc_data)
                
                # Check for tool inactivity
                self.tool_detector.check_tool_inactivity()
                
                # Broadcast status update
                self._broadcast_status_update()
                
                time.sleep(1)  # 1 second monitoring interval
                
            except Exception as e:
                logger.error(f"Error in integrated monitoring loop: {e}")
                time.sleep(5)
        
        logger.info("Integrated monitoring system stopped")
    
    def _broadcast_status_update(self):
        """Broadcast status update to all callbacks"""
        status = self.get_comprehensive_status()
        
        for callback in self.status_callbacks:
            try:
                callback({
                    'type': 'status_update',
                    'status': status,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Error in status broadcast callback: {e}")
    
    def stop(self):
        """Stop the integrated monitoring system"""
        self.running = False
        self._stop_event.set()
        
        # Stop sub-components
        if self.fanuc_monitor and self.fanuc_monitor.running:
            self.fanuc_monitor.stop()
        
        if self.daq_manager and self.daq_manager.recording_active:
            self.daq_manager.stop()
    
    def set_monitored_tool(self, tool_number: int):
        """Set the tool number to monitor for recording"""
        if self.fanuc_monitor:
            self.fanuc_monitor.set_monitored_tool(tool_number)
            logger.info(f"Updated monitored tool to {tool_number}")
        
        # Broadcast status update
        self._broadcast_status_update()
    
    def set_debounce_time(self, debounce_time: float):
        """Set the debounce time for tool monitoring"""
        if self.fanuc_monitor:
            self.fanuc_monitor.set_debounce_time(debounce_time)
            logger.info(f"Updated debounce time to {debounce_time}s")
        
        # Broadcast status update
        self._broadcast_status_update()
    
    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        # Always include monitored tool info at the top level for easy access
        monitored_tool = Config.TOOL_MONITORING_CONFIG['monitored_tool']
        
        status = {
            'integrated_monitor': {
                'running': self.running,
                'auto_recording': self.auto_recording,
                'recording_model': self.current_recording_model,
                'recording_set': self.current_recording_set
            },
            'tool_detection': self.tool_detector.get_status(),
            'monitored_tool': monitored_tool,  # Add monitored tool at top level
            'mode': 'production' if Config.is_production() else 'development'
        }
        
        if self.fanuc_monitor:
            status['fanuc'] = self.fanuc_monitor.get_current_status()
        
        if self.daq_manager:
            status['data_acquisition'] = self.daq_manager.get_status()
        
        return status
