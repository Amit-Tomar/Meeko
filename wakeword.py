"""
Wake word detection module using OpenWakeWord.

Listens on the default microphone for the "alexa" wake word and fires an
optional callback plus shows a brief on-screen notification.
"""

import time
import threading
import logging
import numpy as np
import pyaudio
from openwakeword.model import Model
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audio configuration
# ---------------------------------------------------------------------------

AUDIO_FORMAT   = pyaudio.paInt16
AUDIO_CHANNELS = 1
AUDIO_RATE     = 16000
AUDIO_CHUNK    = 1280   # 80 ms chunks at 16 kHz

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

wakeword_stop_flag       = False
wakeword_thread          = None
wakeword_model           = None
wakeword_detected_callback = None
last_detection_time      = 0
DETECTION_COOLDOWN       = 2.0   # seconds between detections

# ---------------------------------------------------------------------------
# Wakeword helpers
# ---------------------------------------------------------------------------

def initialize_wakeword_model():
    """Load the OpenWakeWord model (alexa)."""
    global wakeword_model
    try:
        logger.info("Initialising wake word model with 'alexa'...")
        wakeword_model = Model(wakeword_models=["alexa"])
        logger.info("Wake word model initialised: alexa")
        return True
    except Exception as e:
        logger.error("Error initialising wake word model: %s", str(e))
        import traceback
        logger.error(traceback.format_exc())
        return False


def wakeword_detection_loop(callback=None):
    """Blocking loop that reads mic audio and runs the wake word model."""
    global wakeword_stop_flag, last_detection_time

    # Lazy import to avoid circular dependency with display_controller
    from display_controller import display_text_centered, clear_display

    try:
        audio  = pyaudio.PyAudio()
        stream = audio.open(
            format=AUDIO_FORMAT,
            channels=AUDIO_CHANNELS,
            rate=AUDIO_RATE,
            input=True,
            frames_per_buffer=AUDIO_CHUNK,
        )

        logger.info("Wake word detection started, listening...")

        while not wakeword_stop_flag:
            audio_data  = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            prediction = wakeword_model.predict(audio_array)

            for mdl_name, score in prediction.items():
                if score > 0.5:
                    current_time = time.time()
                    if current_time - last_detection_time >= DETECTION_COOLDOWN:
                        logger.info("Wake word detected! Model: %s, Score: %.3f",
                                    mdl_name, score)
                        last_detection_time = current_time

                        if callback:
                            callback(mdl_name, score)

                        display_text_centered("Alexa!", color=(0, 255, 0), size=50)
                        time.sleep(1)
                        clear_display()

        stream.stop_stream()
        stream.close()
        audio.terminate()

        logger.info("Wake word detection stopped")

    except Exception as e:
        logger.error("Error in wake word detection: %s", str(e))
        wakeword_stop_flag = False


def start_wakeword_detection(callback=None):
    """Start wake word detection in a background thread.

    Returns True on success, False if the model could not be loaded.
    """
    global wakeword_thread, wakeword_stop_flag, wakeword_detected_callback

    stop_wakeword_detection()

    if wakeword_model is None:
        if not initialize_wakeword_model():
            return False

    wakeword_stop_flag        = False
    wakeword_detected_callback = callback

    wakeword_thread = threading.Thread(
        target=wakeword_detection_loop,
        args=(callback,),
        daemon=True,
    )
    wakeword_thread.start()

    logger.info("Wake word detection thread started")
    return True


def stop_wakeword_detection():
    """Signal the detection thread to stop and wait for it to finish."""
    global wakeword_stop_flag, wakeword_thread

    if wakeword_thread and wakeword_thread.is_alive():
        wakeword_stop_flag = True
        wakeword_thread.join(timeout=2.0)
        logger.info("Wake word detection stopped")


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

wakeword_bp = Blueprint('wakeword', __name__)


@wakeword_bp.route('/wakeword/start', methods=['POST', 'GET'])
def start_wakeword():
    """Start wake word detection."""
    try:
        if start_wakeword_detection():
            return jsonify({'status': 'success',
                            'action': 'wake word detection started'})
        return jsonify({'status': 'error',
                        'message': 'Failed to start wake word detection'}), 500
    except Exception as e:
        logger.error("Error starting wake word detection: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@wakeword_bp.route('/wakeword/stop', methods=['POST', 'GET'])
def stop_wakeword():
    """Stop wake word detection."""
    try:
        stop_wakeword_detection()
        return jsonify({'status': 'success',
                        'action': 'wake word detection stopped'})
    except Exception as e:
        logger.error("Error stopping wake word detection: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@wakeword_bp.route('/wakeword/status', methods=['GET'])
def wakeword_status():
    """Return whether wake word detection is currently active."""
    try:
        is_active    = wakeword_thread is not None and wakeword_thread.is_alive()
        model_loaded = wakeword_model is not None
        return jsonify({
            'status':       'success',
            'active':       is_active,
            'model_loaded': model_loaded,
        })
    except Exception as e:
        logger.error("Error getting wake word status: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500
