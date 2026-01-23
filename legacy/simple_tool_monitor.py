#!/usr/bin/env python3
"""
Simple Fanuc Tool Monitor
A standalone script to monitor the current tool using the existing Fanuc communication functions.
"""

import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Add the project directory to the Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from fanuc_communication import FanucConnection, FanucMonitor
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('tool_monitor.log')
    ]
)

logger = logging.getLogger(__name__)

class SimpleToolMonitor:
    """Simple tool monitoring class"""
    
    def __init__(self):
        self.connection = None
        self.monitor = None
        self.running = False
        
        # Display configuration
        self.last_tool = None
        self.last_status = None
        self.start_time = datetime.now()
        
    def setup_connection(self):
        """Setup Fanuc connection"""
        try:
            # Get Fanuc configuration
            fanuc_config = Config.FANUC_CONFIG
            
            # Create connection
            self.connection = FanucConnection(
                ip_address=fanuc_config['ip_address'],
                port=fanuc_config['port'],
                timeout=fanuc_config['timeout']
            )
            
            # Create monitor with callback
            self.monitor = FanucMonitor(
                connection=self.connection,
                update_callback=self.on_update
            )
            
            logger.info(f"Connecting to Fanuc CNC at {fanuc_config['ip_address']}:{fanuc_config['port']}")
            
            # Test connection
            if self.connection.connect():
                logger.info("Successfully connected to Fanuc CNC")
                return True
            else:
                logger.error("Failed to connect to Fanuc CNC")
                return False
                
        except Exception as e:
            logger.error(f"Error setting up connection: {e}")
            return False
    
    def on_update(self, data):
        """Callback for monitor updates"""
        try:
            # Handle different types of updates
            if data.get('type') == 'tool_monitoring_change':
                active = data.get('active', False)
                tool = data.get('tool')
                status = "ACTIVE" if active else "INACTIVE"
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tool Monitoring: {status} (Tool: {tool})")
                
            elif 'status' in data:
                # Regular status update
                status = data['status']
                path1_tool = data.get('path1_tool', {})
                path2_tool = data.get('path2_tool', {})
                
                # Get current tool (prefer path 1)
                current_tool = path1_tool.get('tool_number') if path1_tool else None
                if not current_tool and path2_tool:
                    current_tool = path2_tool.get('tool_number')
                
                # Check for tool changes
                if current_tool != self.last_tool:
                    self.last_tool = current_tool
                    tool_str = f"T{current_tool}" if current_tool else "None"
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] TOOL CHANGE: {tool_str}")
                    
                    # Show tool details
                    if path1_tool:
                        prog_num = path1_tool.get('program_number', 'N/A')
                        macro_val = path1_tool.get('macro_value', 'N/A')
                        print(f"  Program: O{prog_num}, Macro Value: {macro_val}")
                
                # Update status display periodically
                self._update_status_display(status, current_tool)
                
        except Exception as e:
            logger.error(f"Error in update callback: {e}")
    
    def _update_status_display(self, status, current_tool):
        """Update the status display"""
        try:
            # Only update display every 5 seconds or on tool change
            current_time = time.time()
            if not hasattr(self, '_last_display_time'):
                self._last_display_time = 0
            
            if current_time - self._last_display_time >= 5.0 or current_tool != self.last_tool:
                self._last_display_time = current_time
                
                # Clear line and show status
                print(f"\r[{datetime.now().strftime('%H:%M:%S')}] Status: "
                      f"Tool=T{current_tool or 'None'} | "
                      f"Mode={'AUTO' if status.get('mode') == 1 else 'MANUAL'} | "
                      f"State={'RUN' if status.get('state') == 3 else 'STOP'} | "
                      f"Emergency={'YES' if status.get('emergency') else 'NO'} | "
                      f"Alarm={'YES' if status.get('alarm') else 'NO'}", 
                      end='', flush=True)
                      
        except Exception as e:
            logger.error(f"Error updating status display: {e}")
    
    def print_header(self):
        """Print the header information"""
        print("=" * 80)
        print("                    FANUC TOOL MONITOR")
        print("=" * 80)
        print(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Mode: {'Development (Simulated)' if Config.is_development() else 'Production (Real Hardware)'}")
        print(f"Monitored Tool: T{Config.TOOL_MONITORING_CONFIG['monitored_tool']}")
        print(f"Record Only Monitored Tool: {Config.TOOL_MONITORING_CONFIG['record_only_monitored_tool']}")
        print("-" * 80)
        print("Monitoring for tool changes... (Press Ctrl+C to stop)")
        print("-" * 80)
    
    def run(self):
        """Main run loop"""
        try:
            # Setup connection
            if not self.setup_connection():
                print("Failed to setup connection. Exiting.")
                return
            
            # Print header
            self.print_header()
            
            # Start monitoring
            self.monitor.start()
            self.running = True
            
            # Keep the main thread alive
            try:
                while self.running:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                print("\n\nShutdown requested by user...")
                
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            print(f"Error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            print("\nCleaning up...")
            self.running = False
            
            if self.monitor:
                self.monitor.stop()
                self.monitor.join(timeout=5.0)
                
            if self.connection:
                self.connection.disconnect()
                
            print("Cleanup complete. Goodbye!")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def main():
    """Main entry point"""
    print("Starting Simple Fanuc Tool Monitor...")
    
    try:
        # Check if config is available
        if not hasattr(Config, 'FANUC_CONFIG'):
            print("Error: FANUC_CONFIG not found in config.py")
            print("Make sure your configuration is set up correctly.")
            return 1
        
        # Create and run monitor
        monitor = SimpleToolMonitor()
        monitor.run()
        
        return 0
        
    except Exception as e:
        print(f"Fatal error: {e}")
        logger.exception("Fatal error in main")
        return 1

if __name__ == "__main__":
    sys.exit(main())
