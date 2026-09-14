# Forwarding eisy / Polisy logs with syslog-ng

A syslog-ng configuration that tails the log files an eisy (or Polisy)
writes locally, parses each one, **keeps the timestamp that is written in
the file**, and forwards everything to a remote syslog server as RFC5424.

Nothing here is specific to a plugin — it is host-level log shipping for
the IoX, Z-Wave, Zigbee, Matter and Polyglot v3 logs.

## Layout

```
syslog-ng.conf              main file: version, scl.conf, include of eisy.d/
eisy.d/00-options.conf      paths, remote server, timezone, global options
eisy.d/01-destinations.conf the remote destination (TCP / TLS / RFC3164)
eisy.d/02-common.conf       shared filters, rewrites and parser blocks
eisy.d/10-iox-dev.conf      DEV.LOG
eisy.d/11-iox-error.conf    ERROR.LOG
eisy.d/12-iox-debug.conf    debug.log
eisy.d/20-zwave.conf        ZWAY.LOG
eisy.d/21-zigbee.conf       ZBEE.LOG
eisy.d/22-zmatter.conf      ZMAT.LOG
eisy.d/23-zigbee-archive.conf  ZBEE.ARCHIVE.LOG
eisy.d/30-pg3.conf          pg3-current.log
eisy.d/31-pg3-plugin.conf   plugin.log (all node servers, wildcard)
collector.conf.example      the receiving end
test-with-samples.sh        run the whole thing against samples/
samples/                    the sample logs the parsers were written against
```

One file per log keeps each format's quirks next to the parser that deals
with them; adding a log is a new file, not an edit to a large one.

## What each log looks like, and what happens to it

| File | Format | Facility / program | Parsed into |
| --- | --- | --- | --- |
| `DEV.LOG` | tab separated, CRLF, `node⇥driver⇥value⇥Sun 2026/09/13 23:13:16 ⇥flag⇥level` | `local0` / `iox-dev` | `node`, `driver`, `value` |
| `ERROR.LOG` | tab separated, bare CR before each record, `ts⇥flag⇥code⇥text` | `local1` / `iox-error` | `code`, severity `err` |
| `debug.log` | `2026-09-13 23:15:16 -  DBG1|ISY [T:…] text (file@line:func())` | `local5` / `iox-debug` | `lvl`, `subsys`, `thread` |
| `ZWAY.LOG` | `[2026-09-13 23:14:04.003] [I] [iox] text` | `local2` / `zway` | `lvl`, `module` |
| `ZBEE.LOG` | same bracketed format | `local3` / `zbee` | `lvl`, `module` |
| `ZMAT.LOG` | same bracketed format (also `[chip]` from the Matter SDK) | `local4` / `zmatter` | `lvl`, `module` |
| `ZBEE.ARCHIVE.LOG` | already RFC3164 (`newsyslog` rotation notices) | `local3` / `newsyslog` | syslog-ng's own syslog parser |
| `pg3-current.log` | `2026-09-13 01:01:07.464 [pg3] error: text` | `local6` / `pg3` | `component`, `lvl` |
| `plugin.log` | Python logging: `ts thread logger LEVEL text` | `local7` / `pg3-plugin` | `logger`, `thread`, `file` |

Distinct facilities mean the collector can split the streams with a
`facility()` filter without re-parsing anything.

### Timestamps

Every parser ends with a `date-parser()`, so the forwarded message carries
the time from the log line, not the time syslog-ng read it. That matters
when a file is being caught up after a restart, or when a plugin writes
late. Combined with `keep-timestamp(yes)`, `ts-format(iso)` and
`frac-digits(3)`, the wire format is
`2026-09-13T23:14:04.003+00:00` — millisecond resolution where the source
log has it.

None of these files records a timezone, so bare timestamps are read as
local time. If the host clock is UTC while the daemons log local time,
set `@define tz "time-zone(\"America/Los_Angeles\")"` in
`00-options.conf`; the value is pasted into every `date-parser()`.

### Severity

The level in each format is mapped onto a real syslog severity — `[E]` →
`err`, `[D]` → `debug`, Python `WARNING` → `warning`, and so on — so
`level(warning..emerg)` on the collector means what it says. Without the
mapping everything would arrive as `notice` and the level would only be
readable inside the text.

### Reformatting

The message body is rebuilt from the parsed fields (the redundant
timestamp and level columns are dropped, since they are now in the syslog
header), and the interesting fields are attached as RFC5424 structured
data under `eisy@32473`:

