#!/bin/bash
# tests/update_test.sh — checks the update block at the top of scripts/daily.sh without running daily.sh itself.
# It copies the lines between "# --- update: begin" and "# --- update: end" and runs them in a throwaway clone of a
# local bare repository, so nothing reaches the network. The clone's own scripts/daily.sh is a stand-in that only
# prints how it was started, so a restart on new code shows up as that line.
#   bash tests/update_test.sh [path/to/daily.sh]        exit 0 = every case passed
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DAILY=${1:-$HERE/../scripts/daily.sh}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
sed -n '/^# --- update: begin/,/^# --- update: end/p' "$DAILY" > "$T/block.sh"
grep -q 'git pull --ff-only' "$T/block.sh" && grep -q 'SOL_UPDATED=1 exec bash scripts/daily.sh' "$T/block.sh" \
  || { echo "FAIL: could not copy the block out of $DAILY"; exit 2; }
G() { git -c user.name=t -c user.email=t@example.test "$@"; }
git init -q --bare "$T/remote.git"
( git init -q "$T/seed" && cd "$T/seed" && mkdir -p data scripts && echo '{"n":0}' > data/data-xx.json \
  && printf '#!/bin/bash\necho "RESTARTED SOL_UPDATED=${SOL_UPDATED:-}"\n' > scripts/daily.sh && git add -A \
  && G commit -qm seed && git branch -M main && git push -q "$T/remote.git" main ) || { echo "FAIL: could not build the test remote"; exit 2; }
pass=0; fail=0
fresh() { cd "$T" || exit 2; rm -rf "$T/work"; git clone -q "$T/remote.git" "$T/work"; cd "$T/work" || exit 2; mkdir -p data; }
upstream() {  # a new commit on the remote, made from another clone
  ( rm -rf "$T/other" && git clone -q "$T/remote.git" "$T/other" && cd "$T/other" && echo "$1" > "${2:-other.txt}" && git add -A \
    && G commit -qm "$1" && git push -q origin main ); rm -rf "$T/other"
}
run() {  # one start of the block in a subshell; prints its output, then EXIT=<code>
  ( LOG="data/daily.log"; LOCK="data/.daily.lock"; mkdir -p "$LOCK"; say() { echo "[test] $*" >> "$LOG"; }
    source "$T/block.sh"; echo "CONTINUED" ) 2>&1; echo "EXIT=$?"
}
expect() {  # expect <case> <output must contain> <HEAD moved: yes|no> <HEAD before> [result in the status file]
  local out=$6 moved got; [ "$(git rev-parse HEAD)" != "$4" ] && moved=yes || moved=no
  got=$(sed -n 's/.*"result": "\([a-z-]*\)".*/\1/p' data/push-status.state.json 2>/dev/null)
  if printf '%s' "$out" | grep -qF -- "$2" && [ "$moved" = "$3" ] && [ "$got" = "${5:-}" ]; then pass=$((pass+1)); echo "PASS $1"
  else fail=$((fail+1)); echo "FAIL $1: moved=$moved (want $3), status=${got:-none} (want ${5:-none}), output: $(printf '%s' "$out" | tr '\n' '|')"; fi
}
fresh; h=$(git rev-parse HEAD); o=$(run); expect "already up to date: the round goes on" $'CONTINUED\nEXIT=0' no "$h" "" "$o"
fresh; h=$(git rev-parse HEAD); upstream "new code"; o=$(run)
  expect "new commits: pull them and start again on the new code" "RESTARTED SOL_UPDATED=1" yes "$h" "" "$o"
  [ -d data/.daily.lock ] && { fail=$((fail+1)); echo "FAIL the lock is released before the restart"; } || { pass=$((pass+1)); echo "PASS the lock is released before the restart"; }
fresh; h=$(git rev-parse HEAD); echo local > local.txt; git add local.txt; G commit -qm local; h=$(git rev-parse HEAD); upstream "remote side"; o=$(run)
  expect "commits here and on the remote: stop, nothing computed" "EXIT=1" no "$h" not-run-pull-failed "$o"
  grep -q 'git pull --ff-only failed' data/daily.log && { pass=$((pass+1)); echo "PASS the log says why"; } || { fail=$((fail+1)); echo "FAIL the log says why"; }
fresh; h=$(git rev-parse HEAD); git remote set-url origin git@unreachable-host.invalid:x/y.git; o=$(run)
  expect "no network: stop, nothing computed" "EXIT=1" no "$h" not-run-pull-failed "$o"
fresh; h=$(git rev-parse HEAD); upstream '{"n":9}' data/data-xx.json; echo '{"n":5}' > data/data-xx.json; o=$(run)
  expect "an uncommitted change the pull would overwrite: stop" "EXIT=1" no "$h" not-run-pull-failed "$o"
fresh; h=$(git rev-parse HEAD); upstream "more code"; o=$(SOL_UPDATED=1; export SOL_UPDATED; run)
  expect "second start (SOL_UPDATED set): no pull, the round goes on" $'CONTINUED\nEXIT=0' no "$h" "" "$o"
echo "RESULT: $pass passed, $fail failed"
[ "$fail" = 0 ]
