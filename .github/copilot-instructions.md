# Iskra FANUC Hub — Copilot Instructions (RPi4 Monitor + MQTT)

## Mission
Build a **new production-ready Raspberry Pi 4 service** that continuously monitors **multiple FANUC CNC machines** via **FOCAS** (legacy code exists) and publishes **low-latency MQTT notifications** on **tool change** per machine.

This service must:
- Run 24/7 as a background process
- Monitor many machines at once
- Survive disconnects and recover automatically
- Notify other devices (e.g. Raspberry Pi 5 recorders) immediately when a tool change occurs

---

## What already exists in the repo (MUST reuse working knowledge, NOT structure)
Legacy code in `legacy/` already reads the current tool reliably using FOCAS. Use it as reference and reuse its proven logic where applicable.

### Key Legacy Files
- `legacy/fanuc_communication.py`
  - `FanucConnection`: low-level FOCAS communication (connect/disconnect, tool info reads, status reads)
  - `FanucMonitor`: background thread that polls and triggers callbacks on changes
- `legacy/tool_monitoring.py`
  - Higher-level tool activity detection (`ToolDetector`, `IntegratedMonitor`)
  - (Optional for later — tool-change is priority now)
- Standalone scripts (known-good tests)
  - `legacy/basic_tool_reader.py`
  - `legacy/simple_tool_monitor.py`
- `legacy/focas-snippets/`
  - Original ctypes prototypes and FOCAS structures

✅ **Important:** the new service should be a clean rewrite in a new folder (do not extend legacy threading design), but it should **lift the proven FOCAS reading logic**, such as:
- macro conversion method
- return-code handling
- path selection via `cnc_setpath()`
- FOCAS connection pattern + locks if needed

---

## Core Requirements

### 1) Multi-machine monitoring (MUST)
- Load machines from `config.yaml`
- Each machine must have at least:
  - `machine_id` (stable unique string, simple format like "lathe_03")
  - `ip`
  - `port` (default 8193)
  - `monitored_paths` array with per-path configuration
  - optional: `poll_interval_ms` (default 100ms)

Concurrency rules:
- One monitoring task per machine per path (asyncio-based)
- Path failures are isolated - one path failing does not stop other paths or machines
- No single machine or path failure may stop the whole service

---

### 2) Tool change detection (EDGE-triggered + debounced)
- Define “tool current” as the value read from the CNC (typically a macro variable)
- Tool change event triggers **only when tool changes from previous stable tool to new stable tool**
- Debounce rules:
  - require `N` consecutive polls returning the same new tool value before confirming (`N` default 2)
  - optional cooldown to avoid double-fire from flicker (e.g. 250–500ms)
- Publish **exactly once** per tool transition

🚫 **DO NOT publish on every poll.**

---

### 3) MQTT eventing contract (MUST)
Use MQTT to notify devices in the same LAN quickly and reliably.

#### Topics
- Tool-change event (per path):
  - `fanuc/<machine_id>/event/tool_change/path1`
  - `fanuc/<machine_id>/event/tool_change/path2`
- Error event:
  - `fanuc/<machine_id>/event/error`
- Heartbeat/state (per machine):
  - `fanuc/<machine_id>/state`

#### Payloads (JSON)

Tool change payload:
```json
{
  "machine_id": "lathe_03",
  "path": 1,
  "ip": "10.151.32.81",
  "event": "tool_change",
  "tool_previous": 12,
  "tool_current": 5,
  "ts_unix_ms": 1730000000000,
  "source": "100.113.52.109"
}
```

Error event payload:
```json
{
  "machine_id": "lathe_03",
  "path": 1,
  "ip": "10.151.32.81",
  "error": "Failed to read macro: FOCAS return code -1",
  "ts_unix_ms": 1730000000000,
  "source": "100.113.52.109"
}
```

Heartbeat/state payload (every 2 seconds):
```json
{
  "machine_id": "lathe_03",
  "ip": "10.151.32.81",
  "connected": true,
  "path1_status": "ok",
  "path2_status": "error",
  "path2_error": "FOCAS error code: -1",
  "ts_unix_ms": 1730000000000,
  "source": "100.113.52.109"
}
```