```
<134>1 2026-09-13T23:13:16.000-07:00 eisy iox-dev - - \
  [eisy@32473 node="ZB55147_001_1" driver="CLITEMP" value="62.17°F"] ZB55147_001_1 CLITEMP=62.17°F
```

32473 is the IANA example enterprise number; substitute your own if you
have one. A collector that understands structured data can then index
`node` or `driver` directly.

### Lines that do not parse

Every log path is a junction: the parsing channel is `flags(final)`, and a
second channel with `flags(fallback)` catches anything the parser rejects,
tags it `parse="unparsed"` and forwards it verbatim. A format change in a
future firmware release degrades to raw forwarding instead of silently
dropping records.

### Multi-line records

Python tracebacks in `plugin.log`, wrapped XML in `pg3-current.log` and
the IoX debug log are re-assembled with `multi-line-mode(regexp)` keyed on
the leading timestamp, so a traceback arrives as one message.
`multi-line-timeout(2)` flushes the last record instead of holding it
until the next line is written.

## Install

FreeBSD (eisy / Polisy):

```sh
pkg install syslog-ng

install -d /usr/local/etc/syslog-ng /var/db/syslog-ng
cp syslog-ng.conf      /usr/local/etc/syslog-ng.conf
cp -R eisy.d           /usr/local/etc/syslog-ng/

# edit at least the remote host and the log directories
vi /usr/local/etc/syslog-ng/eisy.d/00-options.conf

syslog-ng -s -f /usr/local/etc/syslog-ng.conf      # syntax check
sysrc syslog_ng_enable=YES
service syslog-ng start
```

On Linux, install `syslog-ng.conf` as `/etc/syslog-ng/syslog-ng.conf`,
`eisy.d/` as `/etc/syslog-ng/eisy.d/`, and change `@define confdir` at the
top of `syslog-ng.conf` to `/etc/syslog-ng`.

Set in `eisy.d/00-options.conf`:

* `remote_host`, `remote_port` — the collector (601 = syslog over TCP,
  514 = legacy BSD syslog, 6514 with the TLS destination)
* `iox_log_dir`, `zx_log_dir`, `pg3_log_dir`, `pg3_ns_dir` — where the
  logs actually live on your box; the defaults follow a stock eisy
* `tz` — only if the host clock and the log timestamps disagree

Requires syslog-ng 4.x (tested against 4.3.1). It uses `regexp-parser()`,
`date-parser()`, `set-severity()`, `wildcard-file()` and `disk-buffer()`,
all of which are in the open source edition.

### Notes on running it

* **Rotation.** `newsyslog` rotates these files. syslog-ng follows by
  name and reopens after the rename, so no `newsyslog` change is needed;
  the `ZBEE.ARCHIVE.LOG` source exists to keep the rotation notices
  themselves.
* **Buffering.** The destination has a 64 MiB disk buffer in
  `/var/db/syslog-ng`, so a collector outage or a WAN blip is ridden out
  rather than dropped. Create the directory before starting.
* **Long lines.** The PG3 plugin-store record is a single line of several
  kilobytes, so that source sets `log-msg-size(262144)`; the collector
  needs the same or larger, otherwise it truncates.
* **Volume.** The `[D]` records in `ZWAY.LOG` / `ZBEE.LOG` are most of the
  bytes. `f_no_debug` and a commented `rate-limit()` filter in
  `02-common.conf` are there for when that is too much.
* **UTF-8.** `DEV.LOG` values contain `°` and `%`. They are forwarded as
  UTF-8 without a BOM; a strict RFC5424 collector may want
  `flags(syslog-protocol)` handling checked on its side.

## Testing

`test-with-samples.sh` builds a throwaway copy of the configuration whose
paths point at `samples/` and whose remote destination is a local file,
runs syslog-ng over it, and reports what would have gone on the wire:

```
$ ./test-with-samples.sh
--- syntax check ---
syntax OK
--- messages forwarded, per source ---
     25 iox-debug
     25 iox-dev
     13 iox-error
      1 newsyslog
     25 pg3
     25 pg3-plugin
     25 zbee
     25 zmatter
     24 zway
--- unparsed (forwarded verbatim): 0 ---
```

Every non-blank line of every sample file is accounted for, and none of
them falls through to the unparsed path. Nothing outside `$TMPDIR` is
touched, so it is safe to run on a workstation.

## The other end

`collector.conf.example` is a minimal receiving configuration: an RFC5424
`syslog()` source on TCP 601 with `keep-timestamp(yes)` (without it the
collector would stamp its own arrival time and the whole exercise would be
pointless), writing one file per host and program.
