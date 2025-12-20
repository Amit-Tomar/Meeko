#!/usr/bin/env python3
"""
Flask server for controlling a Raspberry Pi robot car with L298N motor driver.
"""

from flask import Flask, jsonify, request, render_template
import RPi.GPIO as GPIO
import time
import atexit
import logging
import os
from PIL import Image, ImageDraw, ImageFont
import board
import digitalio
from adafruit_rgb_display import st7789
import cv2
import threading

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Display Configuration
CS_PIN = digitalio.DigitalInOut(board.CE0)  # GPIO8
DC_PIN = digitalio.DigitalInOut(board.D25)  # GPIO25
RESET_PIN = digitalio.DigitalInOut(board.D24)  # GPIO24
BAUDRATE = 24000000

# Display dimensions
DISPLAY_WIDTH = 320
DISPLAY_HEIGHT = 240

# Initialize SPI and display
spi = board.SPI()
display = st7789.ST7789(
    spi,
    height=DISPLAY_WIDTH,
    width=DISPLAY_HEIGHT,
    y_offset=0,
    x_offset=0,
    cs=CS_PIN,
    dc=DC_PIN,
    rst=RESET_PIN,
    baudrate=BAUDRATE,
    rotation=90,
)

# Video playback control
video_stop_flag = False

# GPIO Pin Configuration for L298N Motor Driver

# Left wheels (IN1, IN2) - Swapped to correct orientation
LEFT_FORWARD = 26      # IN2 (Pin 37)
LEFT_BACKWARD = 16     # IN1 (Pin 36)

# Right wheels (IN3, IN4)
RIGHT_FORWARD = 19     # IN3 (Pin 35)
RIGHT_BACKWARD = 13    # IN4 (Pin 33)

# PWM Speed Control (ENA, ENB)
LEFT_ENABLE = 12       # ENA (Pin 32) Left motor speed control
RIGHT_ENABLE = 18      # ENB (Pin 12) Right motor speed control

# Note: Based on your wiring:
# - ENA (GPIO12) controls IN1/IN2 (Left motor: GPIO16/GPIO26)
# - ENB (GPIO18) controls IN3/IN4 (Right motor: GPIO19/GPIO13)

# PWM objects (initialized in setup_gpio)
left_pwm = None
right_pwm = None

# Current speed (0-100)
current_speed = 50  # Default to half speed

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
    
    # Initialize all direction pins to LOW first
    stop_all_motors()
    
    # Set enable pins HIGH to provide full power (jumpers removed)
    # This ensures motors get constant power like when jumpers were on
    GPIO.output(LEFT_ENABLE, GPIO.HIGH)
    GPIO.output(RIGHT_ENABLE, GPIO.HIGH)
    
    # Initialize PWM at 1000Hz frequency
    left_pwm = GPIO.PWM(LEFT_ENABLE, 1000)
    right_pwm = GPIO.PWM(RIGHT_ENABLE, 1000)
    
    # Start PWM at 100% duty cycle (full power, like jumpers were on)
    left_pwm.start(100)
    right_pwm.start(100)

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

# ============================================================================
# Display Functions
# ============================================================================

def clear_display(color=(0, 0, 0)):
    """Clear display with specified color."""
    image = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), color)
    display.image(image)

def display_text_centered(text, color=(255, 255, 255), size=35, bg_color=(0, 0, 0)):
    """Display text centered on screen after clearing."""
    # Clear the display
    image = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), bg_color)
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        font = ImageFont.load_default()
    
    # Get text bounding box to center it
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Calculate centered position
    x = (DISPLAY_WIDTH - text_width) // 2
    y = (DISPLAY_HEIGHT - text_height) // 2
    
    draw.text((x, y), text, font=font, fill=color)
    display.image(image)

def play_video_on_display(video_path):
    """Play video file on the TFT display."""
    global video_stop_flag
    
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return False
    
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            logger.error(f"Could not open video: {video_path}")
            return False
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30
        frame_delay = 1.0 / fps
        
        logger.info(f"Playing video: {video_path} at {fps} fps")
        
        while cap.isOpened() and not video_stop_flag:
            ret, frame = cap.read()
            
            if not ret:
                # End of video, loop back to start
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            
            # Resize frame to display dimensions
            frame_resized = cv2.resize(frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
            
            # Convert BGR to RGB for PIL
            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            
            # Invert the colors (255 - pixel_value for each channel)
            frame_inverted = 255 - frame_rgb
            
            # Convert to PIL Image and display
            image = Image.fromarray(frame_inverted, mode='RGB')
            display.image(image)
            
            time.sleep(frame_delay)
        
        cap.release()
        video_stop_flag = False
        logger.info("Video playback stopped")
        return True
        
    except Exception as e:
        logger.error(f"Error playing video: {str(e)}")
        video_stop_flag = False
        return False

def play_gif_on_display(gif_path):
    """Play GIF file on the TFT display in a loop."""
    global video_stop_flag
    
    if not os.path.exists(gif_path):
        logger.error(f"GIF file not found: {gif_path}")
        return False
    


    try:
        gif = Image.open(gif_path)
        
        # Get number of frames
        try:
            frame_count = gif.n_frames
        except AttributeError:
            frame_count = 1
        
        logger.info(f"Playing GIF: {gif_path} with {frame_count} frames")
        
        while not video_stop_flag:
            for frame_num in range(frame_count):
                if video_stop_flag:
                    break
                
                gif.seek(frame_num)
                frame = gif.convert('RGB')
                
                # Resize to display dimensions
                frame_resized = frame.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.NEAREST)
                
                # Display the frame
                display.image(frame_resized)
                
                # Get frame duration (in milliseconds), default to 100ms
                try:
                    duration = gif.info.get('duration', 100) / 1000.0
                except:
                    duration = 0.1
                
                time.sleep(duration)
        
        video_stop_flag = False
        logger.info("GIF playback stopped")
        return True
        
    except Exception as e:
        logger.error(f"Error playing GIF: {str(e)}")
        video_stop_flag = False
        return False

