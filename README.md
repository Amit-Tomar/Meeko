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
