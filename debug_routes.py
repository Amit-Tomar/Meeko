"""
Debug routes for diagnosing motor and GPIO wiring issues on the Raspberry Pi.
"""

import time
import logging
import RPi.GPIO as GPIO
from flask import Blueprint, jsonify, request

import motor

logger = logging.getLogger(__name__)

debug_bp = Blueprint('debug', __name__)


@debug_bp.route('/debug/pins', methods=['GET'])
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
            (motor.LEFT_FORWARD,   37, 'LEFT_FORWARD  (IN2)',  'L298N IN2  – left wheels forward'),
            (motor.LEFT_BACKWARD,  36, 'LEFT_BACKWARD (IN1)',  'L298N IN1  – left wheels backward'),
            (motor.RIGHT_FORWARD,  35, 'RIGHT_FORWARD (IN3)',  'L298N IN3  – right wheels forward'),
            (motor.RIGHT_BACKWARD, 33, 'RIGHT_BACKWARD(IN4)',  'L298N IN4  – right wheels backward'),
            # Enable / PWM pins
            (motor.LEFT_ENABLE,  32, 'LEFT_ENABLE   (ENA)', 'L298N ENA  – left motor PWM speed (Blue wire, Pin 32)'),
            (motor.RIGHT_ENABLE, 12, 'RIGHT_ENABLE  (ENB)', 'L298N ENB  – right motor PWM speed (Brown wire, Pin 12)'),
            # TFT display pins (GPIO10/11 are SPI hardware-managed – not readable via GPIO.input)
            (8,  24, 'TFT_CS',    'ST7789 CS  (Green wire → CE0, Pin 24)'),
            (25, 22, 'TFT_DC',    'ST7789 D/C (Purple wire, Pin 22)'),
            (24, 18, 'TFT_RESET', 'ST7789 RST (Blue wire, Pin 18)'),
            (10, 19, 'TFT_MOSI',  'ST7789 MOSI (Grey wire, Pin 19) – SPI hardware'),
            (11, 23, 'TFT_SCK',   'ST7789 SCK  (White wire, Pin 23) – SPI hardware'),
        ]

        # Pins managed by the SPI hardware peripheral – cannot be read via GPIO.input
        SPI_HW_PINS = {10, 11}

        pin_states = []
        warnings   = []

        for bcm, phys, role, wiring in pin_catalogue:
            if bcm in SPI_HW_PINS:
                state_label = 'SPI_HARDWARE_MANAGED'
                state       = None
            else:
                try:
                    state       = GPIO.input(bcm)
                    state_label = 'HIGH' if state == GPIO.HIGH else 'LOW'
                except Exception as read_err:
                    state_label = f'READ_ERROR ({read_err})'
                    state       = None

            entry = {
                'bcm_gpio':     bcm,
                'physical_pin': phys,
                'role':         role,
                'connected_to': wiring,
                'state':        state_label,
            }

            if bcm == motor.LEFT_ENABLE:
                entry['pwm_duty_cycle'] = (motor.left_pwm_duty
                                           if motor.left_pwm is not None
                                           else 'pwm_not_started')
            elif bcm == motor.RIGHT_ENABLE:
                entry['pwm_duty_cycle'] = (motor.right_pwm_duty
                                           if motor.right_pwm is not None
                                           else 'pwm_not_started')

            pin_states.append(entry)

        # ------------------------------------------------------------------ #
        # Sanity checks                                                        #
        # ------------------------------------------------------------------ #
        enable_states = {p['role']: p['state'] for p in pin_states if 'ENABLE' in p['role']}
        for role, state in enable_states.items():
            if state != 'HIGH':
                warnings.append(
                    f'{role} is {state} – motor on this side will not move. '
                    'Check ENA/ENB jumper or pin-extender wiring.'
                )

        left_pins  = [p for p in pin_states
                      if 'LEFT_FORWARD' in p['role'] or 'LEFT_BACKWARD' in p['role']]
        right_pins = [p for p in pin_states
                      if 'RIGHT_FORWARD' in p['role'] or 'RIGHT_BACKWARD' in p['role']]
        for side_label, side_pins in [('LEFT', left_pins), ('RIGHT', right_pins)]:
            if sum(1 for p in side_pins if p['state'] == 'HIGH') > 1:
                warnings.append(
                    f'{side_label} motor has both IN pins HIGH simultaneously – '
                    'this will cause a shoot-through condition on the L298N.'
                )

        logger.info("Debug /debug/pins requested – %d pins reported, %d warnings",
                    len(pin_states), len(warnings))

        return jsonify({
            'status':          'success',
            'gpio_mode':       'BCM',
            'current_speed_pct': motor.current_speed,
            'pin_config': {
                'LEFT_FORWARD_BCM':   motor.LEFT_FORWARD,
                'LEFT_BACKWARD_BCM':  motor.LEFT_BACKWARD,
                'RIGHT_FORWARD_BCM':  motor.RIGHT_FORWARD,
                'RIGHT_BACKWARD_BCM': motor.RIGHT_BACKWARD,
                'LEFT_ENABLE_BCM':    motor.LEFT_ENABLE,
                'RIGHT_ENABLE_BCM':   motor.RIGHT_ENABLE,
            },
            'pins':     pin_states,
            'warnings': warnings,
        })

    except Exception as e:
        logger.error("Error in /debug/pins: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@debug_bp.route('/debug/motor/left', methods=['GET', 'POST'])
def debug_motor_left():
    """Drive ONLY the left motor for 1 second then stop.

    Optional query param: ``?direction=forward`` (default) or ``?direction=backward``
    """
    try:
        direction = request.args.get('direction', 'forward').lower()
        motor.stop_all_motors()
        time.sleep(0.05)

        if direction == 'backward':
            GPIO.output(motor.LEFT_BACKWARD, GPIO.HIGH)
            pin_driven_name = f'LEFT_BACKWARD (GPIO{motor.LEFT_BACKWARD}, phys36)'
        else:
            GPIO.output(motor.LEFT_FORWARD, GPIO.HIGH)
            pin_driven_name = f'LEFT_FORWARD (GPIO{motor.LEFT_FORWARD}, phys37)'

        logger.info("DEBUG: Left motor only – direction=%s, pin=%s HIGH for 1s",
                    direction, pin_driven_name)
        time.sleep(1)
        motor.stop_all_motors()

        return jsonify({
            'status':     'success',
            'motor':      'left',
            'direction':  direction,
            'pin_driven': pin_driven_name,
            'enable_pin': f'LEFT_ENABLE (GPIO{motor.LEFT_ENABLE}) – ENA on L298N',
            'note':       'Motor ran for 1 second then stopped. If it did not move, '
                          'check ENA wire from pin extender to L298N.',
        })
    except Exception as e:
        logger.error("Error in /debug/motor/left: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@debug_bp.route('/debug/motor/right', methods=['GET', 'POST'])
def debug_motor_right():
    """Drive ONLY the right motor for 1 second then stop.

    Optional query param: ``?direction=forward`` (default) or ``?direction=backward``
    """
    try:
        direction = request.args.get('direction', 'forward').lower()
        motor.stop_all_motors()
        time.sleep(0.05)

        if direction == 'backward':
            GPIO.output(motor.RIGHT_BACKWARD, GPIO.HIGH)
            pin_driven_name = f'RIGHT_BACKWARD (GPIO{motor.RIGHT_BACKWARD}, phys33)'
        else:
            GPIO.output(motor.RIGHT_FORWARD, GPIO.HIGH)
            pin_driven_name = f'RIGHT_FORWARD (GPIO{motor.RIGHT_FORWARD}, phys35)'

        logger.info("DEBUG: Right motor only – direction=%s, pin=%s HIGH for 1s",
                    direction, pin_driven_name)
        time.sleep(1)
        motor.stop_all_motors()

        return jsonify({
            'status':     'success',
            'motor':      'right',
            'direction':  direction,
            'pin_driven': pin_driven_name,
            'enable_pin': f'RIGHT_ENABLE (GPIO{motor.RIGHT_ENABLE}) – ENB on L298N',
            'note':       'Motor ran for 1 second then stopped. If it did not move, '
                          'check ENB wire from pin extender to L298N.',
        })
    except Exception as e:
        logger.error("Error in /debug/motor/right: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500


@debug_bp.route('/debug/motor/raw', methods=['GET', 'POST'])
def debug_motor_raw():
    """Low-level motor test: bypass PWM, use plain ``GPIO.output`` on enable pins.

    Query params:
      * ``side``      = ``left`` | ``right`` | ``both``  (default: ``both``)
      * ``direction`` = ``forward`` | ``backward``        (default: ``forward``)
    """
    try:
        side      = request.args.get('side',      'both').lower()
        direction = request.args.get('direction', 'forward').lower()

        results = {}

        # ── Step 1: hard stop ──────────────────────────────────────────────
        motor.stop_all_motors()
        if motor.left_pwm:
            motor.left_pwm.stop()
        if motor.right_pwm:
            motor.right_pwm.stop()
        GPIO.output(motor.LEFT_ENABLE,  GPIO.LOW)
        GPIO.output(motor.RIGHT_ENABLE, GPIO.LOW)
        time.sleep(0.1)

        results['step1_stop_readback'] = {
            'LEFT_ENABLE':   'HIGH' if GPIO.input(motor.LEFT_ENABLE)   == GPIO.HIGH else 'LOW',
            'RIGHT_ENABLE':  'HIGH' if GPIO.input(motor.RIGHT_ENABLE)  == GPIO.HIGH else 'LOW',
            'LEFT_FORWARD':  'HIGH' if GPIO.input(motor.LEFT_FORWARD)  == GPIO.HIGH else 'LOW',
            'RIGHT_FORWARD': 'HIGH' if GPIO.input(motor.RIGHT_FORWARD) == GPIO.HIGH else 'LOW',
        }

        # ── Step 2: drive requested sides ─────────────────────────────────
        drive_left  = side in ('left',  'both')
        drive_right = side in ('right', 'both')

        if drive_left:
            GPIO.output(motor.LEFT_ENABLE,  GPIO.HIGH)
        if drive_right:
            GPIO.output(motor.RIGHT_ENABLE, GPIO.HIGH)
        time.sleep(0.05)

        if direction == 'forward':
            if drive_left:
                GPIO.output(motor.LEFT_FORWARD,  GPIO.HIGH)
            if drive_right:
                GPIO.output(motor.RIGHT_FORWARD, GPIO.HIGH)
            dir_pins = {
                'left':  f'LEFT_FORWARD  (GPIO{motor.LEFT_FORWARD},  physical pin 37)',
                'right': f'RIGHT_FORWARD (GPIO{motor.RIGHT_FORWARD}, physical pin 35)',
            }
        else:
            if drive_left:
                GPIO.output(motor.LEFT_BACKWARD,  GPIO.HIGH)
            if drive_right:
                GPIO.output(motor.RIGHT_BACKWARD, GPIO.HIGH)
            dir_pins = {
                'left':  f'LEFT_BACKWARD  (GPIO{motor.LEFT_BACKWARD},  physical pin 36)',
                'right': f'RIGHT_BACKWARD (GPIO{motor.RIGHT_BACKWARD}, physical pin 33)',
            }

        # ── Step 3: read back all motor pins ──────────────────────────────
        readback = {
            f'LEFT_ENABLE   GPIO{motor.LEFT_ENABLE}  phys32':
                'HIGH' if GPIO.input(motor.LEFT_ENABLE)   == GPIO.HIGH else 'LOW',
            f'RIGHT_ENABLE  GPIO{motor.RIGHT_ENABLE} phys12':
                'HIGH' if GPIO.input(motor.RIGHT_ENABLE)  == GPIO.HIGH else 'LOW',
            f'LEFT_FORWARD  GPIO{motor.LEFT_FORWARD}  phys37':
                'HIGH' if GPIO.input(motor.LEFT_FORWARD)  == GPIO.HIGH else 'LOW',
            f'LEFT_BACKWARD GPIO{motor.LEFT_BACKWARD} phys36':
                'HIGH' if GPIO.input(motor.LEFT_BACKWARD) == GPIO.HIGH else 'LOW',
            f'RIGHT_FORWARD GPIO{motor.RIGHT_FORWARD} phys35':
                'HIGH' if GPIO.input(motor.RIGHT_FORWARD) == GPIO.HIGH else 'LOW',
            f'RIGHT_BACKWARD GPIO{motor.RIGHT_BACKWARD} phys33':
                'HIGH' if GPIO.input(motor.RIGHT_BACKWARD) == GPIO.HIGH else 'LOW',
        }
        results['step2_drive_readback'] = readback

        warnings = []
        actions  = []

        left_en_stuck  = results['step1_stop_readback']['LEFT_ENABLE']  == 'HIGH'
        right_en_stuck = results['step1_stop_readback']['RIGHT_ENABLE'] == 'HIGH'

        if left_en_stuck:
            warnings.append(
                'LEFT_ENABLE (GPIO12, physical pin 32) read HIGH immediately after '
                'GPIO.output(LOW) was called. The ENA jumper on the L298N is almost '
                'certainly still fitted – hardwiring ENA to 5 V.'
            )
        if right_en_stuck:
            warnings.append(
                'RIGHT_ENABLE (GPIO18, physical pin 12) read HIGH immediately after '
                'GPIO.output(LOW) was called. The ENB jumper on the L298N is almost '
                'certainly still fitted.'
            )

        left_dir_key  = (f'LEFT_FORWARD  GPIO{motor.LEFT_FORWARD}  phys37'
                         if direction == 'forward'
                         else f'LEFT_BACKWARD GPIO{motor.LEFT_BACKWARD} phys36')
        right_dir_key = (f'RIGHT_FORWARD GPIO{motor.RIGHT_FORWARD} phys35'
                         if direction == 'forward'
                         else f'RIGHT_BACKWARD GPIO{motor.RIGHT_BACKWARD} phys33')

        if drive_left and readback.get(left_dir_key) != 'HIGH':
            warnings.append(
                f'Left direction pin ({left_dir_key}) reads LOW after GPIO.output(HIGH). '
                'Pin extender not fully seated or broken trace.'
            )
        if drive_right and readback.get(right_dir_key) != 'HIGH':
            warnings.append(
                f'Right direction pin ({right_dir_key}) reads LOW after GPIO.output(HIGH). '
                'Same issue for the right side.'
            )

        left_ok  = (readback[f'LEFT_ENABLE   GPIO{motor.LEFT_ENABLE}  phys32']  == 'HIGH' and
                    readback.get(left_dir_key) == 'HIGH')
        right_ok = (readback[f'RIGHT_ENABLE  GPIO{motor.RIGHT_ENABLE} phys12'] == 'HIGH' and
                    readback.get(right_dir_key) == 'HIGH')

        if drive_left and left_ok:
            actions.append(
                'LEFT MOTOR – Pi GPIO is outputting correctly. '
                'Fault is downstream of the Pi. Check:\n'
                '  1. Physical pin 37 → L298N IN2  (GPIO26) – left forward\n'
                '  2. Physical pin 36 → L298N IN1  (GPIO16) – left backward\n'
                '  3. Physical pin 32 → L298N ENA  (GPIO12) – if ENA jumper removed'
            )
        if drive_right and right_ok:
            actions.append(
                'RIGHT MOTOR – Pi GPIO is outputting correctly. '
                'If the right motor moved, right side wiring is good.'
            )

        logger.info("DEBUG raw motor: side=%s direction=%s warnings=%d actions=%d",
                    side, direction, len(warnings), len(actions))

        # ── Step 4: hold 2 s then restore ─────────────────────────────────
        time.sleep(2)
        motor.stop_all_motors()
        motor.left_pwm.start(motor.left_pwm_duty)
        motor.right_pwm.start(motor.right_pwm_duty)

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
        try:
            motor.stop_all_motors()
            motor.left_pwm.start(motor.left_pwm_duty)
            motor.right_pwm.start(motor.right_pwm_duty)
        except Exception:
            pass
        logger.error("Error in /debug/motor/raw: %s", str(e))
        return jsonify({'status': 'error', 'message': str(e)}), 500
