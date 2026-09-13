"""
Metric collection.  FreeBSD first, but everything degrades gracefully when a
counter is not exposed by the kernel (a value of None is simply not reported).
"""

import os
import re
import subprocess
import time

import psutil

try:
    import udi_interface
    LOGGER = udi_interface.LOGGER
except ImportError:  # allows running the collector standalone
    import logging
    LOGGER = logging.getLogger(__name__)

from .registry import MOUNT_DRIVERS

PREFERRED_IFACES = ('eth0', 'wlan0')
TEMP_RE = re.compile(r'(-?\d+(?:\.\d+)?)')


def get_disk_io_utilization(interval=1):
    """Percent of wall time the disks spent busy, sampled over `interval`."""
    before = psutil.disk_io_counters()
    time.sleep(interval)
    after = psutil.disk_io_counters()
    if before is None or after is None:
        return None
    if not hasattr(after, 'busy_time'):
        return None
    busy_ms = after.busy_time - before.busy_time
    return min(busy_ms / (interval * 1000.0) * 100.0, 100.0)


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _sysctl(name):
    return _run(['sysctl', '-n', name])


def _as_temp(text):
    """'45.1C' / '318.2K' / '45' -> degrees Celsius."""
    if not text:
        return None
    match = TEMP_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    if text.strip().endswith('K') or value > 200:
        # FreeBSD reports some thermal zones in decikelvin
        if value > 1000:
            value /= 10.0
        value -= 273.15
    return value


def _sensor(*wanted):
    """First reading from psutil whose chip or label matches one of `wanted`."""
    if not hasattr(psutil, 'sensors_temperatures'):
        return None
    try:
        sensors = psutil.sensors_temperatures()
    except (OSError, AttributeError):
        return None
    for chip, entries in (sensors or {}).items():
        for entry in entries:
            haystack = f"{chip} {entry.label or ''}".lower()
            if any(want in haystack for want in wanted) and entry.current:
                return float(entry.current)
    return None


def cpu_temperature():
    temp = _sensor('coretemp', 'k10temp', 'cpu_thermal', 'cpu', 'acpitz')
    if temp is not None:
        return temp
    for oid in ('dev.cpu.0.temperature', 'hw.acpi.thermal.tz0.temperature'):
        temp = _as_temp(_sysctl(oid))
        if temp is not None:
            return temp
    return None


def gpu_temperature():
    temp = _sensor('gpu', 'amdgpu', 'radeon', 'nouveau')
    if temp is not None:
        return temp
    out = _run(['nvidia-smi', '--query-gpu=temperature.gpu',
                '--format=csv,noheader,nounits'])
    if out:
        try:
            return float(out.splitlines()[0].strip())
        except ValueError:
            pass
    return _as_temp(_sysctl('hw.acpi.thermal.tz1.temperature'))


def root_disk_device():
    """Best guess at the physical device holding /."""
    try:
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint == '/':
                dev = part.device
                break
        else:
            return None
    except OSError:
        return None
    # /dev/ada0p2 -> /dev/ada0, /dev/nvd0p2 -> /dev/nvd0, /dev/sda1 -> /dev/sda
    name = os.path.basename(dev)
    name = re.sub(r'(p\d+|s\d+[a-z]?|\d+)$', '', name) if not name.startswith('nvme') \
        else re.sub(r'n\d+p\d+$', '', name)
    return f"/dev/{name}" if name else None


def disk_temperature(device=None):
    temp = _sensor('nvme', 'ada', 'drivetemp', 'disk')
    if temp is not None:
        return temp
    device = device or root_disk_device()
    if not device:
        return None
    base = os.path.basename(device)
    # for oid in ('dev.%s.temperature' % base.replace('nvme', 'nvme'),
    #            'dev.nvme.%s.temperature' % re.sub(r'\D', '', base)):
    for oid in (
        f"dev.{base}.temperature",
        f"dev.nvme.{re.sub(r'\D', '', base)}.temperature"
    ):
        temp = _as_temp(_sysctl(oid))
        if temp is not None:
            return temp
    out = _run(['smartctl', '-A', '-n', 'standby', device])
    if not out:
        return None
    for line in out.splitlines():
        low = line.lower()
        if 'temperature_celsius' in low or low.startswith('temperature:'):
            numbers = TEMP_RE.findall(line)
            if numbers:
                return float(numbers[-1])
    return None


