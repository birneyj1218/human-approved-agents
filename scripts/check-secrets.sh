#!/bin/sh
# Extra pre-push check alongside gitleaks: private IP ranges, personal
# addresses, real-looking tokens, Discord-style user IDs, internal names.
# Usage: sh scripts/check-secrets.sh   (exit 1 on any hit)
set -u
cd "$(dirname "$0")/.."
status=0

# tracked + untracked-but-not-ignored files, so it works before the first commit
files=$(git ls-files --cached --others --exclude-standard)
[ -n "$files" ] || { echo "check-secrets: no files found"; exit 1; }

check() {
  label=$1
  pattern=$2
  hits=$(printf '%s\n' "$files" | grep -v '^scripts/check-secrets.sh$' | xargs grep -nIiE "$pattern" 2>/dev/null | grep -vE "${3:-^$}")
  if [ -n "$hits" ]; then
    echo "FAIL: $label"
    echo "$hits"
    status=1
  fi
}

check "private IPv4 (10/8, 172.16/12, 192.168/16, 100.64/10)" '(^|[^0-9.])(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3})([^0-9]|$)'
check "personal email domains" '[A-Za-z0-9._%+-]+@(gmail|yahoo|outlook|hotmail|icloud|proton)\.'
check "real-looking API keys" '(sk|pk|rk)_(live|test)_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.|ghp_[A-Za-z0-9]{20,}|xox[bap]-|[MN][A-Za-z0-9_-]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}'
check "Discord-style snowflake IDs (17-20 digits)" '(^|[^0-9a-f])[0-9]{17,20}([^0-9a-f]|$)'

if [ "$status" -eq 0 ]; then echo "check-secrets: clean"; fi
exit $status
