"""Main entrypoint for FANUC CNC monitoring service"""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import List

from .config import load_config, Config
from .mqtt_pub import MQTTPublisher
from .monitor import MachineMonitor
from .fanuc_client_impl import FanucClientImpl
from .fake_fanuc_client import FakeFanucClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('fanuc-monitor.log')
    ]
)

logger = logging.getLogger(__name__)


class MonitorService:
    """Main monitoring service coordinator"""
    
    def __init__(self, config: Config):
        self.config = config
        self.mqtt_publisher: MQTTPublisher = None
        self.monitors: List[MachineMonitor] = []
        self._running = False
    
    async def start(self) -> None:
        """Start the monitoring service"""
        if self._running:
            logger.warning("Service already running")
            return
        
        self._running = True
        
        logger.info("=" * 60)
        logger.info("FANUC CNC Monitor Service Starting")
        logger.info("=" * 60)
        logger.info(f"Environment: {self.config.env}")
        logger.info(f"MQTT Broker: {self.config.mqtt.host}:{self.config.mqtt.port}")
        logger.info(f"Monitored Machines: {len(self.config.machines)}")
        
        # Start MQTT publisher
        self.mqtt_publisher = MQTTPublisher(
            host=self.config.mqtt.host,
            port=self.config.mqtt.port,
            username=self.config.mqtt.username,
            password=self.config.mqtt.password,
            tls=self.config.mqtt.tls
        )
        await self.mqtt_publisher.start()
        
        # Create and start monitors for each machine
        for machine_config in self.config.machines:
            # Create FANUC client (production or fake)
            if self.config.is_production:
                fanuc_client = FanucClientImpl(
                    machine_id=machine_config.machine_id,
                    ip=machine_config.ip,
                    port=machine_config.port,
                    library_path=self.config.focas.library_path,
                    macro_address=self.config.focas.macro_address
                )
                logger.info(f"[{machine_config.machine_id}] Using production FOCAS client")
            else:
                fanuc_client = FakeFanucClient(
                    machine_id=machine_config.machine_id,
                    ip=machine_config.ip,
                    port=machine_config.port
                )
                logger.info(f"[{machine_config.machine_id}] Using simulated FANUC client")
            
            # Extract path numbers
            monitored_paths = [p.path for p in machine_config.monitored_paths]
            
            # Determine poll interval
            poll_interval = (
                machine_config.poll_interval_ms 
                if machine_config.poll_interval_ms 
                else self.config.monitoring.poll_interval_ms_default
            )
            
            # Create monitor
            monitor = MachineMonitor(
                machine_id=machine_config.machine_id,
                ip=machine_config.ip,
                port=machine_config.port,
                monitored_paths=monitored_paths,
                fanuc_client=fanuc_client,
                mqtt_publisher=self.mqtt_publisher,
                poll_interval_ms=poll_interval,
                debounce_consecutive_reads=self.config.monitoring.debounce_consecutive_reads,
                heartbeat_interval_s=self.config.monitoring.heartbeat_interval_s,
                reconnect_min_delay_s=self.config.monitoring.reconnect_min_delay_s,
                reconnect_max_delay_s=self.config.monitoring.reconnect_max_delay_s
            )
            
            self.monitors.append(monitor)
            await monitor.start()
        
        logger.info("=" * 60)
        logger.info(f"Service started successfully - monitoring {len(self.monitors)} machine(s)")
        logger.info("=" * 60)
    
    async def stop(self) -> None:
        """Stop the monitoring service"""
        if not self._running:
            return
        
        self._running = False
        
        logger.info("Shutting down monitoring service...")
        
        # Stop all monitors
        for monitor in self.monitors:
            await monitor.stop()
        self.monitors.clear()
        
        # Stop MQTT publisher
        if self.mqtt_publisher:
            await self.mqtt_publisher.stop()
        
        logger.info("Service stopped")
    
    async def run(self) -> None:
        """Run the service until interrupted"""
        await self.start()
        
        # Wait for shutdown signal
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


async def main(config_path: str = "config.yaml") -> None:
    """Main async entry point"""
    
    # Load configuration
    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    # Create service
    service = MonitorService(config)
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def handle_shutdown(signum):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(service.stop())
        loop.stop()
    
    # Register signal handlers (Unix signals)
    try:
        loop.add_signal_handler(signal.SIGINT, lambda: handle_shutdown(signal.SIGINT))
        loop.add_signal_handler(signal.SIGTERM, lambda: handle_shutdown(signal.SIGTERM))
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        signal.signal(signal.SIGINT, lambda s, f: handle_shutdown(s))
        signal.signal(signal.SIGTERM, lambda s, f: handle_shutdown(s))
    
    # Run service
    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        await service.stop()
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        await service.stop()
        sys.exit(1)


def run():
    """Synchronous entry point for console script"""
    import sys
    
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    
    try:
        asyncio.run(main(config_path))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    run()
