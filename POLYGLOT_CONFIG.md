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

### Blocking a single driver

A metric that publishes several lines can be trimmed by blocking a driver by
its ISY identifier, without disabling the metric itself:

```
display = +system_uptime,-GV36
```

keeps uptime but hides the minutes.  `-GV2` keeps load average without the 15
minute figure, `-GV24` keeps the disk I/O statistics without write IOPS.  The
identifiers are listed in the metric table in the README; `ST` is the node's
status and cannot be blocked.  A driver may also be blocked by its own
parameter key, `GV36 = false`.

| metric | default | argument | shows |
| --- | --- | --- | --- |
| `load_avg` | on | | 1, 5 and 15 minute load average |
| `cpu_util` | on | | CPU utilization percent |
| `cpu_temp` | on | | CPU temperature |
| `gpu_temp` | off | | GPU temperature |
| `disk_temp` | off | device, e.g. `/dev/ada0` | drive temperature |
| `mem_usage` | on | | memory used percent |
| `disk_capacity` | on | mount points, max 8 | capacity percent per filesystem (`GV10`-`GV17`) |
| `disk_io_util` | on | | percent of time the disks were busy |
| `disk_iostats` | on | | read/write MB/s and IOPS |
| `net_util` | on | interface, e.g. `eth0` | link utilization percent, rx/tx kbit/s |
| `net_errors` | on | | errors + drops as percent of packets |
| `system_uptime` | on | | uptime as days, hours and minutes |

### Other parameters

| key | default | meaning |
| --- | --- | --- |
| `temp_unit` | `C` | `C` or `F`, applies to every temperature |
| `io_interval` | `1` | seconds for the first disk I/O sample |
| `decimals` | `true` | see **Decimals** below |

### Decimals

IoX applies the precision the profile's editors declare, so values are sent
as themselves: a CPU temperature of 33.0, a load average of 0.36, 88.0%
memory.

That only works once IoX has actually **reloaded the profile**.  A profile
whose version has not changed is served from cache, and a stale editor drops
the decimal point -- 33.0 shows as **330**, 88.0% as **880**.  If you see
that, bump `profile/version.txt`, restart the plugin, then restart the Admin
Console.

`decimals = false` is the fallback if the values still come out a power of
ten too large: everything is rounded to a whole number, and load average --
meaningless as an integer -- is sent multiplied by 100 under a label that
says so, *Load Average 1 min (x100)* reading 36 for a load of 0.36.

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
