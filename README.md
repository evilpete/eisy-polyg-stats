# eisy-polyg-stats

A lightweight [Universal Devices](https://www.universal-devices.com/) EISY /
Polyglot v3 plugin that monitors the local FreeBSD host and reports its system
statistics to IoX.  Built on `udi_interface` and
[`psutil`](https://github.com/giampaolo/psutil), no agents and no network
calls -- it reads the machine it runs on.

## What it reports

One node, `System Stats`, with a driver per metric:

* **Load average** -- 1, 5 and 15 minute
* **CPU utilization** -- percent since the previous poll
* **Temperatures** -- CPU, GPU and disk, in °C or °F
* **Memory used** -- percent
* **Filesystem capacity** -- percent used, per mount point (`/`, `/home`,
  `/var/isy` by default, up to 8)
* **Disk I/O utilization** -- percent of wall time the disks were busy,
  from `busy_time`
* **Disk I/O statistics** -- read and write MB/s, read and write IOPS
* **Network utilization** -- percent of link speed plus rx/tx kbit/s for
  `eth0`, `wlan0` or whichever interface you name
* **Network errors** -- errors + drops as a percent of packets handled
* **System uptime** -- days, hours and minutes

## Configuration

Everything is selectable from **Custom Parameters**.  The `display`
parameter takes one comma separated list where `+` enables a metric, `-`
disables it, and anything after `=` is that metric's argument:

```
display = +load_avg,-cpu_temp,+disk_capacity=/ /var /var/isy, -system_uptime
```

Metrics that are not mentioned keep their default.  A metric can also be
given its own parameter key, which is easier to edit in the PG3 UI:

```
disk_capacity = / /var /var/isy
net_util      = wlan0
cpu_temp      = false
temp_unit     = F
```

See [POLYGLOT_CONFIG.md](POLYGLOT_CONFIG.md) for the full table of metrics,
defaults and arguments -- it is also the help text shown inside PG3.

### Values are whole numbers

IoX has been seen displaying the digits it is sent with the decimal point
removed, so 33.0 °C arrives as **330**.  Every value is therefore rounded to
a whole number.  Load average would be meaningless that way, so it is sent
x100 under a label that says so -- *Load Average 1 min (x100)* reading 36 is
a load of 0.36.  Set `decimals = true` if your IoX honours the editor
precision and you want the fractional digits back.

### The node definition follows the configuration

The ISY profile (node definition, editors and NLS) is **generated from the
configuration at start up**, so the node shows only the metrics you enabled,
each filesystem is labelled with its own mount point, and the temperature
editor carries the unit you chose.  When the configuration changes the
profile is rewritten and re-installed automatically; **restart the IoX Admin
Console** afterwards so it loads the new profile.

Driver slots are assigned statically -- a metric keeps the same driver across
a re-configure, so programs that reference it keep working.

## Installation

From the PG3 store, or manually:

```
cd ~/.polyglot/nodeservers
git clone https://github.com/evilpete/eisy-polyg-stats.git
cd eisy-polyg-stats
./install.sh
```

Then add the plugin in PG3 as a local plugin.  Requires Python 3.7+,
`udi_interface` 3.x and `psutil` 5.9+.

## Polling

Stats refresh on every **shortPoll** (30 s by default, set in `server.json`
or in the PG3 UI).  Rate metrics are differenced between consecutive polls so
no poll blocks; the one exception is the first disk I/O sample after a
restart, which takes a live `io_interval` second reading:

```python
def get_disk_io_utilization(interval=1):
    before = psutil.disk_io_counters()
    time.sleep(interval)
    after = psutil.disk_io_counters()
    busy_ms = after.busy_time - before.busy_time
    return min(busy_ms / (interval * 1000) * 100, 100)
```

## Graceful degradation

Counters the host does not expose are reported as notices in PG3 and are
simply not sent: a machine with no readable thermal sensor, a mount point
that is not present, a NIC that reports no link speed.  A failure in one
collector never stops the rest of the poll.

Temperatures are read from `psutil.sensors_temperatures()` first, then from
`sysctl` (`dev.cpu.0.temperature`, `hw.acpi.thermal.tz0.temperature`),
`nvidia-smi` for the GPU, and `smartctl` for the drive.

## Tests

```
python3 tests/test_plugin.py
```

No pytest, no EISY and no MQTT required -- `tests/fake_pg3.py` stands in for
PG3 and drives the node end to end.

## Layout

```
stats-poly.py        entry point
sysstats/registry.py metric definitions and driver slot map
sysstats/config.py   Custom Parameters parsing
sysstats/metrics.py  the collectors
sysstats/profile.py  nodedef / editors / NLS generation
sysstats/controller.py the node
profile/             generated profile, regenerated at run time
tests/               PG3 stand-in and the regression suite
```

## License

MIT, see [LICENSE](LICENSE).
