# FANUC CNC Monitor

Production-ready Raspberry Pi 4 service that continuously monitors multiple FANUC CNC machines via FOCAS and publishes low-latency MQTT notifications on tool changes.

## Features

- ✅ **Multi-machine monitoring** - Monitor many CNC machines concurrently
- ✅ **Dual-path support** - Track both spindles independently on dual-path machines
- ✅ **Edge-triggered detection** - Tool changes published exactly once with debouncing
- ✅ **MQTT eventing** - Real-time notifications via MQTT (QoS 1)
- ✅ **Automatic reconnection** - Exponential backoff for CNC and MQTT connections
- ✅ **Path isolation** - One path failure doesn't stop other paths
- ✅ **Dev/Production modes** - Simulate CNC hardware for development
- ✅ **Low latency** - 100ms polling by default, configurable per machine
- ✅ **Systemd ready** - Autostart on boot with automatic restart

## Architecture

```
app/
├── main.py              # Service entrypoint
├── config.py            # YAML configuration loader
├── monitor.py           # Per-machine monitor with debouncing
├── mqtt_pub.py          # MQTT publisher with reconnection
├── fanuc_client.py      # Abstract FANUC client interface
├── fanuc_client_impl.py # Production FOCAS implementation
└── fake_fanuc_client.py # Development simulator
```

## MQTT Topics

### Tool Change Events (QoS 1)
```
fanuc/<machine_id>/event/tool_change/path1
fanuc/<machine_id>/event/tool_change/path2
```

Payload:
```json
{
  "machine_id": "lathe_03",
  "path": 1,
  "ip": "10.151.32.81",
  "event": "tool_change",
  "tool_previous": 12,
  "tool_current": 5,
  "ts_unix_ms": 1730000000000,
  "source": "rpi4-monitor"
}
```

### Error Events (QoS 1)
```
fanuc/<machine_id>/event/error
```

Payload:
```json
{
  "machine_id": "lathe_03",
  "path": 1,
  "ip": "10.151.32.81",
  "error": "Failed to read macro: FOCAS return code -1",
  "ts_unix_ms": 1730000000000,
  "source": "rpi4-monitor"
}
```

### Heartbeat/State (QoS 0, every 2 seconds)
```
fanuc/<machine_id>/state
```

Payload:
```json
{
  "machine_id": "lathe_03",
  "ip": "10.151.32.81",
  "connected": true,
  "path1_status": "ok",
  "path2_status": "error",
  "path2_error": "FOCAS error code: -1",
  "ts_unix_ms": 1730000000000,
  "source": "rpi4-monitor"
}
```

## Installation

### Prerequisites

- Python 3.11+
- FANUC FOCAS library (`libfwlib32.so`) installed at `/usr/local/lib/` (production mode only)
- MQTT broker (e.g., Mosquitto)

### Installing FOCAS Library (Production Only)

For production mode, you need the FANUC FOCAS library. You can install it from the community repository:

1. **Download the library**
   ```bash
   # Clone the fwlib repository
   git clone https://github.com/strangesast/fwlib.git
   cd fwlib
   ```

2. **Install the library**
   ```bash
   # For x86 32-bit systems
   sudo cp libfwlib32-linux-x86.so.1.0.5 /usr/local/lib/libfwlib32.so
   
   # OR for x86_64 64-bit systems (like Raspberry Pi 4 64-bit)
   sudo cp libfwlib32-linux-x64.so.1.0.5 /usr/local/lib/libfwlib32.so
   
   # OR for ARM systems (like Raspberry Pi 32-bit)
   sudo cp libfwlib32-linux-armv7.so.1.0.5 /usr/local/lib/libfwlib32.so
   
   # Update library cache
   sudo ldconfig
   ```

3. **Verify installation**
   ```bash
   ls -l /usr/local/lib/libfwlib*.so
   ```

4. **Update config.yaml if using non-default path**
   ```yaml
   focas:
     library_path: "/usr/local/lib/libfwlib32.so"
   ```

**Note:** The library from this repository is reverse-engineered and may not support all FOCAS functions. For production use, consider obtaining the official FANUC FOCAS library if available.

### Setup

