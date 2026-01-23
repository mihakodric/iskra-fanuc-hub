# Quick Start Guide

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Create Configuration

```bash
cp config.yaml.example config.yaml
nano config.yaml  # Edit with your settings
```

## 3. Run in Development Mode

The service will use simulated FANUC clients (no hardware needed):

```bash
python run.py
```

Or with explicit config path:

```bash
python -m app.main config.yaml
```

## 4. Test with MQTT

Subscribe to all events:

```bash
# Install mosquitto clients if needed
sudo apt-get install mosquitto-clients

# Subscribe to all topics
mosquitto_sub -h 192.168.0.10 -t 'fanuc/#' -v
```

## 5. Switch to Production Mode

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

## 6. Install as Systemd Service

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
