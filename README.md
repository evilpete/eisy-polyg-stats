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

See [POLYGLOT_CONFIG.md](POLYGLOT_CONFIG.md) for the full table of metrics,
defaults and arguments -- it is also the help text shown inside PG3.


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
