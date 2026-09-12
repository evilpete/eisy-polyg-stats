"""
Custom Parameters parsing.

The display list is given as a single comma separated parameter, for example

    display = +load_avg,-cpu_temp,+disk_capacity=/ /var /var/isy, -system_uptime

A leading '+' enables a metric, '-' disables it, no prefix means enable.
Anything after '=' is the metric's argument list, space (or comma-in-quotes
free) separated.  Metrics that are not mentioned keep their default state.

An individual driver can be blocked by its ISY identifier, which is how you
drop one line of a metric without losing the rest -- `-GV36` keeps uptime but
hides the minutes, `-GV2` keeps load average without the 15 minute figure:

    display = +system_uptime,-GV36

Individual metrics may also be given their own parameter key, which is handy
in the PG3 UI:

    disk_capacity = / /var /var/isy
    net_util      = wlan0
    cpu_temp      = false

Other recognised keys:

    temp_unit     = C | F          (default C)
    io_interval   = 1              (seconds, first disk io sample)
    decimals      = true           (see below)

IoX applies the precision its editors advertise, so values are sent as
themselves: 33.0, 0.36, 88.0.  That only holds once IoX has actually
reloaded the profile -- an installed profile whose version has not moved is
served from cache, and a stale editor renders 33.0 as 330 with the decimal
point dropped.  Bump `profile/version.txt` and restart the Admin Console if
you see that.  Setting `decimals = false` is the fallback: everything is
rounded to whole numbers and load average is scaled x100 under a label that
says so.
"""

import re

from .registry import METRICS, METRICS_BY_NAME, MAX_MOUNTS, all_drivers

DRIVER_RE = re.compile(r'^(ST|GV\d+)$', re.IGNORECASE)
DRIVERS = {d for d, _, _ in all_drivers()}

DISPLAY_KEYS = ('display', 'metrics', 'options', 'stats')
FALSE_WORDS = ('false', 'off', 'no', 'none', 'disable', 'disabled', '0')
TRUE_WORDS = ('true', 'on', 'yes', 'enable', 'enabled', '1')


class Config:
    """Resolved plugin configuration."""

    def __init__(self):
        self.enabled = {m.name: m.default for m in METRICS}
        self.args = {m.name: list(m.default_args) for m in METRICS}
        self.temp_unit = 'C'
        self.io_interval = 1
        self.decimals = True
        self.blocked = set()
        self.errors = []

    @property
    def mounts(self):
        return self.args['disk_capacity'][:MAX_MOUNTS]

    def is_on(self, name):
        return self.enabled.get(name, False)

    def shows(self, driver):
        return driver not in self.blocked

    def signature(self):
        """Everything that changes the shape of the ISY profile."""
        parts = [self.temp_unit, 'dec' if self.decimals else 'int']
        parts.extend('-' + d for d in sorted(self.blocked))
        for metric in METRICS:
            if not self.enabled[metric.name]:
                continue
            parts.append(metric.name)
            if metric.dynamic:
                parts.extend(self.args[metric.name][:MAX_MOUNTS])
        return '|'.join(parts)

    def _block(self, driver, state):
        """state False blocks the driver, True puts it back."""
        driver = driver.upper()
        if driver not in DRIVERS:
            self.errors.append("unknown driver '%s'" % driver)
        elif driver == 'ST':
            self.errors.append('ST is the node status and cannot be blocked')
        elif state:
            self.blocked.discard(driver)
        else:
            self.blocked.add(driver)

    def _set(self, name, state, args):
        if DRIVER_RE.match(name):
            self._block(name, state)
            return
        if name not in METRICS_BY_NAME:
            self.errors.append("unknown metric '%s'" % name)
            return
        self.enabled[name] = state
        if args:
            self.args[name] = args

    def _token(self, token):
        token = token.strip()
        if not token:
            return
        state = True
        if token[0] in '+-':
            state = token[0] == '+'
            token = token[1:].strip()
        name, _, raw = token.partition('=')
        self._set(name.strip(), state, raw.split())

    def parse(self, params):
        """params: dict of Custom Parameter key -> value."""
        for key, value in (params or {}).items():
            key = str(key).strip()
            value = '' if value is None else str(value).strip()
            low = key.lower()

            if low in DISPLAY_KEYS:
                for token in value.split(','):
                    self._token(token)
            elif low == 'temp_unit':
                unit = value.upper()[:1]
                if unit in ('C', 'F'):
                    self.temp_unit = unit
                else:
                    self.errors.append("temp_unit must be C or F, got '%s'" % value)
            elif low == 'decimals':
                self.decimals = value.lower() in TRUE_WORDS or value == ''
            elif low == 'io_interval':
                try:
                    self.io_interval = max(1, min(10, int(float(value))))
                except ValueError:
                    self.errors.append("io_interval must be a number, got '%s'" % value)
            elif DRIVER_RE.match(key):
                self._block(key, value.lower() not in FALSE_WORDS)
            elif low in METRICS_BY_NAME:
                if value.lower() in FALSE_WORDS:
                    self._set(low, False, None)
                elif value.lower() in TRUE_WORDS or value == '':
                    self._set(low, True, None)
                else:
                    self._set(low, True, value.replace(',', ' ').split())
            else:
                self.errors.append("unknown parameter '%s'" % key)

        extra = self.args['disk_capacity'][MAX_MOUNTS:]
        if extra:
            self.errors.append('ignoring mount points past the first %d: %s'
                               % (MAX_MOUNTS, ' '.join(extra)))
            self.args['disk_capacity'] = self.args['disk_capacity'][:MAX_MOUNTS]
        return self


def parse(params):
    return Config().parse(params)


def defaults_doc():
    """The default Custom Parameters shown on a fresh install."""
    display = []
    for metric in METRICS:
        token = '+' if metric.default else '-'
        token += metric.name
        if metric.dynamic and metric.default_args:
            token += '=' + ' '.join(metric.default_args)
        display.append(token)
    return ','.join(display)
