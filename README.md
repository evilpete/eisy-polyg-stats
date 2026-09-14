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

See [POLY_CONFIG.md](POLY_CONFIG.md) for the full table of metrics,
defaults and arguments -- it is also the help text shown inside PG3.


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


## Graceful degradation

Counters the host does not expose are reported as notices in PG3 and are
simply not sent: a machine with no readable thermal sensor, a mount point
that is not present, a NIC that reports no link speed.  A failure in one
collector never stops the rest of the poll.

Temperatures are read from `psutil.sensors_temperatures()` first, then from
`sysctl` (`dev.cpu.0.temperature`, `hw.acpi.thermal.tz0.temperature`),
`nvidia-smi` for the GPU, and `smartctl` for the drive.

## License

MIT, see [LICENSE](LICENSE).
