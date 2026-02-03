# Quick Start Guide

## 1. Install Mosquitto MQTT Broker

Install and start the MQTT broker:

```bash
# Install Mosquitto
sudo apt update
sudo apt install mosquitto mosquitto-clients -y

# Enable and start the service
sudo systemctl enable mosquitto
sudo systemctl start mosquitto

# Verify it's running
sudo systemctl status mosquitto
```

## 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## 3. Create Configuration

```bash
cp config.yaml.example config.yaml
nano config.yaml  # Edit with your settings
```

If running locally, update MQTT host to `localhost`:
```yaml
mqtt:
  host: "localhost"  # or "127.0.0.1"
```

## 4. Run in Development Mode

The service will use simulated FANUC clients (no hardware needed):

```bash
python run.py
```

Or with explicit config path:

```bash
python -m app.main config.yaml
```

## 5. Test with MQTT

Subscribe to all events:

```bash
# Subscribe to all topics (use localhost if broker is local)
mosquitto_sub -h localhost -t 'fanuc/#' -v
```

## 6. Switch to Production Mode

Edit `config.yaml`:

```yaml
env: production
```

Ensure FOCAS library is installed:

```bash
ls -l /usr/local/lib/libfwlib32.so
```

Run:

```bash
python run.py
```

## 7. Install as Systemd Service

```bash
sudo cp systemd/fanuc-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fanuc-monitor
sudo systemctl start fanuc-monitor
sudo systemctl status fanuc-monitor
```

## Monitoring

View logs:
```bash
tail -f fanuc-monitor.log
```

Or if running as systemd service:
```bash
sudo journalctl -u fanuc-monitor -f
```

## Troubleshooting

**Service won't start:**
- Check `config.yaml` syntax
- Verify Python version >= 3.11
- Check logs for specific errors

**No MQTT messages:**
- Verify MQTT broker is running
- Check broker IP/port in config
- Test with: `mosquitto_pub -h 192.168.0.10 -t test -m hello`

**Tool changes not detected:**
- Verify CNC connectivity: `ping <cnc_ip>`
- Check FOCAS library path
- Review logs for FOCAS errors
- Verify macro address (default 4120)
