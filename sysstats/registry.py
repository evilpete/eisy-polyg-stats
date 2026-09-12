"""
Metric registry.

Every metric owns a fixed block of ISY driver slots.  Slots are assigned
statically (never re-shuffled when the configuration changes) so that a
metric keeps the same driver across a re-configure and IoX programs that
reference it do not break.

Driver map
----------
  ST              node online
  GV0  - GV2      load average  1 / 5 / 15 minute
  GV3             cpu utilization
  GV4  - GV6      cpu / gpu / disk temperature
  GV7             memory used
  GV10 - GV17     filesystem capacity (up to 8 mount points)
  GV20            disk io utilization (busy time)
  GV21 - GV24     disk iostats  read MB/s, write MB/s, read IOPS, write IOPS
  GV30 - GV32     network utilization  percent, rx kbit/s, tx kbit/s
  GV33            network errors + drops
  GV34            system uptime
"""

# Editor ids emitted into profile/editor/editors.xml
E_BOOL = 'SS_BOOL'
E_PCT = 'SS_PCT'
E_LOAD = 'SS_LOAD'
E_TEMP = 'SS_TEMP'
E_RATE = 'SS_RATE'
E_DAYS = 'SS_DAYS'

# uom, min, max -- the temperature editor is built at runtime because its
# uom depends on the configured unit (4 = Celsius, 17 = Fahrenheit).
EDITORS = {
    E_BOOL: {'uom': 2, 'min': 0, 'max': 1, 'prec': 0},
    E_PCT: {'uom': 51, 'min': 0, 'max': 100, 'prec': 1},
    E_LOAD: {'uom': 56, 'min': 0, 'max': 1000, 'prec': 2},
    E_TEMP: {'uom': 4, 'min': -50, 'max': 250, 'prec': 1},
    E_RATE: {'uom': 56, 'min': 0, 'max': 10000000, 'prec': 1},
    E_DAYS: {'uom': 10, 'min': 0, 'max': 36500, 'prec': 2},
}

MAX_MOUNTS = 8


class Metric:
    """One configurable line item."""

    def __init__(self, name, label, drivers, default=True, args=None,
                 arg_help=None, dynamic=False):
        self.name = name
        self.label = label
        # list of (driver, label, editor)
        self.drivers = drivers
        self.default = default
        self.default_args = args or []
        self.arg_help = arg_help
        # dynamic metrics size their driver list from their arguments
        self.dynamic = dynamic


METRICS = [
    Metric('load_avg', 'Load Average', [
        ('GV0', 'Load Average 1 min', E_LOAD),
        ('GV1', 'Load Average 5 min', E_LOAD),
        ('GV2', 'Load Average 15 min', E_LOAD),
    ]),
    Metric('cpu_util', 'CPU Utilization', [
        ('GV3', 'CPU Utilization', E_PCT),
    ]),
    Metric('cpu_temp', 'CPU Temperature', [
        ('GV4', 'CPU Temperature', E_TEMP),
    ]),
    Metric('gpu_temp', 'GPU Temperature', [
        ('GV5', 'GPU Temperature', E_TEMP),
    ], default=False),
    Metric('disk_temp', 'Disk Temperature', [
        ('GV6', 'Disk Temperature', E_TEMP),
    ], default=False, arg_help='device, e.g. /dev/ada0'),
    Metric('mem_usage', 'Memory Used', [
        ('GV7', 'Memory Used', E_PCT),
    ]),
    Metric('disk_capacity', 'Filesystem Capacity', [], dynamic=True,
           args=['/', '/home', '/var/isy'],
           arg_help='space separated mount points (max %d)' % MAX_MOUNTS),
    Metric('disk_io_util', 'Disk I/O Utilization', [
        ('GV20', 'Disk I/O Utilization', E_PCT),
    ]),
    Metric('disk_iostats', 'Disk I/O Statistics', [
        ('GV21', 'Disk Read MB/s', E_RATE),
        ('GV22', 'Disk Write MB/s', E_RATE),
        ('GV23', 'Disk Read IOPS', E_RATE),
        ('GV24', 'Disk Write IOPS', E_RATE),
    ]),
    Metric('net_util', 'Network Utilization', [
        ('GV30', 'Network Utilization', E_PCT),
        ('GV31', 'Network Rx kbit/s', E_RATE),
        ('GV32', 'Network Tx kbit/s', E_RATE),
    ], arg_help='interface name, e.g. eth0 or wlan0'),
    Metric('net_errors', 'Network Errors + Drops', [
        ('GV33', 'Network Errors + Drops', E_PCT),
    ]),
    Metric('system_uptime', 'System Uptime', [
        ('GV34', 'System Uptime', E_DAYS),
    ]),
]

METRICS_BY_NAME = {m.name: m for m in METRICS}

# Filesystem capacity slots, handed out in the order the mount points are
# listed in the configuration.
MOUNT_DRIVERS = ['GV1%d' % i for i in range(MAX_MOUNTS)]


def mount_drivers(paths):
    """(driver, label, editor) for each configured mount point."""
    out = []
    for i, path in enumerate(paths[:MAX_MOUNTS]):
        out.append((MOUNT_DRIVERS[i], 'Capacity %s' % path, E_PCT))
    return out


def all_drivers():
    """Every driver the node can ever carry, for the node driver table."""
    out = [('ST', 'Status', E_BOOL)]
    for metric in METRICS:
        if metric.dynamic:
            out.extend(mount_drivers(['x'] * MAX_MOUNTS))
        else:
            out.extend(metric.drivers)
    return out
