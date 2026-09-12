# Development notes / session handoff

Working state of the plugin as of the initial implementation, with the
decisions behind it and what is still open.  Read this first when picking the
work back up.

## Where things stand

Branch `claude/awesome-thompson-9dxg20`, commit "Add lightweight
EISY/Polyglot v3 system stats plugin".  No PR opened yet.  The plugin is
feature complete against the original request and runs clean, but see
**Not yet verified** below -- it has never run on real EISY/FreeBSD hardware.

## Layout

| path | role |
| --- | --- |
| `stats-poly.py` | entry point: `Interface` -> `StatsController` -> `ready()` -> `runForever()` |
| `sysstats/registry.py` | metric definitions, editor specs, the static driver slot map |
| `sysstats/config.py` | Custom Parameters parsing (`+metric,-metric,+metric=args`) |
| `sysstats/metrics.py` | the collectors, `Collector.collect()` returns `{driver: value}` |
| `sysstats/profile.py` | generates nodedef / editors / NLS from the config |
| `sysstats/controller.py` | the single node, polling, notices, driver scaling |
| `profile/` | generated profile, committed at defaults, rewritten at run time |

Data flow per poll: `POLL` -> `controller.update()` -> `Collector.collect()`
-> `controller.setDriver()` (scales) -> `udi_interface`.

## Key decisions

**The ISY profile is generated, not static.**  `profile.write()` builds
`nodedef/nodedefs.xml`, `editor/editors.xml` and `nls/en_us.txt` from the
resolved config at start up, so the node shows only enabled metrics, each
filesystem is labelled with its own mount point, and the temperature editor
carries the configured unit.  Files are only rewritten -- and
`poly.updateProfile()` only called -- when the content actually changes, and
`profile/version.txt` is bumped on change because IoX caches by version.
Cost: the Admin Console must be restarted after a config change.  The repo
ships the default profile so a fresh install has valid files before the
plugin ever runs.

**Driver slots are static, not packed.**  `registry.py` hands each metric a
fixed driver (load = GV0-GV2, cpu_util = GV3, temps = GV4-GV6, mem = GV7,
mounts = GV10-GV17, disk io = GV20-GV24, net = GV30-GV33, uptime = GV34).  A
metric therefore keeps its driver across a re-configure and IoX programs
referencing it do not silently repoint.  Do not renumber these.

**The node declares every possible driver** (`all_drivers()`), the generated
node definition selects which are displayed.  This sidesteps an ordering
problem: `addNode()` happens in `__init__`, before Custom Parameters arrive,
so the driver table cannot depend on the config.  Disabled drivers are simply
never written.

**Values are scaled integers.**  `udi_interface` 3.4.7's
`Node.setDriver(driver, value, report, force, uom, text)` has no `prec`
parameter (verified against the wheel, not from memory).  ISY's convention is
that the editor's `prec` shifts the decimal, so `controller.setDriver()`
overrides the base method to send `int(round(value * 10**prec))` -- load 1.07
is sent as `107` under `prec="2"`.  If a value ever looks 10x/100x off in the
Admin Console, this is the first place to look.

**One snapshot per counter set per poll.**  Both disk metrics share one
`psutil.disk_io_counters()` sample and both network metrics share one
`net_io_counters()` sample, taken at the top of `collect()`.  This was a real
bug found in testing: each metric used to re-sample, so the second one
differenced against a baseline microseconds old -- rx and tx came out
identical and the error percentage was pinned at 0.

**No poll blocks.**  Rates are differenced between consecutive polls.  The
single exception is the first disk I/O sample after a restart, which calls
`get_disk_io_utilization(interval)` (the function from the original request,
kept verbatim) and sleeps `io_interval` seconds.

**Degrade, never fail.**  A missing counter returns `None` and is not
reported; `_warn_once()` logs it once and records it, and the controller
mirrors those into PG3 notices.  Every collector call is individually wrapped
so one bad counter cannot abort the poll.

