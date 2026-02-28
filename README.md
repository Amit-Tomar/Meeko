# Raspberry Pi Robot Car Controller

A Flask-based REST API server for controlling a 4-wheel robot car on Raspberry Pi using the L298N motor driver.

## Hardware Configuration

### L298N Motor Driver Connections
- **Left wheels** (Motor A):
  - IN1: GPIO 23 (forward)
  - IN2: GPIO 24 (backward)
  - ENA: GPIO 5 (PWM speed control)

- **Right wheels** (Motor B):
  - IN3: GPIO 22 (forward)
  - IN4: GPIO 27 (backward)
  - ENB: GPIO 6 (PWM speed control)

### Setup Notes
- Remove jumpers from ENA and ENB pins on L298N when using speed control
- Keep jumpers on for full-speed operation (GPIO 5 and 6 not needed)

## Requirements

- Raspberry Pi (any model with GPIO)
- Python 3.8+
- UV package manager

## Installation

1. Install UV (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Install dependencies:
```bash
uv sync
```

## Running the Server

Start the Flask server:
```bash
uv run python server.py
```

The server will run on `http://0.0.0.0:5000`

## API Endpoints

All endpoints accept both GET and POST requests.

### Get API Information
```bash
GET /
```

### Move Forward
```bash
POST /forward
curl -X POST http://localhost:5000/forward
```

### Move Backward
```bash
POST /backward
curl -X POST http://localhost:5000/backward
```

### Rotate Clockwise (at center)
```bash
POST /rotate/clockwise
curl -X POST http://localhost:5000/rotate/clockwise
```

### Rotate Anticlockwise (at center)
```bash
POST /rotate/anticlockwise
curl -X POST http://localhost:5000/rotate/anticlockwise
```

### Stop All Motors
```bash
POST /stop
curl -X POST http://localhost:5000/stop
```

### Set Speed (Both Motors)
Set speed from 0-100% for both motors:
```bash
POST /speed/set
curl -X POST http://localhost:5000/speed/set \
  -H "Content-Type: application/json" \
  -d '{"speed": 75}'
```

### Get Current Speed
```bash
GET /speed/get
curl http://localhost:5000/speed/get
```

### Set Left Motor Speed
Set speed from 0-100% for left motor only:
```bash
POST /speed/left
curl -X POST http://localhost:5000/speed/left \
  -H "Content-Type: application/json" \
  -d '{"speed": 60}'
```

### Set Right Motor Speed
Set speed from 0-100% for right motor only:
```bash
POST /speed/right
curl -X POST http://localhost:5000/speed/right \
  -H "Content-Type: application/json" \
  -d '{"speed": 80}'
```

## Response Format

All endpoints return JSON responses:

**Success:**
```json
{
  "status": "success",
  "action": "moving forward"
}
```

**Error:**
```json
{
  "status": "error",
  "message": "Error description"
}
```

## Notes

- The server automatically stops all motors when shut down
- GPIO pins are cleaned up on exit
- The server listens on all network interfaces (0.0.0.0) for remote access
- Motors continue running until a stop command or different movement command is issued
- Default speed is 100% (full speed)
- PWM frequency is set to 1000Hz for smooth motor control
- Individual motor speed control allows for advanced maneuvers and drift correction

## Safety

Remember to call the `/stop` endpoint to stop the motors when done!

## Integrating voice assistant

When we try to connect to Home assistant over secured networks, certain ports/ip might be blocked. To manage this we use : 

SSH Tunnel - Detailed Explanation

The idea is to create a secure tunnel that makes Home Assistant (running on Windows) appear as if it's running locally on the Raspberry Pi.

### How It Works

```
┌─────────────────────┐                    ┌─────────────────────┐
│   Raspberry Pi      │                    │   Windows Laptop    │
│                     │                    │                     │
│  linux-voice-       │                    │  Docker             │
│  assistant          │                    │    └─ Home Assistant│
│       │             │                    │         (port 8123) │
│       ▼             │                    │              ▲       │
│  localhost:8123 ────┼── SSH Tunnel ──────┼──────────────┘       │
│                     │  (encrypted)       │                     │
└─────────────────────┘                    └─────────────────────┘
```

When the voice assistant tries to fetch `http://localhost:8123/api/tts_proxy/...`, the SSH tunnel forwards that request through to your Windows machine's port 8123.

### Step-by-Step Setup

#### Step 1: Ensure SSH Server is Running on Raspberry Pi

On your Raspberry Pi, check if SSH is enabled:
```bash
sudo systemctl status ssh
```

If not running:
```bash
sudo systemctl enable ssh
sudo systemctl start ssh
```

#### Step 2: Get Your Raspberry Pi's IP Address

On Raspberry Pi:
```bash
hostname -I
```

Note this IP (e.g., `192.168.1.XXX`).

#### Step 3: Create the Reverse Tunnel from Windows

On your **Windows machine** (Git Bash or PowerShell with OpenSSH), run:

```bash
ssh -R 8123:localhost:8123 gumpoo@192.168.1.XXX
```

Replace `192.168.1.XXX` with your Raspberry Pi's IP.

This command means:
- `-R 8123:localhost:8123` - "Listen on port 8123 on the remote machine (Pi), and forward connections to localhost:8123 on this machine (Windows)"
- `gumpoo@192.168.1.XXX` - Connect to the Pi as user gumpoo

**Keep this terminal window open** - the tunnel only works while this SSH session is active.

#### Step 4: Configure Home Assistant to Use Correct URLs

You need Home Assistant to generate TTS URLs that point to `localhost:8123` instead of `192.168.1.2:8123`.

Edit your Home Assistant configuration. On Windows, the file is at:
```
./volumes/home-assistant/configuration.yaml
```

Add or modify:
```yaml
homeassistant:
  internal_url: "http://localhost:8123"
  external_url: "http://localhost:8123"
```

Then restart Home Assistant:
```bash
docker restart home-assistant
```

#### Step 5: Test the Tunnel

With the SSH tunnel running, test from Raspberry Pi:
```bash
curl -I http://localhost:8123
```

You should get a response (not hang).

#### Step 6: Run linux-voice-assistant

The voice assistant should now work because TTS URLs will be `http://localhost:8123/api/tts_proxy/...` which the tunnel forwards to Windows.

### Making the Tunnel Persistent

The basic `ssh -R` command stops when you close the terminal. To make it persistent:

#### Option A: Use autossh (Recommended)

On Windows, install autossh (via MSYS2 or WSL), then:
```bash
autossh -M 0 -f -N -R 8123:localhost:8123 gumpoo@192.168.1.XXX
```

#### Option B: Create a Windows Scheduled Task

Create a batch script that runs at startup to establish the tunnel.

---

### Quick Test First

Before configuring everything, just test if the tunnel works:

1. **On Windows**, run: `ssh -R 8123:localhost:8123 gumpoo@<PI_IP>`
2. **On Raspberry Pi** (new terminal), run: `curl -I http://localhost:8123`


## Voice assistant sattellite

We use https://github.com/OHF-Voice/linux-voice-assistant for creating a satellite to interact with the Home Assistant pipeline.
