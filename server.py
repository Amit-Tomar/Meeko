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
import pyaudio
import numpy as np
from openwakeword.model import Model

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

# Wake word detection control
wakeword_stop_flag = False
wakeword_thread = None
wakeword_model = None
wakeword_detected_callback = None
last_detection_time = 0
DETECTION_COOLDOWN = 2.0  # seconds to wait before next detection

# Audio configuration for wake word detection
AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 1
AUDIO_RATE = 16000
AUDIO_CHUNK = 1280  # 80ms chunks at 16kHz

# GPIO Pin Configuration for L298N Motor Driver
#
# Left motor is physically reversed on the chassis, so IN2 drives it forward
# and IN1 drives it backward (opposite of what you'd expect).
#
# Verified by hardware test:
#   GPIO26 (IN2, phys pin 37) → left wheels FORWARD
#   GPIO16 (IN1, phys pin 36) → left wheels BACKWARD
#   GPIO19 (IN3, phys pin 35) → right wheels FORWARD
#   GPIO13 (IN4, phys pin 33) → right wheels BACKWARD

LEFT_FORWARD  = 26     # IN2 (Pin 37) – left wheels forward
LEFT_BACKWARD = 16     # IN1 (Pin 36) – left wheels backward

RIGHT_FORWARD  = 19    # IN3 (Pin 35) – right wheels forward
RIGHT_BACKWARD = 13    # IN4 (Pin 33) – right wheels backward

# PWM Speed Control (ENA, ENB)
LEFT_ENABLE  = 12      # ENA (Pin 32) – left motor speed control
RIGHT_ENABLE = 18      # ENB (Pin 12) – right motor speed control

# PWM objects (initialized in setup_gpio)
left_pwm = None
right_pwm = None

# Tracked duty cycles (RPi.GPIO doesn't expose these directly)
left_pwm_duty = 100
right_pwm_duty = 100

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
    global left_pwm_duty, right_pwm_duty
    left_pwm_duty = 100
    right_pwm_duty = 100

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
    stop_wakeword_detection()
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
# Wake Word Detection Functions
# ============================================================================

def initialize_wakeword_model():
    """Initialize the OpenWakeWord model with alexa model."""
    global wakeword_model
    try:
        logger.info("Initializing wake word model with 'alexa'...")
        
        # Use the pre-trained alexa model
        wakeword_model = Model(wakeword_models=["alexa"])
        
        logger.info(f"✓ Wake word model initialized: alexa")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing wake word model: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def wakeword_detection_loop(callback=None):
    """Main loop for wake word detection."""
    global wakeword_stop_flag, last_detection_time
    
    try:
        # Initialize PyAudio
        audio = pyaudio.PyAudio()
        
        # Open audio stream
        stream = audio.open(
            format=AUDIO_FORMAT,
            channels=AUDIO_CHANNELS,
            rate=AUDIO_RATE,
            input=True,
            frames_per_buffer=AUDIO_CHUNK
        )
        
        logger.info("Wake word detection started, listening...")
        
        while not wakeword_stop_flag:
            # Read audio chunk
            audio_data = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Run prediction
            prediction = wakeword_model.predict(audio_array)
            
            # Check all model predictions
            for mdl_name, score in prediction.items():
                if score > 0.5:  # Threshold for detection
                    current_time = time.time()
                    
                    # Check if cooldown period has passed
                    if current_time - last_detection_time >= DETECTION_COOLDOWN:
                        logger.info(f"Wake word detected! Model: {mdl_name}, Score: {score:.3f}")
                        last_detection_time = current_time
                        
                        # Call callback if provided
                        if callback:
                            callback(mdl_name, score)
                        
                        # Display notification on screen
                        display_text_centered("Alexa!", color=(0, 255, 0), size=50)
                        time.sleep(1)
                        clear_display()
        
        # Cleanup
        stream.stop_stream()
        stream.close()
        audio.terminate()
        
        logger.info("Wake word detection stopped")
        
    except Exception as e:
        logger.error(f"Error in wake word detection: {str(e)}")
        wakeword_stop_flag = False

def start_wakeword_detection(callback=None):
    """Start wake word detection in a separate thread."""
    global wakeword_thread, wakeword_stop_flag, wakeword_detected_callback
    
    # Stop any existing detection
    stop_wakeword_detection()
    
    # Initialize model if not already done
    if wakeword_model is None:
        if not initialize_wakeword_model():
            return False
    
    # Reset stop flag
    wakeword_stop_flag = False
    wakeword_detected_callback = callback
    
    # Start detection thread
    wakeword_thread = threading.Thread(
        target=wakeword_detection_loop,
        args=(callback,)
    )
    wakeword_thread.daemon = True
    wakeword_thread.start()
    
    logger.info("Wake word detection thread started")
    return True

