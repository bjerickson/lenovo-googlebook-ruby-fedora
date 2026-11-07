#!/usr/bin/env python3
"""Drive Ruby's glowbar (the EC's four-segment lightbar) from desktop state.

Priority: dictation (hyprwhspr recording) > battery (on AC, green segments to the
charge level with the filling segment breathing from yellow to green, solid green
when not charging; amber or red when low on battery) > accent colour > off. The
bar is off while the session is locked, the panel is off or the lid is closed.
The EC rejects the lightbar's built-in sequences, so every frame is set from here.

Needs write access to the lightbar's led_rgb (90-ruby-glowbar.rules grants it
to the video group). The accent comes from Noctalia's theme as rendered for
hyprwhspr's mic OSD, else KDE Plasma's accent colour (kdeglobals), at full
saturation, with a fixed fallback.
"""
import colorsys
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

LIGHTBAR = Path('/sys/class/chromeos/cros_ec/lightbar')
BATTERY = Path('/sys/class/power_supply/BAT0')
AC = Path('/sys/class/power_supply/AC/online')
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
RECORDING = RUNTIME / 'hyprwhspr/recording_status'
THEME = Path.home() / '.config/hyprwhspr/theme/mic-osd.css'
KDEGLOBALS = Path.home() / '.config/kdeglobals'

SEGMENTS = 4
OFF = (0, 0, 0)
FALLBACK_ACCENT = (80, 60, 255)
RECORD = (255, 0, 0)   # fixed: the bar's strong blue LEDs turn the theme's red magenta
CHARGING, FILLING, AMBER, RED = (0, 255, 40), (255, 200, 0), (255, 90, 0), (255, 0, 0)
LOW, CRITICAL = 20, 10           # battery percent on battery power
TICK, STATE_EVERY, REFRESH_EVERY = 0.1, 1.0, 10.0


def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def theme_colour(css, name, default):
    m = re.search(rf'@define-color {name} #([0-9a-fA-F]{{6}})', css)
    return tuple(int(m[1][i:i + 2], 16) for i in (0, 2, 4)) if m else default


def saturate(colour):
    """LEDs render pastel theme colours as white; keep the hue at full saturation and value."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in colour))
    if s < 0.05:
        return colour
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, 1.0, 1.0))


def kde_accent(text):
    """Plasma writes AccentColor=r,g,b under [General] (also when taken from the wallpaper)."""
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('['):
            section = line
        elif section == '[General]' and line.startswith('AccentColor='):
            parts = line.split('=', 1)[1].split(',')
            if len(parts) >= 3 and all(x.strip().isdigit() for x in parts[:3]):
                return tuple(min(255, int(x)) for x in parts[:3])
    return None


def accent_colour():
    css = read(THEME)
    if css:
        return saturate(theme_colour(css, 'border-color', FALLBACK_ACCENT))
    return saturate(kde_accent(read(KDEGLOBALS)) or FALLBACK_ACCENT)


def panel_on():
    """The internal panel's DRM card number depends on driver probe order (simpledrm, Xe)."""
    states = [read(p) for p in Path('/sys/class/drm').glob('card*-eDP-1/dpms')]
    return not states or 'On' in states


def session_locked(session):
    if not session:
        return False
    out = subprocess.run(['loginctl', 'show-session', session, '-p', 'LockedHint', '--value'],
                         capture_output=True, text=True).stdout.strip()
    return out == 'yes'


def lid_closed():
    return any('closed' in read(p) for p in Path('/proc/acpi/button/lid').glob('*/state'))


def scale(colour, k):
    return tuple(round(c * k) for c in colour)


def charging(percent, pulse):
    """Completed segments solid green; the segment being filled breathes, shifting
    from yellow to green as it nears completion."""
    level = max(0.0, min(1.0, percent / 100)) * SEGMENTS
    full = min(int(level), SEGMENTS - 1)
    progress = level - full
    blend = tuple(round(y + (g - y) * progress) for y, g in zip(FILLING, CHARGING))
    return [CHARGING] * full + [scale(blend, pulse)] + [OFF] * (SEGMENTS - full - 1)


class Glowbar:
    def __init__(self):
        self.shown = None
        self.failing = False

    def show(self, frame, force=False):
        if frame == self.shown and not force:
            return
        # The kernel spaces lightbar commands interval_msec (50 ms) apart, so send as few
        # as possible: LED 4 sets all segments at once, otherwise only changed segments.
        if len(set(frame)) == 1:
            text = '4 %d %d %d' % frame[0]
        else:
            changed = [i for i in range(SEGMENTS) if force or not self.shown or frame[i] != self.shown[i]]
            text = ' '.join('%d %d %d %d' % (i, *frame[i]) for i in changed)
        try:
            (LIGHTBAR / 'led_rgb').write_text(text)
            self.shown = frame
            if self.failing:
                print('glowbar writes working again', file=sys.stderr, flush=True)
            self.failing = False
        except OSError as e:
            if not self.failing:             # log once per failure streak, not every tick
                print(f'glowbar write failed: {e}', file=sys.stderr, flush=True)
            self.failing = True
            self.shown = None


def main():
    if not (LIGHTBAR / 'led_rgb').exists():
        sys.exit('No lightbar at ' + str(LIGHTBAR))
    bar = Glowbar()
    session = subprocess.run(['loginctl', 'show-user', str(os.getuid()), '-p', 'Display', '--value'],
                             capture_output=True, text=True).stdout.strip()

    def stop(*_):
        bar.show([OFF] * SEGMENTS, force=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    state, next_state, next_refresh = None, 0.0, 0.0
    while True:
        now = time.monotonic()
        if now >= next_state:
            state = dict(
                dark=session_locked(session) or lid_closed() or not panel_on(),
                recording=RECORDING.exists(),
                ac=read(AC) == '1',
                percent=int(read(BATTERY / 'capacity', '0') or 0),
                charging=read(BATTERY / 'status') == 'Charging',
                accent=accent_colour())
            next_state = now + STATE_EVERY
        force = now >= next_refresh       # rewrite after resume or anything else that reset the EC
        if force:
            next_refresh = now + REFRESH_EVERY
        s = state
        pulse = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(now * 2 * math.pi / 1.6))
        if s['dark']:
            frame = [OFF] * SEGMENTS
        elif s['recording']:
            frame = [scale(RECORD, pulse)] * SEGMENTS
        elif s['ac']:
            frame = charging(s['percent'], pulse) if s['charging'] else [CHARGING] * SEGMENTS
        elif s['percent'] <= CRITICAL:
            frame = [scale(RED, pulse)] * SEGMENTS
        elif s['percent'] <= LOW:
            frame = [AMBER] * SEGMENTS
        else:
            frame = [s['accent']] * SEGMENTS
        bar.show(frame, force)
        time.sleep(TICK)


if __name__ == '__main__':
    main()
