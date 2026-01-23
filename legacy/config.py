import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application configuration"""
    
    # App Info
    app_name: str = "Tool Wear Monitor"
    app_version: str = "1.0.0"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Hardware - DAQ
    daq_sample_rate: int = 51200
    daq_channel: int = 0
    daq_sensitivity: float = 100.0  # Sensor sensitivity in mV/unit (e.g., 100 mV/g for accelerometer)
    use_mock_daq: bool = True  # Auto-detect if False
    
    # Hardware - Fanuc
    fanuc_ip: str = "10.151.32.81"
    fanuc_port: int = 8193
    fanuc_timeout: int = 5000
    use_mock_fanuc: bool = True  # Auto-detect if False
    fanuc_tool_cycle_interval: int = 5  # seconds for mock
    
    # Recording
    min_duration: float = 3.0  # seconds
    max_duration: float = 15.0  # seconds
    save_raw_timeseries: bool = True
    
    # Storage
    base_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir: str = os.path.join(base_dir, "..", "data")
    timeseries_dir: str = os.path.join(data_dir, "timeseries")
    models_dir: str = os.path.join(data_dir, "models")
    database_url: str = f"sqlite:///{os.path.join(data_dir, 'metadata.db')}"
    
    # Data aggregation for plotting
    plot_time_bucket: float = 0.005  # seconds - time window for aggregating samples (abs max)
    
    # UI Display
    max_recordings_display: int = 20  # maximum number of recordings to show in list
    
    # CORS
    cors_origins: list = ["http://localhost:3000", "http://localhost:5173"]
    
    class Config:
        env_file = ".env"

settings = Settings()

# Create directories
os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.timeseries_dir, exist_ok=True)
os.makedirs(settings.models_dir, exist_ok=True)