def stop_wakeword_detection():
    """Stop wake word detection."""
    global wakeword_stop_flag, wakeword_thread
    
    if wakeword_thread and wakeword_thread.is_alive():
        wakeword_stop_flag = True
        wakeword_thread.join(timeout=2.0)
        logger.info("Wake word detection stopped")

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
            '/display/clear': 'Clear display to black',
            '/wakeword/start': 'Start wake word detection',
            '/wakeword/stop': 'Stop wake word detection',
            '/wakeword/status': 'Get wake word detection status',
            '/debug/pins': 'Show live state of all GPIO pins with wiring details',
            '/debug/motor/left': 'Drive left motor only (GET/POST, optional ?direction=forward|backward, default forward)',
            '/debug/motor/right': 'Drive right motor only (GET/POST, optional ?direction=forward|backward, default forward)',
            '/debug/motor/raw': 'Bypass PWM, drive one side with plain GPIO.output and read pins back (GET, ?side=left|right|both, ?direction=forward|backward)'
        }
    })

@app.route('/forward', methods=['POST', 'GET'])
def move_forward():
    """Move the car forward."""
    try:
        logger.info("Command: FORWARD - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        GPIO.output(LEFT_FORWARD,  GPIO.HIGH)   # GPIO26 IN2 phys37
        GPIO.output(RIGHT_FORWARD, GPIO.HIGH)   # GPIO19 IN3 phys35
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
        GPIO.output(LEFT_BACKWARD,  GPIO.HIGH)  # GPIO16 IN1 phys36
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)  # GPIO13 IN4 phys33
        return jsonify({'status': 'success', 'action': 'moving backward'})
    except Exception as e:
        logger.error("Error moving backward: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/rotate/clockwise', methods=['POST', 'GET'])
def rotate_clockwise():
    """Rotate the car clockwise at its center (left forward, right backward)."""
    try:
        logger.info("Command: ROTATE CLOCKWISE - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        GPIO.output(LEFT_FORWARD,   GPIO.HIGH)  # GPIO26 IN2 phys37
        GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)  # GPIO13 IN4 phys33
        return jsonify({'status': 'success', 'action': 'rotating clockwise'})
    except Exception as e:
        logger.error("Error rotating clockwise: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/rotate/anticlockwise', methods=['POST', 'GET'])
def rotate_anticlockwise():
    """Rotate the car anticlockwise at its center (left backward, right forward)."""
    try:
        logger.info("Command: ROTATE ANTICLOCKWISE - Speed: %d%%", current_speed)
        stop_all_motors()
        time.sleep(0.01)  # Brief delay to ensure motors are stopped
        GPIO.output(LEFT_BACKWARD,  GPIO.HIGH)  # GPIO16 IN1 phys36
        GPIO.output(RIGHT_FORWARD,  GPIO.HIGH)  # GPIO19 IN3 phys35
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
        
        global left_pwm_duty, right_pwm_duty
        logger.info("Speed changed: %d%% -> %d%%", current_speed, speed)
        current_speed = speed
        left_pwm.ChangeDutyCycle(speed)
        right_pwm.ChangeDutyCycle(speed)
        left_pwm_duty = speed
        right_pwm_duty = speed
        
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

# ============================================================================
# Flask Routes - Wake Word Detection
# ============================================================================

@app.route('/wakeword/start', methods=['POST', 'GET'])
def start_wakeword():
    """Start wake word detection."""
    try:
        if start_wakeword_detection():
            return jsonify({'status': 'success', 'action': 'wake word detection started'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to start wake word detection'}), 500
    except Exception as e:
        logger.error("Error starting wake word detection: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/wakeword/stop', methods=['POST', 'GET'])
def stop_wakeword():
    """Stop wake word detection."""
    try:
        stop_wakeword_detection()
        return jsonify({'status': 'success', 'action': 'wake word detection stopped'})
    except Exception as e:
        logger.error("Error stopping wake word detection: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/wakeword/status', methods=['GET'])
def wakeword_status():
    """Get wake word detection status."""
    try:
        is_active = wakeword_thread is not None and wakeword_thread.is_alive()
        model_loaded = wakeword_model is not None
        return jsonify({
            'status': 'success',
            'active': is_active,
            'model_loaded': model_loaded
        })
    except Exception as e:
        logger.error("Error getting wake word status: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/debug/pins', methods=['GET'])
def debug_pins():
    """Return the live state of every motor/display GPIO pin with wiring details.

    Useful for troubleshooting after a pin-extender installation – check that
    the expected side of the L298N is actually being driven HIGH.
    """
    try:
        # ------------------------------------------------------------------ #
        # Pin catalogue: (bcm_gpio, physical_pin, role, connected_to)         #
        # Based on pinConnections.txt                                          #
        # ------------------------------------------------------------------ #
        pin_catalogue = [
            # Motor direction pins
            (LEFT_FORWARD,   37, 'LEFT_FORWARD  (IN2)',  'L298N IN2  – left wheels forward'),
            (LEFT_BACKWARD,  36, 'LEFT_BACKWARD (IN1)',  'L298N IN1  – left wheels backward'),
            (RIGHT_FORWARD,  35, 'RIGHT_FORWARD (IN3)',  'L298N IN3  – right wheels forward'),
            (RIGHT_BACKWARD, 33, 'RIGHT_BACKWARD(IN4)',  'L298N IN4  – right wheels backward'),
            # Enable / PWM pins
            (LEFT_ENABLE,    32, 'LEFT_ENABLE   (ENA)',  'L298N ENA  – left motor PWM speed (Blue wire, Pin 32)'),
            (RIGHT_ENABLE,   12, 'RIGHT_ENABLE  (ENB)',  'L298N ENB  – right motor PWM speed (Brown wire, Pin 12)'),
            # TFT display pins (GPIO10/11 are SPI hardware-managed – not readable via GPIO.input)
            (8,              24, 'TFT_CS',               'ST7789 CS  (Green wire → CE0, Pin 24)'),
            (25,             22, 'TFT_DC',               'ST7789 D/C (Purple wire, Pin 22)'),
            (24,             18, 'TFT_RESET',            'ST7789 RST (Blue wire, Pin 18)'),
            (10,             19, 'TFT_MOSI',             'ST7789 MOSI (Grey wire, Pin 19) – SPI hardware'),
            (11,             23, 'TFT_SCK',              'ST7789 SCK  (White wire, Pin 23) – SPI hardware'),
        ]

        # Pins controlled by the SPI hardware peripheral – cannot be read via GPIO.input
        SPI_HW_PINS = {10, 11}

        pin_states = []
        warnings = []

        for bcm, phys, role, wiring in pin_catalogue:
            if bcm in SPI_HW_PINS:
                state_label = 'SPI_HARDWARE_MANAGED'
                state = None
            else:
                try:
                    state = GPIO.input(bcm)
                    state_label = 'HIGH' if state == GPIO.HIGH else 'LOW'
                except Exception as read_err:
                    state_label = f'READ_ERROR ({read_err})'
                    state = None

            entry = {
                'bcm_gpio':      bcm,
                'physical_pin':  phys,
                'role':          role,
                'connected_to':  wiring,
                'state':         state_label,
            }

            # Attach PWM duty cycle for enable pins (tracked manually)
            if bcm == LEFT_ENABLE:
                entry['pwm_duty_cycle'] = left_pwm_duty if left_pwm is not None else 'pwm_not_started'
            elif bcm == RIGHT_ENABLE:
                entry['pwm_duty_cycle'] = right_pwm_duty if right_pwm is not None else 'pwm_not_started'

            pin_states.append(entry)

        # ------------------------------------------------------------------ #
        # Sanity checks – highlight likely wiring problems                    #
        # ------------------------------------------------------------------ #
        enable_states = {p['role']: p['state'] for p in pin_states if 'ENABLE' in p['role']}
        for role, state in enable_states.items():
            if state != 'HIGH':
                warnings.append(
                    f'{role} is {state} – motor on this side will not move. '
                    'Check ENA/ENB jumper or pin-extender wiring.'
                )

        # Check that at most one direction pin per side is HIGH at a time
        left_pins  = [p for p in pin_states if 'LEFT_FORWARD' in p['role'] or 'LEFT_BACKWARD' in p['role']]
        right_pins = [p for p in pin_states if 'RIGHT_FORWARD' in p['role'] or 'RIGHT_BACKWARD' in p['role']]
        for side_label, side_pins in [('LEFT', left_pins), ('RIGHT', right_pins)]:
            high_count = sum(1 for p in side_pins if p['state'] == 'HIGH')
            if high_count > 1:
                warnings.append(
                    f'{side_label} motor has both IN pins HIGH simultaneously – '
                    'this will cause a shoot-through condition on the L298N.'
                )

        logger.info("Debug /debug/pins requested – %d pins reported, %d warnings",
                    len(pin_states), len(warnings))

        return jsonify({
            'status':   'success',
            'gpio_mode': 'BCM',
            'current_speed_pct': current_speed,
            'pin_config': {
                'LEFT_FORWARD_BCM':   LEFT_FORWARD,
                'LEFT_BACKWARD_BCM':  LEFT_BACKWARD,
                'RIGHT_FORWARD_BCM':  RIGHT_FORWARD,
                'RIGHT_BACKWARD_BCM': RIGHT_BACKWARD,
                'LEFT_ENABLE_BCM':    LEFT_ENABLE,
                'RIGHT_ENABLE_BCM':   RIGHT_ENABLE,
            },
            'pins':     pin_states,
            'warnings': warnings,
        })

    except Exception as e:
        logger.error("Error in /debug/pins: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/debug/motor/left', methods=['GET', 'POST'])
def debug_motor_left():
    """Drive ONLY the left motor for 1 second then stop.

    Use this to confirm the left side responds independently of the right.
    Optional query param: ?direction=forward (default) or ?direction=backward
    """
    try:
        direction = request.args.get('direction', 'forward').lower()
        stop_all_motors()
        time.sleep(0.05)

        if direction == 'backward':
            GPIO.output(LEFT_BACKWARD, GPIO.HIGH)
            pin_driven_name = f'LEFT_BACKWARD (GPIO{LEFT_BACKWARD}, phys36)'
        else:
            GPIO.output(LEFT_FORWARD, GPIO.HIGH)
            pin_driven_name = f'LEFT_FORWARD (GPIO{LEFT_FORWARD}, phys37)'

        logger.info("DEBUG: Left motor only – direction=%s, pin=%s HIGH for 1s", direction, pin_driven_name)
        time.sleep(1)
        stop_all_motors()

        return jsonify({
            'status':       'success',
            'motor':        'left',
            'direction':    direction,
            'pin_driven':   pin_driven_name,
            'enable_pin':   f'LEFT_ENABLE (GPIO{LEFT_ENABLE}) – ENA on L298N',
            'note':         'Motor ran for 1 second then stopped. If it did not move, check ENA wire from pin extender to L298N.'
        })
    except Exception as e:
        logger.error("Error in /debug/motor/left: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/debug/motor/right', methods=['GET', 'POST'])
def debug_motor_right():
    """Drive ONLY the right motor for 1 second then stop.

    Use this to confirm the right side responds independently of the left.
    Optional query param: ?direction=forward (default) or ?direction=backward
    """
    try:
        direction = request.args.get('direction', 'forward').lower()
        stop_all_motors()
        time.sleep(0.05)

        if direction == 'backward':
            GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
            pin_driven_name = f'RIGHT_BACKWARD (GPIO{RIGHT_BACKWARD}, phys33)'
        else:
            GPIO.output(RIGHT_FORWARD, GPIO.HIGH)
            pin_driven_name = f'RIGHT_FORWARD (GPIO{RIGHT_FORWARD}, phys35)'

        logger.info("DEBUG: Right motor only – direction=%s, pin=%s HIGH for 1s", direction, pin_driven_name)
        time.sleep(1)
        stop_all_motors()

        return jsonify({
            'status':       'success',
            'motor':        'right',
            'direction':    direction,
            'pin_driven':   pin_driven_name,
            'enable_pin':   f'RIGHT_ENABLE (GPIO{RIGHT_ENABLE}) – ENB on L298N',
            'note':         'Motor ran for 1 second then stopped. If it did not move, check ENB wire from pin extender to L298N.'
        })
    except Exception as e:
        logger.error("Error in /debug/motor/right: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/debug/motor/raw', methods=['GET', 'POST'])
def debug_motor_raw():
    """Low-level motor test: bypass PWM, use plain GPIO.output on enable pins.

    This rules out PWM as the cause – if motors still don't move here the
    fault is in the physical wiring between pin extender and L298N.

    Query params:
      side      = left | right | both  (default: both)
      direction = forward | backward   (default: forward)
    """
    try:
        side      = request.args.get('side', 'both').lower()
        direction = request.args.get('direction', 'forward').lower()

        results = {}

        # ------------------------------------------------------------------ #
        # Step 1 – hard stop: direction pins LOW, PWM stopped, enable LOW     #
        # ------------------------------------------------------------------ #
        stop_all_motors()
        if left_pwm:
            left_pwm.stop()
        if right_pwm:
            right_pwm.stop()
        GPIO.output(LEFT_ENABLE, GPIO.LOW)
        GPIO.output(RIGHT_ENABLE, GPIO.LOW)
        time.sleep(0.1)

        results['step1_stop_readback'] = {
            'LEFT_ENABLE':   'HIGH' if GPIO.input(LEFT_ENABLE)   == GPIO.HIGH else 'LOW',
            'RIGHT_ENABLE':  'HIGH' if GPIO.input(RIGHT_ENABLE)  == GPIO.HIGH else 'LOW',
            'LEFT_FORWARD':  'HIGH' if GPIO.input(LEFT_FORWARD)  == GPIO.HIGH else 'LOW',
            'RIGHT_FORWARD': 'HIGH' if GPIO.input(RIGHT_FORWARD) == GPIO.HIGH else 'LOW',
        }

        # ------------------------------------------------------------------ #
        # Step 2 – raise only the requested enable pins via GPIO.output       #
        # ------------------------------------------------------------------ #
        drive_left  = side in ('left',  'both')
        drive_right = side in ('right', 'both')

        if drive_left:
            GPIO.output(LEFT_ENABLE, GPIO.HIGH)
        if drive_right:
            GPIO.output(RIGHT_ENABLE, GPIO.HIGH)
        time.sleep(0.05)

        # Resolve direction pins
        if direction == 'forward':
            if drive_left:
                GPIO.output(LEFT_FORWARD, GPIO.HIGH)
            if drive_right:
                GPIO.output(RIGHT_FORWARD, GPIO.HIGH)
            dir_pins = {'left':  f'LEFT_FORWARD  (GPIO{LEFT_FORWARD},  physical pin 37)',
                        'right': f'RIGHT_FORWARD (GPIO{RIGHT_FORWARD}, physical pin 35)'}
        else:
            if drive_left:
                GPIO.output(LEFT_BACKWARD, GPIO.HIGH)
            if drive_right:
                GPIO.output(RIGHT_BACKWARD, GPIO.HIGH)
            dir_pins = {'left':  f'LEFT_BACKWARD  (GPIO{LEFT_BACKWARD},  physical pin 36)',
                        'right': f'RIGHT_BACKWARD (GPIO{RIGHT_BACKWARD}, physical pin 33)'}

        # ------------------------------------------------------------------ #
        # Step 3 – read every motor pin back to confirm writes reached HW     #
        # ------------------------------------------------------------------ #
        readback = {
            f'LEFT_ENABLE   GPIO{LEFT_ENABLE}  phys32': 'HIGH' if GPIO.input(LEFT_ENABLE)   == GPIO.HIGH else 'LOW',
            f'RIGHT_ENABLE  GPIO{RIGHT_ENABLE} phys12': 'HIGH' if GPIO.input(RIGHT_ENABLE)  == GPIO.HIGH else 'LOW',
            f'LEFT_FORWARD  GPIO{LEFT_FORWARD}  phys37': 'HIGH' if GPIO.input(LEFT_FORWARD)  == GPIO.HIGH else 'LOW',
            f'LEFT_BACKWARD GPIO{LEFT_BACKWARD} phys36': 'HIGH' if GPIO.input(LEFT_BACKWARD) == GPIO.HIGH else 'LOW',
            f'RIGHT_FORWARD GPIO{RIGHT_FORWARD} phys35': 'HIGH' if GPIO.input(RIGHT_FORWARD) == GPIO.HIGH else 'LOW',
            f'RIGHT_BACKWARD GPIO{RIGHT_BACKWARD} phys33': 'HIGH' if GPIO.input(RIGHT_BACKWARD) == GPIO.HIGH else 'LOW',
        }
        results['step2_drive_readback'] = readback

        warnings = []
        actions  = []

        # ── Check 1: enable pins stayed HIGH after we drove them LOW ──────
        # This means an external source (L298N ENA/ENB jumpers still fitted)
        # is holding them HIGH, bypassing GPIO control entirely.
        left_en_stuck_high  = results['step1_stop_readback']['LEFT_ENABLE']  == 'HIGH'
        right_en_stuck_high = results['step1_stop_readback']['RIGHT_ENABLE'] == 'HIGH'

        if left_en_stuck_high:
            warnings.append(
                'LEFT_ENABLE (GPIO12, physical pin 32) read HIGH immediately after '
                'GPIO.output(LOW) was called. The ENA jumper on the L298N is almost '
                'certainly still fitted – it is hardwiring ENA to 5 V and ignoring '
                'the Pi. This is harmless for basic control but means the Pi has no '
                'speed control over the left motor.'
            )
        if right_en_stuck_high:
            warnings.append(
                'RIGHT_ENABLE (GPIO18, physical pin 12) read HIGH immediately after '
                'GPIO.output(LOW) was called. The ENB jumper on the L298N is almost '
                'certainly still fitted – same as above for the right motor.'
            )

        # ── Check 2: direction pin write failures ─────────────────────────
        left_dir_key  = (f'LEFT_FORWARD  GPIO{LEFT_FORWARD}  phys37'
                         if direction == 'forward'
                         else f'LEFT_BACKWARD GPIO{LEFT_BACKWARD} phys36')
        right_dir_key = (f'RIGHT_FORWARD GPIO{RIGHT_FORWARD} phys35'
                         if direction == 'forward'
                         else f'RIGHT_BACKWARD GPIO{RIGHT_BACKWARD} phys33')

        if drive_left and readback.get(left_dir_key) != 'HIGH':
            warnings.append(
                f'Left direction pin ({left_dir_key}) reads LOW after GPIO.output(HIGH). '
                'The Pi GPIO write is not reaching the output pad. '
                'Pin extender not fully seated or broken trace on that row.'
            )
        if drive_right and readback.get(right_dir_key) != 'HIGH':
            warnings.append(
                f'Right direction pin ({right_dir_key}) reads LOW after GPIO.output(HIGH). '
                'Same as above for the right side.'
            )

        # ── Check 3: all Pi readbacks correct but left motor still silent ─
        # (The pattern from the live data: left EN HIGH, left direction HIGH,
        #  right motor works, left motor silent → wire between extender and L298N)
        left_pi_looks_correct = (
            readback[f'LEFT_ENABLE   GPIO{LEFT_ENABLE}  phys32'] == 'HIGH' and
            readback.get(left_dir_key) == 'HIGH'
        )
        right_pi_looks_correct = (
            readback[f'RIGHT_ENABLE  GPIO{RIGHT_ENABLE} phys12'] == 'HIGH' and
            readback.get(right_dir_key) == 'HIGH'
        )

        if drive_left and left_pi_looks_correct:
            actions.append(
                'LEFT MOTOR – Pi GPIO is outputting correctly (all pins read back HIGH). '
                'The fault is DOWNSTREAM of the Pi, between the pin extender output '
                'and the L298N screw terminals. Check these wires physically:\n'
                '  1. Physical pin 37 → L298N IN2  (GPIO26, Yellow wire) – left forward\n'
                '  2. Physical pin 36 → L298N IN1  (GPIO16, Green wire)  – left backward\n'
                '  3. Physical pin 32 → L298N ENA  (GPIO12, Blue wire)   – only if ENA jumper removed\n'
                'With a pin extender, pins 36/37 are the most common to pop loose. '
                'Press each wire firmly into its terminal and re-test.'
            )
        if drive_right and right_pi_looks_correct:
            actions.append(
                'RIGHT MOTOR – Pi GPIO is outputting correctly. If the right motor '
                'moved during this test, the right side wiring is good.'
            )

        logger.info("DEBUG raw motor: side=%s direction=%s warnings=%d actions=%d",
                    side, direction, len(warnings), len(actions))

        # ------------------------------------------------------------------ #
        # Step 4 – hold for 2 seconds so movement is clearly visible         #
        # ------------------------------------------------------------------ #
        time.sleep(2)
        stop_all_motors()

        # Restart PWM on enable pins
        left_pwm.start(left_pwm_duty)
        right_pwm.start(right_pwm_duty)

        return jsonify({
            'status':           'success',
            'side_tested':      side,
            'direction':        direction,
            'direction_pins':   dir_pins,
            'pwm_bypassed':     True,
            'held_for_seconds': 2,
            'diagnostics':      results,
            'warnings':         warnings,
            'actions':          actions,
        })

    except Exception as e:
        # Best-effort PWM restore
        try:
            stop_all_motors()
            left_pwm.start(left_pwm_duty)
            right_pwm.start(right_pwm_duty)
        except Exception:
            pass
        logger.error("Error in /debug/motor/raw: %s", str(e))
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