#### MQTT QoS + retain rules
- `tool_change`: QoS 1, retain=false
- `error`: QoS 1, retain=false
- `state`: QoS 0, retain=false

#### MQTT Broker
- Anonymous access (no authentication)
- Runs on same RPi4 or separate machine
- Default example: 192.168.0.10:1883

### 4) Reliability (MUST)
- CNC reconnect loop:
  - exponential backoff + jitter
  - min ~0.5s, max ~30s
- MQTT reconnect loop:
  - retry forever
  - no crash loops
- Handle FOCAS return codes:
  - `0 = success`
  - any other code = log error and retry
- In production mode, failed reads must not crash service
- Must be systemd-ready (autostart on boot, restart on failure)


### 4) Reliability (MUST)
- CNC reconnect loop:
  - exponential backoff + jitter
  - min ~0.5s, max ~30s
- MQTT reconnect loop:
  - retry forever
  - no crash loops
- Handle FOCAS return codes:
  - `0 = success`
  - any other code = log error and retry
- In production mode, failed reads must not crash service
- Must be systemd-ready (autostart on boot, restart on failure)

### 5) Low latency goal (MUST)
This system triggers recording on another device, so keep end-to-end latency low:
- polling every 100ms by default (configurable per machine)
- fast publish path for tool change events
- keep per-poll logic lightweight (avoid heavy allocations)

### 6) Error handling and path isolation (MUST)
- If one path fails to read, continue monitoring other paths successfully
- Publish error event immediately when path read fails
- Include path status in heartbeat (ok/error with error message)
- Retry failed path reads continuously with exponential backoff
- Never stop the entire monitor due to single path failure

## Critical Legacy Behaviors to Preserve

### Dual-mode dev/prod pattern (REQUIRED)
Legacy code supports development without FANUC hardware.

New service MUST support:
- `env=development|production` (via config or env var)
- Development mode: run without FANUC library by using a FakeFanucClient simulator
- Production mode: real FANUC reads via FOCAS `.so` using ctypes


### FOCAS ctypes integration rules (REQUIRED)
- Use `ctypes` to load the FANUC FOCAS `.so` (default: `/usr/local/lib/libfwlib32.so`)
- Make library path configurable in config.yaml
- If FOCAS handle is not thread-safe, protect calls with a lock (use asyncio executor for blocking calls)
- Support path-based machines:
  - call `cnc_setpath(path)` before reading path-specific values
  - monitor multiple paths independently (paths 1 and 2)
- FOCAS read sequence per path:
  1. `cnc_setpath(path_number)`
  2. `cnc_rdmacro(libh, 4120, 10, &odbm)` - macro 4120 is same for all paths
  3. Convert macro to tool number using `Macro2Float()` then `int(round(value))`

### Macro variable conversion (REQUIRED)
Tool numbers stored in macro variable 4120 (same for all paths).

Use this conversion pattern from legacy focas.py:
```python
def Macro2Float(m):
    if m.dec_val:
        return (m.mcr_val * 1.0) / (10.0 ** m.dec_val)
    else:
        return m.mcr_val
```

Tool number policy:
 - convert macro to float using Macro2Float()
 - then convert to int: `int(round(value))`
 - macro_length parameter is always 10 (hardcoded, not configurable)


### Logging style (REQUIRED)
- INFO: connection events, tool changes
- DEBUG: poll reads (disabled by default)
- ERROR: FOCAS failures with return codes

Logs must include `machine_id` and `ip`.

## New Architecture (what to generate)

### Tech
- Python 3.11+
- asyncio-based
- MQTT: `asyncio-mqtt` preferred


### New folder layout (MUST generate)
Legacy stays untouched. Create a new `app/` package:

- `app/main.py` — entrypoint
- `app/config.py` — YAML parsing + validation + defaults
- `app/monitor.py` — MachineMonitor asyncio class (debounce + publish)
- `app/mqtt_pub.py` — MQTT wrapper (connect/reconnect/publish)
- `app/fanuc_client.py` — interface + dataclasses
- `app/fanuc_client_impl.py` — production FOCAS client via ctypes (reuse legacy reading knowledge)
- `app/fake_fanuc_client.py` — simulator for dev mode

