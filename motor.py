"""
Motor control module for the L298N motor driver on a Raspberry Pi robot car.

Pin layout (BCM numbering):
  Left motor is physically reversed on the chassis, so IN2 drives it forward
  and IN1 drives it backward (opposite of what you'd expect).

  GPIO26 (IN2, phys pin 37) → left wheels FORWARD
  GPIO16 (IN1, phys pin 36) → left wheels BACKWARD
  GPIO19 (IN3, phys pin 35) → right wheels FORWARD
  GPIO13 (IN4, phys pin 33) → right wheels BACKWARD
"""

import time
import logging
import RPi.GPIO as GPIO
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GPIO Pin Configuration for L298N Motor Driver
# ---------------------------------------------------------------------------

LEFT_FORWARD  = 26     # IN2 (Pin 37) – left wheels forward
LEFT_BACKWARD = 16     # IN1 (Pin 36) – left wheels backward

RIGHT_FORWARD  = 19    # IN3 (Pin 35) – right wheels forward
RIGHT_BACKWARD = 13    # IN4 (Pin 33) – right wheels backward

# PWM Speed Control (ENA, ENB)
LEFT_ENABLE  = 12      # ENA (Pin 32) – left motor speed control
RIGHT_ENABLE = 18      # ENB (Pin 12) – right motor speed control

# PWM objects (initialised in setup_gpio)
left_pwm = None
right_pwm = None

# Tracked duty cycles (RPi.GPIO doesn't expose these directly)
left_pwm_duty  = 100
right_pwm_duty = 100

# Current speed (0-100)
current_speed = 50  # Default to half speed

# ---------------------------------------------------------------------------
# GPIO helpers
# ---------------------------------------------------------------------------

def setup_gpio():
    """Initialise GPIO pins for motor control."""
    global left_pwm, right_pwm

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Setup direction pins as output
    GPIO.setup(LEFT_FORWARD,  GPIO.OUT)
    GPIO.setup(LEFT_BACKWARD, GPIO.OUT)
    GPIO.setup(RIGHT_FORWARD, GPIO.OUT)
    GPIO.setup(RIGHT_BACKWARD, GPIO.OUT)

    # Setup PWM pins for speed control
    GPIO.setup(LEFT_ENABLE,  GPIO.OUT)
    GPIO.setup(RIGHT_ENABLE, GPIO.OUT)

    # Initialise all direction pins to LOW first
    stop_all_motors()

    # Set enable pins HIGH to provide full power (jumpers removed)
    GPIO.output(LEFT_ENABLE,  GPIO.HIGH)
    GPIO.output(RIGHT_ENABLE, GPIO.HIGH)

    # Initialise PWM at 1000 Hz frequency
    left_pwm  = GPIO.PWM(LEFT_ENABLE,  1000)
    right_pwm = GPIO.PWM(RIGHT_ENABLE, 1000)

    # Start PWM at 100 % duty cycle (full power, like jumpers were on)
    left_pwm.start(100)
    right_pwm.start(100)
    global left_pwm_duty, right_pwm_duty
    left_pwm_duty  = 100
    right_pwm_duty = 100


def stop_all_motors():
    """Stop all motors by setting all direction pins to LOW."""
    GPIO.output(LEFT_FORWARD,   GPIO.LOW)
    GPIO.output(LEFT_BACKWARD,  GPIO.LOW)
    GPIO.output(RIGHT_FORWARD,  GPIO.LOW)
    GPIO.output(RIGHT_BACKWARD, GPIO.LOW)


def cleanup_gpio():
    """Clean up GPIO on exit."""
    stop_all_motors()
    if left_pwm:
        left_pwm.stop()
    if right_pwm:
        right_pwm.stop()
    # Lazy import to avoid circular dependency with wakeword module
    from wakeword import stop_wakeword_detection
    stop_wakeword_detection()
    GPIO.cleanup()


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

motor_bp = Blueprint('motor', __name__)