def pick_interface(configured=None):
    try:
        stats = psutil.net_if_stats()
    except OSError:
        return configured
    if configured and configured in stats:
        return configured
    for name in PREFERRED_IFACES:
        if name in stats and stats[name].isup:
            return name
    candidates = [n for n, s in stats.items()
                  if s.isup and not n.startswith(('lo', 'pflog', 'tun', 'tap'))]
    return candidates[0] if candidates else configured


class Collector:
    """Samples the host and returns {driver: value} for the enabled metrics.

    Rate based metrics are differenced against the previous poll, so no poll
    ever blocks -- except the very first disk io sample, which falls back to
    get_disk_io_utilization().
    """

    def __init__(self, config):
        self.config = config
        self.cpu_count = psutil.cpu_count() or 1
        self.iface = pick_interface(self._arg('net_util'))
        self._disk_io = None
        self._net_io = None
        self._sample = None
        self._net_sample = None
        self._warned = {}
        psutil.cpu_percent(interval=None)  # prime the cpu delta

    # ------------------------------------------------------------------ util

    def _arg(self, name, index=0):
        args = self.config.args.get(name) or []
        return args[index] if len(args) > index else None

    def _warn_once(self, key, message):
        """Log a degraded counter once and remember it for the PG3 notices."""
        if key not in self._warned:
            LOGGER.warning(message)
        self._warned[key] = message

    @property
    def issues(self):
        return dict(self._warned)

    def _temp(self, celsius):
        if celsius is None:
            return None
        if self.config.temp_unit == 'F':
            return celsius * 9.0 / 5.0 + 32.0
        return celsius

    # -------------------------------------------------------------- samplers

    def load_avg(self, out):
        try:
            one, five, fifteen = os.getloadavg()
        except (OSError, AttributeError):
            return
        out['GV0'], out['GV1'], out['GV2'] = one, five, fifteen

    def cpu_util(self, out):
        out['GV3'] = psutil.cpu_percent(interval=None)

    def cpu_temp(self, out):
        value = self._temp(cpu_temperature())
        if value is None:
            self._warn_once('cpu_temp', 'No CPU temperature source found')
            return
        out['GV4'] = value

    def gpu_temp(self, out):
        value = self._temp(gpu_temperature())
        if value is None:
            self._warn_once('gpu_temp', 'No GPU temperature source found')
            return
        out['GV5'] = value

    def disk_temp(self, out):
        value = self._temp(disk_temperature(self._arg('disk_temp')))
        if value is None:
            self._warn_once('disk_temp', 'No disk temperature source found')
            return
        out['GV6'] = value

    def mem_usage(self, out):
        out['GV7'] = psutil.virtual_memory().percent

    def disk_capacity(self, out):
        for index, path in enumerate(self.config.mounts):
            try:
                out[MOUNT_DRIVERS[index]] = psutil.disk_usage(path).percent
            except OSError:
                self._warn_once('mount:' + path,
                                f"Mount point {path} is not available")

    def disk_io_util(self, out):
        counters, _ = self._sample or (None, None)
        if counters is None or not hasattr(counters, 'busy_time'):
            self._warn_once('busy_time', 'Disk busy_time is not available on '
                                         'this platform')
            return
        before, elapsed = self._disk_delta()
        if before is None:
            # nothing to difference against yet, take a short live sample
            value = get_disk_io_utilization(self.config.io_interval)
        else:
            busy_ms = counters.busy_time - before.busy_time
            value = min(busy_ms / (elapsed * 1000.0) * 100.0, 100.0)
        if value is not None:
            out['GV20'] = max(value, 0.0)

    def _disk_delta(self):
        """Previous disk snapshot and the seconds since it was taken."""
        counters, stamp = self._sample or (None, None)
        previous = self._disk_io
        if counters is None or previous is None:
            return None, 0
        before, before_stamp = previous
        elapsed = stamp - before_stamp
        if before is None or elapsed <= 0:
            return None, 0
        return before, elapsed

    def disk_iostats(self, out):
        counters, _ = self._sample or (None, None)
        before, elapsed = self._disk_delta()
        if counters is None or before is None:
            return
        mib = 1024.0 * 1024.0
        out['GV21'] = max(counters.read_bytes - before.read_bytes, 0) / mib / elapsed
        out['GV22'] = max(counters.write_bytes - before.write_bytes, 0) / mib / elapsed
        out['GV23'] = max(counters.read_count - before.read_count, 0) / elapsed
        out['GV24'] = max(counters.write_count - before.write_count, 0) / elapsed

    def _net_delta(self):
        """Current and previous interface counters, and the seconds between."""
        now, stamp = self._net_sample or (None, None)
        if now is None:
            return None, None, 0
        previous, prev_stamp = self._net_io or (None, None)
        if previous is None:
            return None, None, 0
        return now, previous, stamp - prev_stamp

    def net_util(self, out):
        now, before, elapsed = self._net_delta()
        if now is None or elapsed <= 0:
            return
        rx_bits = max(now.bytes_recv - before.bytes_recv, 0) * 8.0 / elapsed
        tx_bits = max(now.bytes_sent - before.bytes_sent, 0) * 8.0 / elapsed
        out['GV31'] = rx_bits / 1000.0
        out['GV32'] = tx_bits / 1000.0
        speed = 0
        try:
            stats = psutil.net_if_stats().get(self.iface)
            speed = stats.speed if stats else 0
        except OSError:
            speed = 0
        if speed:  # link speed is reported in Mbit/s, 0 when unknown
            capacity = speed * 1000000.0
            out['GV30'] = min(max(rx_bits, tx_bits) / capacity * 100.0, 100.0)
        else:
            self._warn_once('speed', f'Link speed for {self.iface} is unknown, network '
                                     'utilization percent not reported')

    def net_errors(self, out):
        now, before, elapsed = self._net_delta()
        if now is None or elapsed <= 0:
            return
        bad = (max(now.errin - before.errin, 0)
               + max(now.errout - before.errout, 0)
               + max(now.dropin - before.dropin, 0)
               + max(now.dropout - before.dropout, 0))
        packets = (max(now.packets_recv - before.packets_recv, 0)
                   + max(now.packets_sent - before.packets_sent, 0))
        total = packets + bad
        out['GV33'] = (bad / total * 100.0) if total else 0.0

    def system_uptime(self, out):
        seconds = int(max(time.time() - psutil.boot_time(), 0))
        out['GV34'] = seconds // 86400
        out['GV35'] = seconds % 86400 // 3600
        out['GV36'] = seconds % 3600 // 60

    # ------------------------------------------------------------------ main

    def collect(self):
        """Returns {driver: value} for every enabled and available metric."""
        out = {}
        # one snapshot per poll of each counter set, so that metrics sharing a
        # source difference against the previous poll and not against each other
        try:
            self._sample = (psutil.disk_io_counters(), time.time())
        except OSError:
            self._sample = None
        try:
            self.iface = pick_interface(self._arg('net_util') or self.iface)
            counters = psutil.net_io_counters(pernic=True).get(self.iface)
            if counters is None:
                self._warn_once('iface', f'Network interface {self.iface} not found')
            self._net_sample = (counters, time.time())
        except OSError:
            self._net_sample = None
        order = ['load_avg', 'cpu_util', 'cpu_temp', 'gpu_temp', 'disk_temp',
                 'mem_usage', 'disk_capacity', 'disk_io_util', 'disk_iostats',
                 'net_util', 'net_errors', 'system_uptime']
        for name in order:
            if not self.config.is_on(name):
                continue
            try:
                getattr(self, name)(out)
            except Exception as error:  # one bad counter must not stop the poll
                LOGGER.error('Failed to collect %s: %s', name, error)
        if self._sample and self._sample[0] is not None:
            self._disk_io = self._sample
        if self._net_sample and self._net_sample[0] is not None:
            self._net_io = self._net_sample
        return out
