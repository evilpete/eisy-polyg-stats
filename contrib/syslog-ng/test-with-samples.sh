#!/bin/sh
#############################################################################
# test-with-samples.sh -- run this configuration against the sample logs
#
# Builds a throwaway copy of eisy.d/ whose @define paths point at the
# sample files and whose remote destination is a local file, runs
# syslog-ng over it, and prints what would have gone on the wire in
# RFC5424 form.
#
#   ./test-with-samples.sh [sample-dir] [seconds]
#
# Requires syslog-ng >= 4.0 in $PATH.  Nothing is written outside $TMPDIR.
#############################################################################
set -eu

here=$(cd "$(dirname "$0")" && pwd)
samples=${1:-$here/samples}
runtime=${2:-8}

work=$(mktemp -d "${TMPDIR:-/tmp}/syslog-ng-eisy.XXXXXX")
trap 'rm -rf "$work"' EXIT

# --- stage the sample files in the directory layout the config expects ---
mkdir -p "$work/iox" "$work/var/log" "$work/pg3/logs" "$work/pg3/ns/plugin-1"
for f in DEV.LOG ERROR.LOG debug.log;             do [ -f "$samples/$f" ] && cp "$samples/$f" "$work/iox/"; done
for f in ZWAY.LOG ZBEE.LOG ZMAT.LOG ZBEE.ARCHIVE.LOG; do [ -f "$samples/$f" ] && cp "$samples/$f" "$work/var/log/"; done
# The sample debug.log has no trailing newline; a real, still-open log file
# always does.  Add one so the last record is not held as a partial line.
for f in "$work/iox"/* "$work/var/log"/*; do
    [ -f "$f" ] && [ -n "$(tail -c1 "$f")" ] && printf '\n' >> "$f"
done

[ -f "$samples/pg3-current.log" ] && cp "$samples/pg3-current.log" "$work/pg3/logs/"
[ -f "$samples/plugin.log" ]      && cp "$samples/plugin.log"      "$work/pg3/ns/plugin-1/"

# --- copy the config, repoint the paths, swap the destination -----------
cp -r "$here/eisy.d" "$work/eisy.d"
sed -e "s#^@define iox_log_dir .*#@define iox_log_dir \"$work/iox\"#" \
    -e "s#^@define zx_log_dir .*#@define zx_log_dir \"$work/var/log\"#" \
    -e "s#^@define pg3_log_dir .*#@define pg3_log_dir \"$work/pg3/logs\"#" \
    -e "s#^@define pg3_ns_dir .*#@define pg3_ns_dir \"$work/pg3/ns\"#" \
    "$here/eisy.d/00-options.conf" > "$work/eisy.d/00-options.conf"

cat > "$work/eisy.d/01-destinations.conf" <<EOF
# test stand-in for the real remote destination: same RFC5424 rendering,
# written to a local file instead of a TCP socket.
destination d_remote {
    file("$work/out.log"
        template("<\${PRI}>1 \${ISODATE} \${HOST} \${PROGRAM} \${PID} - \${SDATA} \${MESSAGE}\n")
    );
};
destination d_local_parsed { file("$work/out-parsed.log"); };
EOF

cat > "$work/syslog-ng.conf" <<EOF
@version: 4.2
@include "scl.conf"
@include "$work/eisy.d/"
EOF

echo "--- syntax check ---"
syslog-ng -s -f "$work/syslog-ng.conf" --no-caps
echo "syntax OK"

echo "--- running for ${runtime}s ---"
syslog-ng -F -f "$work/syslog-ng.conf" \
          --persist-file "$work/persist" --pidfile "$work/pid" \
          --control "$work/ctl" --no-caps --stderr >"$work/syslog-ng.err" 2>&1 &
ng=$!
i=0
while [ "$i" -lt "$runtime" ]; do sleep 1; i=$((i + 1)); done
kill "$ng" 2>/dev/null || true
wait "$ng" 2>/dev/null || true

grep -Ev 'smart-multi-line' "$work/syslog-ng.err" >&2 || true

echo "--- messages forwarded, per source ---"
awk '{print $4}' "$work/out.log" 2>/dev/null | sort | uniq -c
echo "--- input lines, per file (blank lines excluded) ---"
for f in "$samples"/*; do
    printf '%8d %s\n' "$(grep -cv '^[[:space:]]*$' "$f")" "$(basename "$f")"
done
unparsed=$(grep -c 'parse="unparsed"' "$work/out.log" 2>/dev/null || true)
echo "--- unparsed (forwarded verbatim): ${unparsed:-0} ---"
echo "--- first lines as they would go on the wire ---"
head -3 "$work/out.log" 2>/dev/null | cut -c1-200
