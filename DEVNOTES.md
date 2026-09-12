# Development notes / session handoff

Working state of the plugin as of the initial implementation, with the
decisions behind it and what is still open.  Read this first when picking the
work back up.

## Where things stand

Branch `claude/awesome-thompson-9dxg20`, no PR opened yet.  Feature complete
against the original request.

The first run on real EISY hardware failed with `Invalid driver` on every
driver; the cause and fix are under **PG3 owns the driver table** below.  That
run got as far as starting the node, loading Custom Parameters and polling, so
the plumbing is right -- but nothing has been seen in the Admin Console yet.
Re-test on hardware is the immediate next step.

## Layout

| path | role |
| --- | --- |
| `stats-poly.py` | entry point: `Interface` -> `StatsController` -> `ready()` -> `runForever()` |
| `sysstats/registry.py` | metric definitions, editor specs, the static driver slot map, and `catalog()`/`markdown_table()` behind the README table |
| `sysstats/config.py` | Custom Parameters parsing (`+metric,-metric,+metric=args,-GV36`) |
| `sysstats/metrics.py` | the collectors, `Collector.collect()` returns `{driver: value}` |
| `sysstats/profile.py` | generates nodedef / editors / NLS from the config |
| `sysstats/controller.py` | the single node, polling, notices, driver scaling |
| `profile/` | generated profile, committed at defaults, rewritten at run time |
| `tests/` | PG3 stand-in (`fake_pg3.py`) and the regression suite |
| `tools/update_docs.py` | regenerates the README metric table from the registry |

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

**Drivers can be blocked individually.**  `-GV36` in `display` (or
`GV36 = false` as its own key) drops one line without disabling its metric.
`config.Config.blocked` feeds `profile.driver_layout()`, so a blocked driver
leaves the node definition, and `controller.update()` skips it via
`self.reported`.  `ST` is refused because it is the node's status.  Blocking
is part of `config.signature()`, or the profile would not be rebuilt when it
changes.

**The README metric table is generated, not written.**  `registry.catalog()`
is the single source of truth, `tools/update_docs.py` renders it between the
markers in README.md, and a test fails when the two diverge -- so a new
metric cannot ship undocumented.  Run the tool after touching the registry.

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

**PG3 owns the driver table, so it has to be re-asserted.**  This is what
broke on the first hardware run.  `interface.py` (3.4.7, line ~800) does this
on *every* config message:

```python
if node['address'] in self.nodes_internal:
    n = self.nodes_internal[node['address']]
    n.updateDrivers(node['drivers'])   # self.drivers = deepcopy(drivers)
```

It replaces the node's driver table wholesale with PG3's database copy.  For a
node the database has only just learned about that copy is **empty**, so all
27 drivers disappear moments after `addNode()` and every `setDriver()` logs
`Invalid driver`, `ST` included.  A node object does not get to keep drivers
PG3 has not stored.

`controller.config_handler()` therefore subscribes to `CONFIG` and rebuilds
the table (`_restore_drivers()`), keeping the values and uoms PG3 does know,
and calls `addNode()` again when anything was missing so the database learns
the full set.  `setDriver()` also self-heals if it is ever handed a driver
that is not in the table, which covers a poll landing between the wipe and
the `CONFIG` event.  Re-adding only happens when the driver set actually
differs, so there is no addNode/config loop.

If drivers ever go quiet again, this is the first thing to check.

**Values are sent as themselves; IoX applies the editor precision.**  This
took three rounds on hardware to pin down, and the conclusion is not what the
first two rounds suggested, so the whole trail matters:

* `udi_interface` has no `prec` anywhere -- `setDriver` sends the value
  string as-is (verified by grepping the wheel).  Any decimal handling has to
  come from the editor in the profile.
* Sending `int(round(value * 10**prec))` on the assumption that IoX shifts
  the decimal back showed 330 for 33.0 degrees, 880 for 88% memory, 21142 for
  211.42 days.
* Sending the real float showed the same, so it looked like IoX was dropping
  the decimal point, and values were switched to whole numbers.
* Then `decimals = true` was tried on hardware and **worked**.