Also generate:
- `config.yaml.example`
- `systemd/fanuc-monitor.service`
- `README.md`
- `requirements.txt` (or `pyproject.toml`)

### FanucClient interface (MUST)
Define a clean interface that supports either sync or async internally:

- `connect()`
- `disconnect()`
- `read_tool()` -> returns `int | None`
- `is_connected` property / state

If read calls are blocking, run them via an executor so the asyncio loop stays responsive.


## Tests (MUST)
Add pytest tests using the FakeFanucClient:

1) Tool change publishes exactly once per tool transition  
2) Debounce prevents duplicates on flicker/noise  
3) Reconnect loop continues after simulated failures  


## Config format (MUST)
Use YAML config structured like this:

```yaml
env: production  # or development

service:
  ip: "100.113.52.109"  # IP address of the machine running this service

focas:
  library_path: "/usr/local/lib/libfwlib32.so"
  macro_address: 4120  # Default for all machines (configurable globally)
  macro_length: 10     # Always 10, hardcoded in FOCAS calls

mqtt:
  host: 192.168.0.10
  port: 1883
  username: ""  # Anonymous access
  password: ""
  tls: false

monitoring:
  poll_interval_ms_default: 100
  debounce_consecutive_reads: 2
  heartbeat_interval_s: 2
  reconnect_min_delay_s: 0.5
  reconnect_max_delay_s: 30.0

machines:
  - machine_id: "lathe_03"
    ip: "10.151.32.81"
    port: 8193
    poll_interval_ms: 100  # Optional override
    monitored_paths:
      - path: 1
      - path: 2
  
  - machine_id: "mill_01"
    ip: "10.150.8.15"
    port: 8193
    monitored_paths:
      - path: 1  # Single-path machine
```

**Key notes:**
- service.ip is used in MQTT payload "source" field to identify which machine sent the message
- macro_address 4120 is the same for all paths (accessed via cnc_setpath)
- Use monitored_paths array format even for single-path machines
- Machine IDs use simple format: "lathe_03", "mill_01"

## Deployment requirements (MUST)

### Systemd service
Generate `systemd/fanuc-monitor.service` that:
- starts on boot (WantedBy=multi-user.target)
- restarts on failure (Restart=always)
- uses venv python interpreter
- logs to journald
- runs from project directory with proper WorkingDirectory
- Sets environment for config.yaml location

### Docker (future consideration)
- Skip Docker for initial implementation
- Focus on native Python + systemd deployment
- Docker support can be added later if needed

## Guardrails / Avoid these mistakes
- Don’t reuse legacy threads; new service must be asyncio-based
- Don't hardcode machine IPs or ports; everything in config.yaml
- Don't publish tool_change repeatedly (must be edge-triggered with debouncing)
- Don't block the asyncio loop with slow sync FOCAS calls (use executor)
- Don't crash on FOCAS return codes; log, publish error event, and retry with backoff
- Don't stop monitoring all paths when one path fails (isolate failures)
- Don't include sequence numbers in payloads (removed per user request)

## Deliverable output format (when writing code)
When generating code, output all files with clear separators:

- `# --- app/main.py ---`
- `# --- app/config.py ---`
- etc.

The project MUST run in development mode with the FakeFanucClient even when FANUC libraries are not installed.


## Extra Notes (must respect)
- Legacy standalone scripts have already worked successfully against real hardware
- This is a new long-running Raspberry Pi 4 monitoring service
- MQTT is the distribution mechanism for tool change events to other devices (e.g. Raspberry Pi 5)
- Tool-change notification must be fast and reliable (QoS 1 + debouncing + sequence number)

## Quick sanity check on assumptions (important)
Before finalizing production FOCAS reads:
- Confirm which data source is truly “tool in spindle” for each machine (macro / PMC / parameter)
- Confirm whether machine uses multiple paths and which one contains the relevant tool value
- Confirm acceptable detection latency and choose poll interval accordingly
