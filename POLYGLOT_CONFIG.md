## System Stats

Reports statistics for the machine the plugin runs on (the EISY / Polisy
itself, or any FreeBSD host) to IoX.

### display

Pick what the node shows.  One comma separated list, `+` enables a metric,
`-` disables it, and anything after `=` is that metric's argument:

```
+load_avg,-cpu_temp,+disk_capacity=/ /var /var/isy, -system_uptime
```

Metrics you do not mention keep their default.  Changing this parameter
rebuilds the node definition and re-installs the profile, so the node shows
only what you asked for -- **restart the IoX Admin Console afterwards** to
pick the new profile up.

| metric | default | argument | shows |
| --- | --- | --- | --- |
| `load_avg` | on | | 1, 5 and 15 minute load average |
| `cpu_util` | on | | CPU utilization percent |
| `cpu_temp` | on | | CPU temperature |
| `gpu_temp` | off | | GPU temperature |
| `disk_temp` | off | device, e.g. `/dev/ada0` | drive temperature |
| `mem_usage` | on | | memory used percent |
| `disk_capacity` | on | mount points, max 8 | capacity percent per filesystem |
| `disk_io_util` | on | | percent of time the disks were busy |
| `disk_iostats` | on | | read/write MB/s and IOPS |
| `net_util` | on | interface, e.g. `eth0` | link utilization percent, rx/tx kbit/s |
| `net_errors` | on | | errors + drops as percent of packets |
| `system_uptime` | on | | uptime in days |

### Other parameters

| key | default | meaning |
| --- | --- | --- |
| `temp_unit` | `C` | `C` or `F`, applies to every temperature |
| `io_interval` | `1` | seconds for the first disk I/O sample |

A metric may also be given its own parameter key instead of listing it in
`display`, which is easier to edit in the UI:

```
disk_capacity = / /var /var/isy
net_util      = wlan0
cpu_temp      = false
```

### Polling

The stats are refreshed on every **shortPoll** (30 seconds by default).
Rates -- disk I/O, network throughput and error percentages -- are averaged
over the interval between polls, so the first poll after a restart reports
only what it can measure immediately.

### Notices

Counters the host does not expose (no temperature sensor, a mount point that
is not present, a NIC with no reported link speed) are listed as notices and
are simply not reported.  Nothing else stops working.