The difference was not the value format at all: it was that the profile had
finally been reinstalled.  `profile/version.txt` had sat at 1 through all of
this, so IoX kept serving the cached editors, which carry no usable
precision.  Once the version moved and the Admin Console was restarted, the
editors' `prec` was honoured and floats displayed correctly.

So the rule is: **send the real value, and make sure the profile version
moves whenever the profile changes.**  A value that comes out a power of ten
too large means a stale profile, not a formatting bug.

`decimals = false` remains as the fallback: every editor drops to prec 0,
values round to whole numbers, and `registry.EDITORS` gives `SS_LOAD` an
`int_scale` of 100 so load average survives, with `profile._nls()` appending
`(x100)` to any scaled driver -- a scaled value is never presented as the raw
measurement.

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

```
python3 tests/test_plugin.py      # 21 tests, no pytest and no EISY needed
python3 -m pyflakes stats-poly.py sysstats/*.py tests/*.py tools/*.py
python3 tools/update_docs.py      # after changing the registry
```

`tests/fake_pg3.py` stands in for PG3: it records what the plugin sends,
replays config messages (including the driver clobber above) and can fire
`CUSTOMPARAMS`, `START`, `POLL` and `STOP`.  It uses the **real**
`udi_interface.Node`, loaded straight from `node.py` so that paho-mqtt and
netifaces are not needed, and falls back to an equivalent stub when the
library is absent -- the line it prints at start up says which.  Testing
against the real Node is the point: the stub would not have reproduced the
hardware bug.

The suite covers the documented `display` syntax, per-metric parameters,
driver blocking, bad input becoming notices, profile generation and
idempotency, static driver slots, the driver-table clobber and its repair,
value formatting in both decimal modes, that disabled and blocked drivers are
never reported, and that the README table matches the registry.  The
regressions were each verified to fail against the code that had the bug, so
they are not vacuous.

Careful: the harness writes `profile/` in the repo working directory.
Regenerate the defaults before committing:

```
python3 -c "import sys; sys.path.insert(0,'.'); from sysstats import config, profile; profile.write(config.parse({'display': config.defaults_doc()}))"
echo 1 > profile/version.txt
```

## Not yet verified

* **Nothing has been seen in the IoX Admin Console yet.**  The one hardware
  run so far died on the driver clobber.  Development is otherwise on Linux.
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
* The `decimals = false` path is now the one nothing has exercised on
  hardware; it is kept as a fallback for a console serving a stale profile.
* **Whether PG3 accepts status for a driver that is not in the installed
  nodedef.**  The node keeps all 27 drivers while the nodedef shows a subset;
  IoX should ignore the rest, but watch the PG3 log for complaints.

## Next steps

1. Check every temperature source and the disk device guess on FreeBSD --
   the last substantial unknown.
2. Consider a GitHub Actions workflow so `tests/test_plugin.py` actually
   gates the PR; there is no CI in the repo today.
4. Extend the tests with faked `psutil` counters so the rate maths (kbit/s,
   IOPS, busy-time percent, error percentage) is covered by arithmetic rather
   than by whatever the host happens to be doing.
5. Consider: swap usage, per-CPU utilization, a configurable interface list
   rather than a single NIC, and ISY alert thresholds.
6. Open a PR when hardware testing passes.

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
* `profile.PROFILE_DIR` is where generated files land; the tests point it at
  a temp dir so a run cannot rewrite the profile shipped in the repo.  An ad
  hoc script that calls `profile.write(cfg)` without doing that **will**
  rewrite the committed defaults -- regenerate as above before committing.
* When the generated profile changes, `profile/version.txt` must end up
  higher than the version already installed on the ISY, and `server.json`'s
  `profile_version` should be bumped too.  Currently 3 and 1.0.2.  This is
  not bookkeeping: a version that does not move is why the decimal display
  looked broken for two rounds (above).  Restart the Admin Console after a
  profile change, or it keeps rendering with the editors it already has.
* Patch scripts that edit source by string replacement must assert the match:
  a silent no-op cost a round here when a literal `°` did not match `\u00b0`.
