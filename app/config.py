"""Configuration loader and validation"""

import yaml
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PathConfig:
    """Configuration for a monitored CNC path"""
    path: int


@dataclass
class MachineConfig:
    """Configuration for a single CNC machine"""
    machine_id: str
    ip: str
    port: int = 8193
    poll_interval_ms: Optional[int] = None
    monitored_paths: List[PathConfig] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate machine config"""
        if not self.machine_id:
            raise ValueError("machine_id is required")
        if not self.ip:
            raise ValueError("ip is required")
        if not self.monitored_paths:
            raise ValueError("monitored_paths array is required")
        
        # Convert path dictionaries to PathConfig objects if needed
        if self.monitored_paths and isinstance(self.monitored_paths[0], dict):
            self.monitored_paths = [
                PathConfig(path=p['path']) for p in self.monitored_paths
            ]


@dataclass
class FOCASConfig:
    """FOCAS library configuration"""
    library_path: str = "/usr/local/lib/libfwlib32.so"
    macro_address: int = 4120
    macro_length: int = 10


@dataclass
class MQTTConfig:
    """MQTT broker configuration"""
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    
    def __post_init__(self):
        """Validate MQTT config"""
        if not self.host:
            raise ValueError("MQTT host is required")


@dataclass
class MonitoringConfig:
    """Monitoring behavior configuration"""
    poll_interval_ms_default: int = 100
    debounce_consecutive_reads: int = 2
    heartbeat_interval_s: int = 2
    reconnect_min_delay_s: float = 0.5
    reconnect_max_delay_s: float = 30.0


@dataclass
class Config:
    """Complete application configuration"""
    env: str
    focas: FOCASConfig
    mqtt: MQTTConfig
    monitoring: MonitoringConfig
    machines: List[MachineConfig]
    
    def __post_init__(self):
        """Validate complete config"""
        if self.env not in ['development', 'production']:
            raise ValueError("env must be 'development' or 'production'")
        if not self.machines:
            raise ValueError("At least one machine must be configured")
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.env == 'development'
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode"""
        return self.env == 'production'


def load_config(config_path: str = "config.yaml") -> Config:
    """
    Load and validate configuration from YAML file
    
    Args:
        config_path: Path to config.yaml file
        
    Returns:
        Validated Config object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    logger.info(f"Loading configuration from {config_path}")
    
    with open(path, 'r') as f:
        data = yaml.safe_load(f)
    
    if not data:
        raise ValueError("Config file is empty")
    
    # Parse configuration with defaults
    try:
        # Parse FOCAS config
        focas_data = data.get('focas', {})
        focas_config = FOCASConfig(
            library_path=focas_data.get('library_path', FOCASConfig.library_path),
            macro_address=focas_data.get('macro_address', FOCASConfig.macro_address),
            macro_length=focas_data.get('macro_length', FOCASConfig.macro_length)
        )
        
        # Parse MQTT config
        mqtt_data = data.get('mqtt', {})
        if not mqtt_data:
            raise ValueError("mqtt section is required in config")
        mqtt_config = MQTTConfig(**mqtt_data)
        
        # Parse monitoring config
        monitoring_data = data.get('monitoring', {})
        monitoring_config = MonitoringConfig(
            poll_interval_ms_default=monitoring_data.get('poll_interval_ms_default', MonitoringConfig.poll_interval_ms_default),
            debounce_consecutive_reads=monitoring_data.get('debounce_consecutive_reads', MonitoringConfig.debounce_consecutive_reads),
            heartbeat_interval_s=monitoring_data.get('heartbeat_interval_s', MonitoringConfig.heartbeat_interval_s),
            reconnect_min_delay_s=monitoring_data.get('reconnect_min_delay_s', MonitoringConfig.reconnect_min_delay_s),
            reconnect_max_delay_s=monitoring_data.get('reconnect_max_delay_s', MonitoringConfig.reconnect_max_delay_s)
        )
        
        # Parse machines
        machines_data = data.get('machines', [])
        if not machines_data:
            raise ValueError("machines array is required and must not be empty")
        
        machines = []
        for machine_data in machines_data:
            machine = MachineConfig(
                machine_id=machine_data['machine_id'],
                ip=machine_data['ip'],
                port=machine_data.get('port', 8193),
                poll_interval_ms=machine_data.get('poll_interval_ms'),
                monitored_paths=machine_data['monitored_paths']
            )
            machines.append(machine)
        
        # Create complete config
        config = Config(
            env=data.get('env', 'development'),
            focas=focas_config,
            mqtt=mqtt_config,
            monitoring=monitoring_config,
            machines=machines
        )
        
        # Log config summary
        logger.info(f"Configuration loaded successfully:")
        logger.info(f"  - Environment: {config.env}")
        logger.info(f"  - MQTT Broker: {config.mqtt.host}:{config.mqtt.port}")
        logger.info(f"  - Machines: {len(config.machines)}")
        for machine in config.machines:
            logger.info(f"    - {machine.machine_id} ({machine.ip}) - {len(machine.monitored_paths)} path(s)")
        
        return config
        
    except KeyError as e:
        raise ValueError(f"Missing required config field: {e}")
    except Exception as e:
        raise ValueError(f"Invalid configuration: {e}")
