"""
Display control module for the ST7789 TFT screen attached to a Raspberry Pi.

Hardware wiring:
  CS    → GPIO8  (CE0, physical pin 24)
  DC    → GPIO25 (physical pin 22)
  RESET → GPIO24 (physical pin 18)
  MOSI  → GPIO10 (physical pin 19, SPI hardware)
  SCK   → GPIO11 (physical pin 23, SPI hardware)
"""

import os
import time
import threading
import logging

from PIL import Image, ImageDraw, ImageFont
import board
import digitalio
from adafruit_rgb_display import st7789
import cv2
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Display Configuration
# ---------------------------------------------------------------------------

CS_PIN    = digitalio.DigitalInOut(board.CE0)  # GPIO8
DC_PIN    = digitalio.DigitalInOut(board.D25)  # GPIO25
RESET_PIN = digitalio.DigitalInOut(board.D24)  # GPIO24
BAUDRATE  = 24000000

DISPLAY_WIDTH  = 320
DISPLAY_HEIGHT = 240

# Initialise SPI and display
spi     = board.SPI()
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

# Shared flag – set to True to stop any running video/GIF playback
video_stop_flag = False

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def clear_display(color=(0, 0, 0)):
    """Clear the display with the specified colour."""
    image = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), color)
    display.image(image)


def display_text_centered(text, color=(255, 255, 255), size=35, bg_color=(0, 0, 0)):
    """Render text centred on the display, replacing whatever is shown."""
    image = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), bg_color)
    draw  = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        font = ImageFont.load_default()

    bbox        = draw.textbbox((0, 0), text, font=font)
    text_width  = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (DISPLAY_WIDTH  - text_width)  // 2
    y = (DISPLAY_HEIGHT - text_height) // 2

    draw.text((x, y), text, font=font, fill=color)
    display.image(image)


def play_video_on_display(video_path):
    """Play a video file on the TFT display (loops until stopped)."""
    global video_stop_flag

    if not os.path.exists(video_path):
        logger.error("Video file not found: %s", video_path)
        return False

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error("Could not open video: %s", video_path)
            return False

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30
        frame_delay = 1.0 / fps

        logger.info("Playing video: %s at %.1f fps", video_path, fps)

        while cap.isOpened() and not video_stop_flag:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            frame_resized  = cv2.resize(frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
            frame_rgb      = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            frame_inverted = 255 - frame_rgb

            display.image(Image.fromarray(frame_inverted, mode='RGB'))
            time.sleep(frame_delay)

        cap.release()
        video_stop_flag = False
        logger.info("Video playback stopped")
        return True

    except Exception as e:
        logger.error("Error playing video: %s", str(e))
        video_stop_flag = False
        return False


def play_gif_on_display(gif_path):
    """Play a GIF file on the TFT display in a loop."""
    global video_stop_flag

    if not os.path.exists(gif_path):
        logger.error("GIF file not found: %s", gif_path)
        return False

    try:
        gif = Image.open(gif_path)

        try:
            frame_count = gif.n_frames
        except AttributeError:
            frame_count = 1

        logger.info("Playing GIF: %s with %d frames", gif_path, frame_count)

        while not video_stop_flag:
            for frame_num in range(frame_count):
                if video_stop_flag:
                    break

                gif.seek(frame_num)
                frame         = gif.convert('RGB')
                frame_resized = frame.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.NEAREST)
                display.image(frame_resized)

                try:
                    duration = gif.info.get('duration', 100) / 1000.0
                except Exception:
                    duration = 0.1

                time.sleep(duration)

        video_stop_flag = False
        logger.info("GIF playback stopped")
        return True

    except Exception as e:
        logger.error("Error playing GIF: %s", str(e))
        video_stop_flag = False
        return False


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

display_bp = Blueprint('display', __name__)


@display_bp.route('/display/text', methods=['POST'])
def display_text():
    """Display centred text on the screen.

    Expects JSON::

        {
            "text": "Hello World",
            "color": [255, 255, 255],   // optional, default white
            "size": 35,                 // optional, default 35
            "bg_color": [0, 0, 0]       // optional, default black
        }
    """
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'status': 'error', 'message': 'Missing text parameter'}), 400

        text     = data['text']
        color    = tuple(data.get('color',    [255, 255, 255]))
        size     = int(data.get('size', 35))
        bg_color = tuple(data.get('bg_color', [0, 0, 0]))

        logger.info("Displaying text: %s", text)
        display_text_centered(text, color=color, size=size, bg_color=bg_color)

        return jsonify({'status': 'success', 'action': 'text displayed', 'text': text})
    except Exception as e:
        logger.error("Error displaying text: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@display_bp.route('/display/video', methods=['POST'])
def play_video():
    """Play a video file on the display.

    Expects JSON::

        {"path": "/path/to/video.mp4"}
    """
    global video_stop_flag
    try:
        data = request.get_json()
        if not data or 'path' not in data:
            return jsonify({'status': 'error', 'message': 'Missing path parameter'}), 400

        video_path = data['path']
        if not os.path.exists(video_path):
            return jsonify({'status': 'error',
                            'message': f'Video file not found: {video_path}'}), 404

        video_stop_flag = True
        time.sleep(0.1)
        video_stop_flag = False

        t = threading.Thread(target=play_video_on_display, args=(video_path,), daemon=True)
        t.start()

        logger.info("Started video playback: %s", video_path)
        return jsonify({'status': 'success', 'action': 'video playing', 'path': video_path})
    except Exception as e:
        logger.error("Error playing video: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@display_bp.route('/display/video/stop', methods=['POST', 'GET'])
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


@display_bp.route('/display/gif', methods=['POST'])
def play_gif():
    """Play a GIF animation on the display.

    Expects JSON::

        {"path": "/path/to/animation.gif"}
    """
    global video_stop_flag
    try:
        data = request.get_json()
        if not data or 'path' not in data:
            return jsonify({'status': 'error', 'message': 'Missing path parameter'}), 400

        gif_path = data['path']
        if not os.path.exists(gif_path):
            return jsonify({'status': 'error',
                            'message': f'GIF file not found: {gif_path}'}), 404

        video_stop_flag = True
        time.sleep(0.1)
        video_stop_flag = False

        t = threading.Thread(target=play_gif_on_display, args=(gif_path,), daemon=True)
        t.start()

        logger.info("Started GIF playback: %s", gif_path)
        return jsonify({'status': 'success', 'action': 'gif playing', 'path': gif_path})
    except Exception as e:
        logger.error("Error playing GIF: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@display_bp.route('/display/clear', methods=['POST', 'GET'])
def clear_screen():
    """Clear the display to black."""
    try:
        clear_display((0, 0, 0))
        logger.info("Display cleared")
        return jsonify({'status': 'success', 'action': 'display cleared'})
    except Exception as e:
        logger.error("Error clearing display: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500