1. **Clone repository**
   ```bash
   cd ~
   git clone <repository-url> iskra-fanuc-hub
   cd iskra-fanuc-hub
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure**
   ```bash
   cp config.yaml.example config.yaml
   nano config.yaml  # Edit configuration
   ```

5. **Test in development mode**
   ```bash
   python -m app.main config.yaml
   ```

## Configuration

See `config.yaml.example` for full configuration options.

### Key Settings

- `env`: `development` (fake client) or `production` (real FOCAS)
- `focas.library_path`: Path to FOCAS library (default: `/usr/local/lib/libfwlib32.so`)
- `focas.macro_address`: Macro variable for tool number (default: 4120)
- `mqtt.host`: MQTT broker IP address
- `monitoring.poll_interval_ms_default`: Polling frequency (default: 100ms)
- `monitoring.debounce_consecutive_reads`: Consecutive reads to confirm tool change (default: 2)

### Machine Configuration

```yaml
machines:
  - machine_id: "lathe_03"      # Simple identifier
    ip: "10.151.32.81"            # CNC IP address
    port: 8193                   # FOCAS port (default: 8193)
    poll_interval_ms: 100        # Optional: override default
    monitored_paths:
      - path: 1                  # Monitor path 1
      - path: 2                  # Monitor path 2
```

## Running

### Development Mode (no FOCAS library needed)

```bash
source venv/bin/activate
python -m app.main config.yaml
```

### Production Mode

1. **Set environment to production in config.yaml**
   ```yaml
   env: production
   ```

2. **Ensure FOCAS library is installed**
   ```bash
   ls -l /usr/local/lib/libfwlib32.so
   ```

3. **Run service**
   ```bash
   python -m app.main config.yaml
   ```

## Systemd Service (Production)

### Install Service

```bash
# Copy service file
sudo cp systemd/fanuc-monitor.service /etc/systemd/system/

# Edit paths if needed
sudo nano /etc/systemd/system/fanuc-monitor.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable fanuc-monitor

# Start service
sudo systemctl start fanuc-monitor
```

### Manage Service

```bash
# Check status
sudo systemctl status fanuc-monitor

# View logs
sudo journalctl -u fanuc-monitor -f

# Restart service
sudo systemctl restart fanuc-monitor

# Stop service
sudo systemctl stop fanuc-monitor
```

## Testing

Run tests (uses fake FANUC client):

```bash
source venv/bin/activate
pytest tests/
```

## Monitoring

### View Logs

```bash
# Service log file
tail -f fanuc-monitor.log

# Systemd journal (if running as service)
sudo journalctl -u fanuc-monitor -f
```

### Subscribe to MQTT Topics

```bash
# Tool change events
mosquitto_sub -h 192.168.0.10 -t 'fanuc/+/event/tool_change/#' -v

# All events
mosquitto_sub -h 192.168.0.10 -t 'fanuc/+/event/#' -v

# Heartbeats
mosquitto_sub -h 192.168.0.10 -t 'fanuc/+/state' -v
```

## Troubleshooting

### FOCAS Library Not Found

```bash
# Check if library exists
ls -l /usr/local/lib/libfwlib32.so

# Update config.yaml with correct path
nano config.yaml
```

### Connection Failures

- Verify CNC IP addresses and network connectivity: `ping 10.151.32.81`
- Check FOCAS port (default 8193) is open on CNC
- Review logs for specific error codes
- Verify CNC is powered on and FOCAS server is running

### MQTT Connection Issues

- Verify MQTT broker is running: `mosquitto -v`
- Check broker IP and port in config.yaml
- Test connection: `mosquitto_pub -h 192.168.0.10 -t test -m "hello"`

### Tool Changes Not Detected

- Check polling interval is appropriate
- Verify macro address (4120) is correct for your CNC
- Increase debounce reads if tool values are noisy
- Check logs for read errors

## Development

### Project Structure

- `app/` - Main application code
- `legacy/` - Reference implementation (do not modify)
- `tests/` - Test suite
- `systemd/` - Systemd service file

### Running Tests

```bash
pytest tests/ -v
```

### Adding New Machines

1. Edit `config.yaml`
2. Add machine to `machines` array
3. Restart service

## License

[Add your license here]

## Support

[Add support contact information]
