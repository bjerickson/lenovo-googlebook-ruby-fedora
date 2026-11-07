#!/usr/bin/env python3
"""Ambient-light screen brightness for KDE Plasma on Ruby.

Reads the ISH light sensor (cros-ec-light, IIO) and sets the internal panel's
brightness through Plasma's own org.kde.ScreenBrightness D-Bus API, so the
brightness slider and keys stay in sync and no OSD pops up.

A brightness change this service did not make (keys, slider, Plasma dimming the
idle screen) is taken as the user's preference: it becomes an offset on the
lux curve, kept across restarts in ~/.local/state/ruby-autobrightness.
"""
import math
import os
from pathlib import Path
import subprocess
import sys
import time

SERVICE = 'org.kde.ScreenBrightness'
ROOT_PATH = '/org/kde/ScreenBrightness'
DISPLAY_IFACE = 'org.kde.ScreenBrightness.Display'
SUPPRESS_INDICATOR = 0x1
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'ruby-autobrightness'

TICK = 1.0            # seconds between sensor reads
SMOOTHING = 0.25      # exponential smoothing of log-lux per tick
STEP = 0.04           # largest brightness change per tick (fraction of max)
DEADBAND = 0.03       # ignore differences smaller than this
MIN, MAX = 0.03, 1.0


def curve(lux):
    """Fraction of max brightness for a lux level: ~10 % dark, ~54 % at 100 lux, ~92 % in sun."""
    return 0.10 + 0.22 * math.log10(max(lux, 0) + 1)


def clamp(x, lo=MIN, hi=MAX):
    return max(lo, min(hi, x))


def sensor():
    for d in Path('/sys/bus/iio/devices').glob('iio:device*'):
        try:
            if (d / 'name').read_text().strip() == 'cros-ec-light':
                return d / 'in_illuminance_input'
        except OSError:
            pass
    return None


def busctl(*args):
    r = subprocess.run(['busctl', '--user', *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or 'busctl failed')
    return r.stdout.strip()


def prop(path, iface, name):
    """busctl prints e.g. 'i 4800', 'b true', 'as 2 "display0" "display1"'."""
    kind, _, value = busctl('get-property', SERVICE, path, iface, name).partition(' ')
    if kind == 'i':
        return int(value)
    if kind == 'b':
        return value == 'true'
    if kind == 'as':
        return [v.strip('"') for v in value.split(' ')[1:]]
    return value


def internal_display():
    for name in prop(ROOT_PATH, SERVICE, 'DisplaysDBusNames'):
        path = f'{ROOT_PATH}/{name}'
        if prop(path, DISPLAY_IFACE, 'IsInternal'):
            return path
    return None


class Controller:
    """Pure decision logic, separate from I/O so it can be tested."""

    def __init__(self, offset=0.0):
        self.offset = offset
        self.log_lux = None
        self.last_set = None

    def step(self, lux, current, maximum):
        """Return the brightness to set, or None to leave it."""
        log_lux = math.log10(max(lux, 0) + 1)
        self.log_lux = log_lux if self.log_lux is None else self.log_lux + SMOOTHING * (log_lux - self.log_lux)
        base = curve(10 ** self.log_lux - 1)
        if self.last_set is not None and abs(current - self.last_set) > max(1, maximum * 0.01):
            # Someone else changed it: keep their choice as the new offset.
            self.offset = clamp(current / maximum - base, -1.0, 1.0)
            self.last_set = current
            return None
        target = clamp(base + self.offset)
        now = current / maximum
        if abs(target - now) < DEADBAND:
            self.last_set = current
            return None
        nxt = now + max(-STEP, min(STEP, target - now))
        value = max(1, round(nxt * maximum))
        self.last_set = value
        return value


def load_offset():
    try:
        return float(STATE.read_text())
    except (OSError, ValueError):
        return 0.0


def save_offset(offset):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(f'{offset:.4f}\n')
    except OSError:
        pass


def main():
    light = sensor()
    if light is None:
        sys.exit('No cros-ec-light sensor (is cros_ec_ishtp loaded?)')
    ctl = Controller(load_offset())
    saved = ctl.offset
    display = None
    while True:
        try:
            if display is None:
                display = internal_display()
                if display is None:
                    raise RuntimeError('Plasma reports no internal display yet')
                print('Controlling', display, flush=True)
            lux = float(light.read_text())
            current = prop(display, DISPLAY_IFACE, 'Brightness')
            maximum = prop(display, DISPLAY_IFACE, 'MaxBrightness')
            value = ctl.step(lux, current, maximum)
            if value is not None:
                busctl('call', SERVICE, display, DISPLAY_IFACE, 'SetBrightness', 'iu', str(value), str(SUPPRESS_INDICATOR))
            if abs(ctl.offset - saved) > 0.005:
                save_offset(ctl.offset)
                saved = ctl.offset
        except (OSError, ValueError, RuntimeError) as e:
            # Plasma restarting, display hotplug, sensor hiccup: retry from scratch.
            print(f'retrying: {e}', file=sys.stderr, flush=True)
            display = None
            time.sleep(5)
            continue
        time.sleep(TICK)


if __name__ == '__main__':
    main()