# ============================================================================
# Flask Routes - Car Control
# ============================================================================

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
            '/speed/right': 'Set right motor speed (POST with JSON: {"speed": 0-100})',
            '/display/text': 'Display text centered (POST with JSON: {"text": "...", "color": [R,G,B], "size": 24, "bg_color": [R,G,B]})',
            '/display/video': 'Play video (POST with JSON: {"path": "/path/to/video.mp4"})',
            '/display/gif': 'Play GIF animation (POST with JSON: {"path": "/path/to/animation.gif"})',
            '/display/video/stop': 'Stop video playback',
            '/display/clear': 'Clear display to black'
        }
    })

@app.route('/forward', methods=['POST', 'GET'])
def move_forward():
    """Move the car forward."""
    try:
        logger.info("Command: FORWARD - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        # Left wheels backward, right wheels forward
        GPIO.output(LEFT_BACKWARD, GPIO.HIGH)
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
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        # Left wheels forward, right wheels backward
        GPIO.output(LEFT_FORWARD, GPIO.HIGH)
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
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        GPIO.output(LEFT_FORWARD, GPIO.HIGH)
        GPIO.output(RIGHT_FORWARD, GPIO.HIGH)
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
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        GPIO.output(LEFT_BACKWARD, GPIO.HIGH)
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
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

# ============================================================================
# Flask Routes - Display Control
# ============================================================================

@app.route('/display/text', methods=['POST'])
def display_text():
    """Display text centered on screen.
    
    Expects JSON: {
        "text": "Hello World",
        "color": [255, 255, 255],  # Optional, default white
        "size": 24,  # Optional, default 24
        "bg_color": [0, 0, 0]  # Optional, default black
    }
    """
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'status': 'error', 'message': 'Missing text parameter'}), 400
        
        text = data['text']
        color = tuple(data.get('color', [255, 255, 255]))
        size = int(data.get('size', 35))
        bg_color = tuple(data.get('bg_color', [0, 0, 0]))
        
        logger.info(f"Displaying text: {text}")
        display_text_centered(text, color=color, size=size, bg_color=bg_color)
        
        return jsonify({'status': 'success', 'action': 'text displayed', 'text': text})
    except Exception as e:
        logger.error("Error displaying text: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/display/video', methods=['POST'])
def play_video():
    """Play video file on display.
    
    Expects JSON: {
        "path": "/path/to/video.mp4"
    }
    """
    global video_stop_flag
    try:
        data = request.get_json()
        if not data or 'path' not in data:
            return jsonify({'status': 'error', 'message': 'Missing path parameter'}), 400
        
        video_path = data['path']
        
        if not os.path.exists(video_path):
            return jsonify({'status': 'error', 'message': f'Video file not found: {video_path}'}), 404
        
        # Stop any currently playing video
        video_stop_flag = True
        time.sleep(0.1)
        
        # Reset flag before starting new video
        video_stop_flag = False
        
        # Start video playback in a separate thread
        video_thread = threading.Thread(target=play_video_on_display, args=(video_path,))
        video_thread.daemon = True
        video_thread.start()
        
        logger.info(f"Started video playback: {video_path}")
        return jsonify({'status': 'success', 'action': 'video playing', 'path': video_path})
    except Exception as e:
        logger.error("Error playing video: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/display/video/stop', methods=['POST', 'GET'])
def stop_video():
    """Stop video playback."""
    global video_stop_flag
    try:
        video_stop_flag = True
        logger.info("Video playback stop requested")
        return jsonify({'status': 'success', 'action': 'video stopped'})
    except Exception as e:
        logger.error("Error stopping video: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/display/gif', methods=['POST'])
def play_gif():
    """Play GIF file on display.
    
    Expects JSON: {
        "path": "/path/to/animation.gif"
    }
    """
    global video_stop_flag
    try:
        data = request.get_json()
        if not data or 'path' not in data:
            return jsonify({'status': 'error', 'message': 'Missing path parameter'}), 400
        
        gif_path = data['path']
        
        if not os.path.exists(gif_path):
            return jsonify({'status': 'error', 'message': f'GIF file not found: {gif_path}'}), 404
        
        # Stop any currently playing video/gif
        video_stop_flag = True
        time.sleep(0.1)
        
        # Reset flag before starting new gif
        video_stop_flag = False
        
        # Start GIF playback in a separate thread
        gif_thread = threading.Thread(target=play_gif_on_display, args=(gif_path,))
        gif_thread.daemon = True
        gif_thread.start()
        
        logger.info(f"Started GIF playback: {gif_path}")
        return jsonify({'status': 'success', 'action': 'gif playing', 'path': gif_path})
    except Exception as e:
        logger.error("Error playing GIF: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/display/clear', methods=['POST', 'GET'])
def clear_screen():
    """Clear the display to black."""
    try:
        clear_display((0, 0, 0))
        logger.info("Display cleared")
        return jsonify({'status': 'success', 'action': 'display cleared'})
    except Exception as e:
        logger.error("Error clearing display: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("Raspberry Pi Car Controller Starting...")
    logger.info("=" * 50)
    setup_gpio()
    logger.info("GPIO initialized successfully")
    logger.info("Server running on http://0.0.0.0:5000")
    logger.info("Access controller UI from mobile browser")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=True)
