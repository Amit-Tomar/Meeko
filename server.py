#!/usr/bin/env python3
"""
Flask server for controlling a Raspberry Pi robot car with L298N motor driver.
"""

from flask import Flask, jsonify, request, render_template
import RPi.GPIO as GPIO
import time
import atexit
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# GPIO Pin Configuration for L298N Motor Driver
# Left wheels (IN1, IN2)
LEFT_FORWARD = 23
LEFT_BACKWARD = 24

# Right wheels (IN3, IN4)
RIGHT_FORWARD = 22
RIGHT_BACKWARD = 27

# PWM Speed Control (ENA, ENB)
LEFT_ENABLE = 5   # ENA - Left motor speed control
RIGHT_ENABLE = 6  # ENB - Right motor speed control

# PWM objects (initialized in setup_gpio)
left_pwm = None
right_pwm = None

# Current speed (0-100)
current_speed = 100  # Default to full speed

def setup_gpio():
    """Initialize GPIO pins for motor control."""
    global left_pwm, right_pwm
    
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    # Setup direction pins as output
    GPIO.setup(LEFT_FORWARD, GPIO.OUT)
    GPIO.setup(LEFT_BACKWARD, GPIO.OUT)
    GPIO.setup(RIGHT_FORWARD, GPIO.OUT)
    GPIO.setup(RIGHT_BACKWARD, GPIO.OUT)
    
    # Setup PWM pins for speed control
    GPIO.setup(LEFT_ENABLE, GPIO.OUT)
    GPIO.setup(RIGHT_ENABLE, GPIO.OUT)
    
    # Initialize PWM at 1000Hz frequency
    left_pwm = GPIO.PWM(LEFT_ENABLE, 1000)
    right_pwm = GPIO.PWM(RIGHT_ENABLE, 1000)
    
    # Start PWM with default speed (100%)
    left_pwm.start(current_speed)
    right_pwm.start(current_speed)
    
    # Initialize all direction pins to LOW
    stop_all_motors()

def stop_all_motors():
    """Stop all motors by setting all pins to LOW."""
    GPIO.output(LEFT_FORWARD, GPIO.LOW)
    GPIO.output(LEFT_BACKWARD, GPIO.LOW)
    GPIO.output(RIGHT_FORWARD, GPIO.LOW)
    GPIO.output(RIGHT_BACKWARD, GPIO.LOW)

def cleanup_gpio():
    """Cleanup GPIO on exit."""
    stop_all_motors()
    if left_pwm:
        left_pwm.stop()
    if right_pwm:
        right_pwm.stop()
    GPIO.cleanup()

# Register cleanup function
atexit.register(cleanup_gpio)

@app.route('/')
def index():
    """Serve the car controller HTML interface."""
    logger.info("Controller page accessed")
    return render_template('controller.html')

@app.route('/api')
def api_info():
    """API information endpoint."""
    return jsonify({
        'message': 'Raspberry Pi Car Control API with L298N Motor Driver',
        'current_speed': current_speed,
        'endpoints': {
            '/forward': 'Move forward',
            '/backward': 'Move backward',
            '/rotate/clockwise': 'Rotate clockwise at center',
            '/rotate/anticlockwise': 'Rotate anticlockwise at center',
            '/stop': 'Stop all motors',
            '/speed/set': 'Set speed (POST with JSON: {"speed": 0-100})',
            '/speed/get': 'Get current speed',
            '/speed/left': 'Set left motor speed (POST with JSON: {"speed": 0-100})',
            '/speed/right': 'Set right motor speed (POST with JSON: {"speed": 0-100})'
        }
    })

