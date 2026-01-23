#!/usr/bin/env python3
"""
Basic Fanuc Tool Reader
A simple script that reads the current tool information once or continuously.
"""

import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

# Add the project directory to the Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from fanuc_communication import FanucConnection
from config import Config

def read_tool_info(connection):
    """Read and display current tool information"""
    try:
        # Read machine status
        status = connection.read_status()
        if not status:
            print("Failed to read machine status")
            return False
        
        # Read tool info for both paths
        path1_info = connection.read_tool_info(1)
        path2_info = connection.read_tool_info(2)
        
        # Display timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n[{timestamp}] Fanuc CNC Status:")
        print("-" * 50)
        
        # Display machine status
        mode = "AUTO" if status.get('mode') == 1 else "MANUAL"
        state = "RUN" if status.get('state') == 3 else "STOP"
        emergency = "YES" if status.get('emergency') else "NO"
        alarm = "YES" if status.get('alarm') else "NO"
        
        print(f"Machine Mode:  {mode}")
        print(f"Machine State: {state}")
        print(f"Emergency:     {emergency}")
        print(f"Alarm:         {alarm}")
        print()
        
        # Display tool information
        if path1_info:
            tool_num = path1_info.get('tool_number', 'None')
            prog_num = path1_info.get('program_number', 'N/A')
            macro_val = path1_info.get('macro_value', 'N/A')
            
            print(f"Path 1 Tool:   T{tool_num}")
            print(f"Program:       O{prog_num}")
            print(f"Macro Value:   {macro_val}")
        else:
            print("Path 1 Tool:   No data")
        
        if path2_info:
            tool_num = path2_info.get('tool_number', 'None')
            prog_num = path2_info.get('program_number', 'N/A')
            macro_val = path2_info.get('macro_value', 'N/A')
            
            print(f"Path 2 Tool:   T{tool_num}")
            print(f"Program:       O{prog_num}")
            print(f"Macro Value:   {macro_val}")
        else:
            print("Path 2 Tool:   No data")
        
        return True
        
    except Exception as e:
        print(f"Error reading tool info: {e}")
        return False

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Basic Fanuc Tool Reader')
    parser.add_argument('--continuous', '-c', action='store_true',
                       help='Continuously monitor (default: read once)')
    parser.add_argument('--interval', '-i', type=float, default=2.0,
                       help='Update interval in seconds (default: 2.0)')
    
    args = parser.parse_args()
    
    print("Basic Fanuc Tool Reader")
    print("=" * 50)
    
    try:
        # Get Fanuc configuration
        fanuc_config = Config.FANUC_CONFIG
        
        print(f"Connecting to: {fanuc_config['ip_address']}:{fanuc_config['port']}")
        print(f"Mode: {'Development (Simulated)' if Config.is_development() else 'Production (Real Hardware)'}")
        
        # Create connection
        connection = FanucConnection(
            ip_address=fanuc_config['ip_address'],
            port=fanuc_config['port'],
            timeout=fanuc_config['timeout']
        )
        
        # Connect to CNC
        if not connection.connect():
            print("Failed to connect to Fanuc CNC")
            return 1
        
        print("Connected successfully!")
        
        if args.continuous:
            print(f"Monitoring continuously (interval: {args.interval}s)")
            print("Press Ctrl+C to stop...")
            
            try:
                while True:
                    read_tool_info(connection)
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nStopping...")
        else:
            # Read once
            read_tool_info(connection)
        
        # Disconnect
        connection.disconnect()
        print("\nDisconnected.")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