@motor_bp.route('/forward', methods=['POST', 'GET'])
def move_forward():
    """Move the car forward."""
    try:
        logger.info("Command: FORWARD - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)
        GPIO.output(LEFT_FORWARD,  GPIO.HIGH)   # GPIO26 IN2 phys37
        GPIO.output(RIGHT_FORWARD, GPIO.HIGH)   # GPIO19 IN3 phys35
        return jsonify({'status': 'success', 'action': 'moving forward'})
    except Exception as e:
        logger.error("Error moving forward: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/backward', methods=['POST', 'GET'])
def move_backward():
    """Move the car backward."""
    try:
        logger.info("Command: BACKWARD - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)
        GPIO.output(LEFT_BACKWARD,  GPIO.HIGH)  # GPIO16 IN1 phys36
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)  # GPIO13 IN4 phys33
        return jsonify({'status': 'success', 'action': 'moving backward'})
    except Exception as e:
        logger.error("Error moving backward: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/rotate/clockwise', methods=['POST', 'GET'])
def rotate_clockwise():
    """Rotate the car clockwise at its centre (left forward, right backward)."""
    try:
        logger.info("Command: ROTATE CLOCKWISE - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)
        GPIO.output(LEFT_FORWARD,   GPIO.HIGH)  # GPIO26 IN2 phys37
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)  # GPIO13 IN4 phys33
        return jsonify({'status': 'success', 'action': 'rotating clockwise'})
    except Exception as e:
        logger.error("Error rotating clockwise: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/rotate/anticlockwise', methods=['POST', 'GET'])
def rotate_anticlockwise():
    """Rotate the car anticlockwise at its centre (left backward, right forward)."""
    try:
        logger.info("Command: ROTATE ANTICLOCKWISE - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)
        GPIO.output(LEFT_BACKWARD,  GPIO.HIGH)  # GPIO16 IN1 phys36
        GPIO.output(RIGHT_FORWARD,  GPIO.HIGH)  # GPIO19 IN3 phys35
        return jsonify({'status': 'success', 'action': 'rotating anticlockwise'})
    except Exception as e:
        logger.error("Error rotating anticlockwise: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/stop', methods=['POST', 'GET'])
def stop():
    """Stop all motors."""
    try:
        logger.info("Command: STOP")
        stop_all_motors()
        return jsonify({'status': 'success', 'action': 'stopped'})
    except Exception as e:
        logger.error("Error stopping: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/dance', methods=['POST', 'GET'])
def dance():
    """Dance sequence: rotate CW 2s, stop, rotate ACW 2s, stop, forward 2s, stop, backward 2s, stop."""
    try:
        logger.info("Command: DANCE")

        # Rotate clockwise for 2 seconds
        stop_all_motors()
        time.sleep(0.01)
        GPIO.output(LEFT_FORWARD,   GPIO.HIGH)
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
        time.sleep(2)

        # Stop
        stop_all_motors()
        time.sleep(0.5)

        # Rotate anticlockwise for 2 seconds
        GPIO.output(LEFT_BACKWARD,  GPIO.HIGH)
        GPIO.output(RIGHT_FORWARD,  GPIO.HIGH)
        time.sleep(2)

        # Stop
        stop_all_motors()
        time.sleep(0.5)

        # Move forward for 2 seconds
        GPIO.output(LEFT_FORWARD,  GPIO.HIGH)
        GPIO.output(RIGHT_FORWARD, GPIO.HIGH)
        time.sleep(2)

        # Stop
        stop_all_motors()
        time.sleep(0.5)

        # Move backward for 2 seconds
        GPIO.output(LEFT_BACKWARD,  GPIO.HIGH)
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
        time.sleep(2)

        # Final stop
        stop_all_motors()

        return jsonify({'status': 'success', 'action': 'dance complete'})
    except Exception as e:
        logger.error("Error during dance: %s", str(e))
        stop_all_motors()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/speed/set', methods=['POST'])
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

        global left_pwm_duty, right_pwm_duty
        logger.info("Speed changed: %d%% -> %d%%", current_speed, speed)
        current_speed = speed
        left_pwm.ChangeDutyCycle(speed)
        right_pwm.ChangeDutyCycle(speed)
        left_pwm_duty  = speed
        right_pwm_duty = speed

        return jsonify({'status': 'success', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400
    except Exception as e:
        logger.error("Error setting speed: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/speed/get', methods=['GET'])
def get_speed():
    """Get current speed setting."""
    return jsonify({'status': 'success', 'speed': current_speed})


@motor_bp.route('/speed/left', methods=['POST'])
def set_left_speed():
    """Set speed for the left motor only (0-100)."""
    try:
        data = request.get_json()
        if not data or 'speed' not in data:
            return jsonify({'status': 'error', 'message': 'Missing speed parameter'}), 400

        speed = int(data['speed'])
        if speed < 0 or speed > 100:
            return jsonify({'status': 'error', 'message': 'Speed must be between 0 and 100'}), 400

        global left_pwm_duty
        logger.info("Left motor speed set: %d%%", speed)
        left_pwm.ChangeDutyCycle(speed)
        left_pwm_duty = speed

        return jsonify({'status': 'success', 'motor': 'left', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400
    except Exception as e:
        logger.error("Error setting left speed: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@motor_bp.route('/speed/right', methods=['POST'])
def set_right_speed():
    """Set speed for the right motor only (0-100)."""
    try:
        data = request.get_json()
        if not data or 'speed' not in data:
            return jsonify({'status': 'error', 'message': 'Missing speed parameter'}), 400

        speed = int(data['speed'])
        if speed < 0 or speed > 100:
            return jsonify({'status': 'error', 'message': 'Speed must be between 0 and 100'}), 400

        global right_pwm_duty
        logger.info("Right motor speed set: %d%%", speed)
        right_pwm.ChangeDutyCycle(speed)
        right_pwm_duty = speed

        return jsonify({'status': 'success', 'motor': 'right', 'speed': speed})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid speed value'}), 400
    except Exception as e:
        logger.error("Error setting right speed: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500