@app.route('/forward', methods=['POST', 'GET'])
def move_forward():
    """Move the car forward."""
    try:
        logger.info("Command: FORWARD - Speed: %d%%", current_speed)
        stop_all_motors()
        GPIO.output(LEFT_FORWARD, GPIO.HIGH)
        GPIO.output(RIGHT_FORWARD, GPIO.HIGH)
        return jsonify({'status': 'success', 'action': 'moving forward'})
    except Exception as e:
        logger.error("Error moving forward: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/backward', methods=['POST', 'GET'])
def move_backward():
    """Move the car backward."""
    try:
        logger.info("Command: BACKWARD - Speed: %d%%", current_speed)
        stop_all_motors()
        GPIO.output(LEFT_BACKWARD, GPIO.HIGH)
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
        return jsonify({'status': 'success', 'action': 'moving backward'})
    except Exception as e:
        logger.error("Error moving backward: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/rotate/clockwise', methods=['POST', 'GET'])
def rotate_clockwise():
    """Rotate the car clockwise at its center."""
    try:
        logger.info("Command: ROTATE CLOCKWISE - Speed: %d%%", current_speed)
        stop_all_motors()
        # Left wheels forward, right wheels backward
        GPIO.output(LEFT_FORWARD, GPIO.HIGH)
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
        return jsonify({'status': 'success', 'action': 'rotating clockwise'})
    except Exception as e:
        logger.error("Error rotating clockwise: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/rotate/anticlockwise', methods=['POST', 'GET'])
def rotate_anticlockwise():
    """Rotate the car anticlockwise at its center."""
    try:
        logger.info("Command: ROTATE ANTICLOCKWISE - Speed: %d%%", current_speed)
        stop_all_motors()
        # Left wheels backward, right wheels forward
        GPIO.output(LEFT_BACKWARD, GPIO.HIGH)
        GPIO.output(RIGHT_FORWARD, GPIO.HIGH)
        return jsonify({'status': 'success', 'action': 'rotating anticlockwise'})
    except Exception as e:
        logger.error("Error rotating anticlockwise: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop', methods=['POST', 'GET'])
def stop():
    """Stop all motors."""
    try:
        logger.info("Command: STOP")
        stop_all_motors()
        return jsonify({'status': 'success', 'action': 'stopped'})
    except Exception as e:
        logger.error("Error stopping: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/speed/set', methods=['POST'])
def set_speed():
    """Set speed for both motors (0-100)."""
    global current_speed
    try:
        data = request.get_json()
        if not data or 'speed' not in data:
            return jsonify({'status': 'error', 'message': 'Missing speed parameter'}), 400
        
        speed = int(data['speed'])
        if speed < 0 or speed > 100:
            return jsonify({'status': 'error', 'message': 'Speed must be between 0 and 100'}), 400
        
        logger.info("Speed changed: %d%% -> %d%%", current_speed, speed)
        current_speed = speed
        left_pwm.ChangeDutyCycle(speed)
        right_pwm.ChangeDutyCycle(speed)
        
        return jsonify({'status': 'success', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400
    except Exception as e:
        logger.error("Error setting speed: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/speed/get', methods=['GET'])
def get_speed():
    """Get current speed setting."""
    return jsonify({'status': 'success', 'speed': current_speed})

@app.route('/speed/left', methods=['POST'])
def set_left_speed():
    """Set speed for left motor only (0-100)."""
    try:
        data = request.get_json()
        if not data or 'speed' not in data:
            return jsonify({'status': 'error', 'message': 'Missing speed parameter'}), 400
        
        speed = int(data['speed'])
        if speed < 0 or speed > 100:
            return jsonify({'status': 'error', 'message': 'Speed must be between 0 and 100'}), 400
        
        logger.info("Left motor speed set: %d%%", speed)
        left_pwm.ChangeDutyCycle(speed)
        
        return jsonify({'status': 'success', 'motor': 'left', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400
    except Exception as e:
        logger.error("Error setting left speed: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/speed/right', methods=['POST'])
def set_right_speed():
    """Set speed for right motor only (0-100)."""
    try:
        data = request.get_json()
        if not data or 'speed' not in data:
            return jsonify({'status': 'error', 'message': 'Missing speed parameter'}), 400
        
        speed = int(data['speed'])
        if speed < 0 or speed > 100:
            return jsonify({'status': 'error', 'message': 'Speed must be between 0 and 100'}), 400
        
        logger.info("Right motor speed set: %d%%", speed)
        right_pwm.ChangeDutyCycle(speed)
        
        return jsonify({'status': 'success', 'motor': 'right', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400
    except Exception as e:
        logger.error("Error setting right speed: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("Raspberry Pi Car Controller Starting...")
    logger.info("=" * 50)
    setup_gpio()
    logger.info("GPIO initialized successfully")
    logger.info("Server running on http://0.0.0.0:5000")
    logger.info("Access controller UI from mobile browser")
    app.run(host='0.0.0.0', port=5000, debug=True)