## Configuration contract

`display` is one comma separated list; `+` enables, `-` disables, `=` takes
arguments; unmentioned metrics keep their default:

```
+load_avg,-cpu_temp,+disk_capacity=/ /var /var/isy, -system_uptime
```

A metric may instead take its own parameter key (`net_util = wlan0`,
`cpu_temp = false`).  Also `temp_unit` (C/F) and `io_interval`.  Unknown
metric or parameter names become notices rather than errors.  Full table in
`POLYGLOT_CONFIG.md`, which is also the in-PG3 help text.

## Testing

No test suite yet.  What was used during development:

* A fake `udi_interface` module injected into `sys.modules` drives
  `StatsController` end to end without PG3 or MQTT -- parameter handling,
  profile regeneration, polling, notices, stop.  It was written to the
  scratchpad and is **not committed**; rebuilding it is the fastest way to
  re-verify a change.  It must stub `Node` (with a `setDriver` that rejects
  unknown drivers), `Custom`, `Interface` and the topic constants.
* `python3 -m pyflakes stats-poly.py sysstats/*.py` is clean.
* Collectors were exercised directly on Linux; profile XML was parsed to
  confirm it is well formed.

Careful: the harness writes `profile/` in the repo working directory.
Regenerate the defaults before committing:

```
python3 -c "import sys; sys.path.insert(0,'.'); from sysstats import config, profile; profile.write(config.parse({'display': config.defaults_doc()}))"
echo 1 > profile/version.txt
```

## Not yet verified

* **Never run on EISY / Polisy / FreeBSD.**  Development was on a Linux
  container.
* **Temperature fallbacks.**  `sysctl dev.cpu.0.temperature` and
  `hw.acpi.thermal.tz0.temperature` are written from the documented FreeBSD
  OID layout but were never read from a real sensor.  `_as_temp()` guesses
  Kelvin vs decikelvin vs Celsius by magnitude -- check that against real
  output before trusting it.
* **Disk temperature.**  `root_disk_device()` strips partition suffixes with
  a regex (`ada0p2` -> `ada0`, `nvme0n1p1` -> `nvme0`); the nvme branch in
  particular is untested.  The `smartctl` path needs smartmontools installed.
* **UOM choices.**  Percent 51, Celsius 4, Fahrenheit 17, days 10 and raw 56
  are used.  Rates (MB/s, IOPS, kbit/s) fall back to raw 56 because no exact
  UOM was confirmed -- the unit lives in the NLS label instead.  If a better
  UOM exists, change it in `registry.EDITORS`.
* **`prec` scaling** has not been confirmed against a live Admin Console.

## Next steps

1. Install on the target EISY and confirm the node appears with the expected
   drivers, then check every temperature source and the disk device guess.
2. Confirm the scaled-integer display is right in the Admin Console.
3. Add a real test suite (pytest) around `config.parse`, `profile.write`
   idempotency and the rate math, with `psutil` faked -- and commit the fake
   `udi_interface` harness as a fixture.
4. Consider: swap files/swap usage, per-CPU utilization, a configurable
   interface list rather than a single NIC, and ISY alert thresholds.
5. Open a PR when hardware testing passes.

## Gotchas

* `profile/version.txt` must increase whenever the profile content changes or
  IoX serves the cached profile and the new drivers never appear.
* `poly.ready()` is called in `stats-poly.py` after the controller is
  constructed; `addNode()` happens inside `__init__`.  Custom Parameters
  arrive only after `ready()`, hence the `configured` flag and the fallback in
  `start()` that boots on defaults if no parameters were ever delivered.
* The node id is `SYSSTATS` and the NLS prefix is `SS`; they appear in
  `profile.py` and must match what the generated files and `server.json`
  describe.
* `server.json` carries `profile_version`; bump it on a release so PG3
  reinstalls the profile.
