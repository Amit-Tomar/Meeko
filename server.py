#!/usr/bin/env python3
"""
Flask server for controlling a Raspberry Pi robot car with L298N motor driver.

Modules
-------
motor              – GPIO setup, motor control, speed routes
display_controller – TFT display helpers and display routes
wakeword           – OpenWakeWord detection and wakeword routes
debug_routes       – Low-level diagnostic routes
"""

import atexit
import logging

from flask import Flask, jsonify, render_template

from motor             import motor_bp,   setup_gpio, cleanup_gpio
import motor
from display_controller import display_bp
from wakeword          import wakeword_bp
from debug_routes      import debug_bp

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Register blueprints
app.register_blueprint(motor_bp)
app.register_blueprint(display_bp)
app.register_blueprint(wakeword_bp)
app.register_blueprint(debug_bp)

# ---------------------------------------------------------------------------
# General routes
# ---------------------------------------------------------------------------

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
        'current_speed': motor.current_speed,
        'endpoints': {
            '/forward':             'Move forward',
            '/backward':            'Move backward',
            '/rotate/clockwise':    'Rotate clockwise at center',
            '/rotate/anticlockwise':'Rotate anticlockwise at center',
            '/stop':                'Stop all motors',
            '/dance':               'Dance sequence (CW 2s → stop → ACW 2s → stop → forward 2s → stop → backward 2s → stop)',
            '/speed/set':           'Set speed (POST: {"speed": 0-100})',
            '/speed/get':           'Get current speed',
            '/speed/left':          'Set left motor speed (POST: {"speed": 0-100})',
            '/speed/right':         'Set right motor speed (POST: {"speed": 0-100})',
            '/display/text':        'Display text (POST: {"text": "...", "color": [R,G,B], "size": 24, "bg_color": [R,G,B]})',
            '/display/video':       'Play video (POST: {"path": "/path/to/video.mp4"})',
            '/display/gif':         'Play GIF animation (POST: {"path": "/path/to/animation.gif"})',
            '/display/video/stop':  'Stop video/GIF playback',
            '/display/clear':       'Clear display to black',
            '/wakeword/start':      'Start wake word detection',
            '/wakeword/stop':       'Stop wake word detection',
            '/wakeword/status':     'Get wake word detection status',
            '/debug/pins':          'Show live state of all GPIO pins with wiring details',
            '/debug/motor/left':    'Drive left motor only (optional ?direction=forward|backward)',
            '/debug/motor/right':   'Drive right motor only (optional ?direction=forward|backward)',
            '/debug/motor/raw':     'Bypass PWM, drive one side with plain GPIO.output (?side=left|right|both, ?direction=forward|backward)',
        },
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("Raspberry Pi Car Controller Starting...")
    logger.info("=" * 50)
    setup_gpio()
    atexit.register(cleanup_gpio)
    logger.info("GPIO initialised successfully")
    logger.info("Server running on http://0.0.0.0:5000")
    logger.info("Access controller UI from mobile browser")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=True)
