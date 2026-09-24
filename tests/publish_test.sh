#!/bin/bash
# tests/publish_test.sh — checks the commit-and-push block of scripts/daily.sh without running daily.sh itself.
# It copies the lines between "# --- publish: begin" and "# --- publish: end" and runs them in a throwaway
# repository whose origin is a local bare repository, so nothing reaches the network. Each case asserts the
# "result" written to data/push-status.state.json and whether the remote's main moved.
#   bash tests/publish_test.sh [path/to/daily.sh]        exit 0 = every case passed
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DAILY=${1:-$HERE/../scripts/daily.sh}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
sed -n '/^# --- publish: begin/,/^# --- publish: end/p' "$DAILY" > "$T/block.sh"
grep -q '^publish() {' "$T/block.sh" && grep -q '^committed=ok' "$T/block.sh" \
  || { echo "FAIL: could not copy the block out of $DAILY"; exit 2; }
git init -q --bare "$T/remote.git"
( git init -q "$T/seed" && cd "$T/seed" && mkdir -p data && echo '{"origins":[]}' > data/origins.json \
  && echo '{"n":0}' > data/data-xx.json && git add -A && git -c user.name=t -c user.email=t@example.test commit -qm seed \
  && git branch -M main && git push -q "$T/remote.git" main ) || { echo "FAIL: could not build the test remote"; exit 2; }
pass=0; fail=0; n=0
fresh() { cd "$T" || exit 2; rm -rf "$T/work"; git clone -q "$T/remote.git" "$T/work"; cd "$T/work" || exit 2; }   # step out before deleting
run() { LOG="data/daily.log"; say() { echo "[test] $*" >> "$LOG"; }; source "$T/block.sh"; }   # one run of the block
data() { n=$((n+1)); echo "{\"n\":$n}" > data/data-xx.json; }
check() { mkdir -p scripts; printf '#!/bin/bash\n%s\n' "$1" > scripts/prepush-check.local; chmod +x scripts/prepush-check.local; }
remote_tip() { git ls-remote "$T/remote.git" refs/heads/main | cut -f1; }
expect() {  # expect <case> <result> <remote moved: yes|no> <remote tip before>
  local got moved; got=$(sed -n 's/.*"result": "\([a-z-]*\)".*/\1/p' data/push-status.state.json 2>/dev/null)
  [ "$(remote_tip)" != "$4" ] && moved=yes || moved=no
  if [ "$got" = "$2" ] && [ "$moved" = "$3" ]; then pass=$((pass+1)); echo "PASS $1: $got, remote moved=$moved"
  else fail=$((fail+1)); echo "FAIL $1: got ${got:-nothing} (want $2), remote moved=$moved (want $3)"; fi
}
fresh; b=$(remote_tip); run; expect "no new data, nothing waiting" no-change no "$b"
fresh; b=$(remote_tip); data; run; expect "new data, no local check" pushed yes "$b"
fresh; b=$(remote_tip); data; check 'exit 0'; run; expect "local check passes" pushed yes "$b"
fresh; b=$(remote_tip); data; check 'echo red; exit 3'; run; expect "local check blocks" blocked-by-check no "$b"
fresh; b=$(remote_tip); data; printf '#!/bin/sh\nexit 1\n' > .git/hooks/pre-push; chmod +x .git/hooks/pre-push; run
  expect "a local pre-push hook declines" refused-by-local-hook no "$b"
fresh; b0=$(remote_tip); ( git clone -q "$T/remote.git" "$T/other" && cd "$T/other" && echo x > other.txt && git add other.txt \
  && git -c user.name=t -c user.email=t@example.test commit -qm other && git push -q origin main ); rm -rf "$T/other"; b=$(remote_tip)
  data; run; expect "the remote has commits this clone lacks" rejected-by-remote no "$b"
fresh; b=$(remote_tip); git remote set-url origin git@unreachable-host.invalid:x/y.git; data; run
  expect "the remote cannot be reached" push-failed-network no "$b"
fresh; b=$(remote_tip); git update-ref -d refs/remotes/origin/main; check 'exit 0'; data; run
  expect "origin/main unknown, local check installed" not-pushed-no-base no "$b"
fresh; b=$(remote_tip); printf '#!/bin/sh\nexit 1\n' > .git/hooks/pre-commit; chmod +x .git/hooks/pre-commit; data; run
  expect "the commit fails" commit-failed no "$b"
fresh; b=$(remote_tip); data; check 'exit 3'; run; expect "retry 1/2: blocked this week" blocked-by-check no "$b"
  check 'exit 0'; run; expect "retry 2/2: no new data next week, the waiting commit goes out" pushed yes "$b"
fresh; b=$(remote_tip); url=$(git remote get-url origin); git remote set-url origin git@unreachable-host.invalid:x/y.git; data; run
  expect "retry 1/2: remote unreachable" push-failed-network no "$b"
  git remote set-url origin "$url"; run; expect "retry 2/2: reachable again, no new data" pushed yes "$b"
echo "RESULT: $pass passed, $fail failed"
[ "$fail" = 0 ]
