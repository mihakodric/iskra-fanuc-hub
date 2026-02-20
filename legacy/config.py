# Configuration file for the Iskra Tool Wear Application
import os
from enum import Enum

class AppMode(Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"

class Config:
    # Application Mode - Switch between development and production
    APP_MODE = AppMode(os.getenv('APP_MODE', 'production'))
    
    # Database Configuration
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_FOLDER = os.path.join(BASE_DIR, 'data')
    DB_FILE = os.path.join(BASE_DIR, 'app.db')
    
    # Data Storage Configuration
    DATA_STORAGE_PATH = os.path.join(BASE_DIR, 'data', 'timeseries')
    
    # Fanuc CNC Configuration
    FANUC_CONFIG = {
        'ip_address': os.getenv('FANUC_IP', '10.151.32.81'),
        'port': int(os.getenv('FANUC_PORT', '8193')),
        'timeout': int(os.getenv('FANUC_TIMEOUT', '10')),
        'retry_attempts': int(os.getenv('FANUC_RETRY_ATTEMPTS', '3')),
        'retry_delay': float(os.getenv('FANUC_RETRY_DELAY', '1.0')),
        'macro_address': int(os.getenv('FANUC_MACRO_ADDRESS', '4120')),
        'macro_length': int(os.getenv('FANUC_MACRO_LENGTH', '10')),
        'enabled': os.getenv('FANUC_ENABLED', 'false').lower() == 'true' if APP_MODE == AppMode.PRODUCTION else False
    }
    
    # MCC 172 DAQ Configuration
    MCC172_CONFIG = {
        'sample_rate': float(os.getenv('MCC172_SAMPLE_RATE', '1000.0')),
        'channels': [int(ch) for ch in os.getenv('MCC172_CHANNELS', '0,1').split(',')],
        'address': int(os.getenv('MCC172_ADDRESS', '0')),  # DAQ HAT address (0-7)
        'enabled': os.getenv('MCC172_ENABLED', 'false').lower() == 'true' if APP_MODE == AppMode.PRODUCTION else False
    }
    
    # Recording Configuration
    RECORDING_CONFIG = {
        'file_interval': float(os.getenv('RECORDING_INTERVAL', '10.0')),  # seconds between files
        'max_recording_duration': int(os.getenv('MAX_RECORDING_DURATION', '3600')),  # max recording time in seconds
        'auto_stop_on_tool_change': os.getenv('AUTO_STOP_ON_TOOL_CHANGE', 'true').lower() == 'true',
        'data_format': os.getenv('DATA_FORMAT', 'hdf5').lower(),  # 'hdf5', 'npz', or 'json'
        'compression': os.getenv('DATA_COMPRESSION', 'true').lower() == 'true'  # Enable compression for data files
    }
    
    # Tool Detection Configuration
    TOOL_DETECTION_CONFIG = {
        'spindle_speed_threshold': float(os.getenv('SPINDLE_SPEED_THRESHOLD', '100.0')),  # RPM
        'feed_rate_threshold': float(os.getenv('FEED_RATE_THRESHOLD', '10.0')),  # mm/min
        'detection_delay': float(os.getenv('TOOL_DETECTION_DELAY', '5.0'))  # seconds
    }
    
    # Tool Monitoring Configuration
    TOOL_MONITORING_CONFIG = {
        'monitored_tool': int(os.getenv('MONITORED_TOOL', '2220')),  # Tool number to monitor
        'record_only_monitored_tool': os.getenv('RECORD_ONLY_MONITORED_TOOL', 'true').lower() == 'true',
        'tool_change_debounce': float(os.getenv('TOOL_CHANGE_DEBOUNCE', '2.0'))  # seconds to debounce tool changes
    }
    
    # Flask Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
    DEBUG = APP_MODE == AppMode.DEVELOPMENT
    
    @classmethod
    def is_production(cls):
        return cls.APP_MODE == AppMode.PRODUCTION
    
    @classmethod
    def is_development(cls):
        return cls.APP_MODE == AppMode.DEVELOPMENT
    
    @classmethod
    def update_recording_config_from_db(cls):
        """Update recording configuration from database settings"""
        try:
            from db import get_data_format_settings
            db_settings = get_data_format_settings()
            cls.RECORDING_CONFIG['data_format'] = db_settings['data_format']
            cls.RECORDING_CONFIG['compression'] = db_settings['compression_enabled']
        except Exception as e:
            print(f"Warning: Could not load data format settings from database: {e}")
            # Keep defaults from environment variables