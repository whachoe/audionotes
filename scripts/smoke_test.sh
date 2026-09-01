#!/usr/bin/env bash
# End-to-end smoke test against a running Copywaste Notes backend instance.
#
# Phase 3 (multi-user): there's no static API token anymore - auth is a real
# per-user session token, minted at the end of the Google sign-in flow. Get
# one by signing into the app once, then either:
#   - reading it out of Settings (if you add a debug display for it), or
#   - completing GET {BASE_URL}/api/google/auth/start in a browser yourself
#     and copying the `token` query param off the copywastenotes://auth
#     redirect it ends on.
#
# Usage:
#   scripts/smoke_test.sh [BASE_URL] [SESSION_TOKEN]
# or via env vars:
#   BASE_URL=https://notes.example.com SESSION_TOKEN=... scripts/smoke_test.sh
#
# Requires: curl, python3 (used only for JSON parsing, not to run the app).
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
SESSION_TOKEN="${2:-${SESSION_TOKEN:-}}"
SAMPLE_FILE="${SAMPLE_FILE:-${repo_root}/tests/fixtures/sample.wav}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-60}"
POLL_DELAY_SECONDS="${POLL_DELAY_SECONDS:-2}"

BASE_URL="${BASE_URL%/}"

if [[ -z "$SESSION_TOKEN" ]]; then
  echo "ERROR: SESSION_TOKEN must be provided (2nd arg, or SESSION_TOKEN env var). See the comment above for how to get one." >&2
  exit 1
fi

if [[ ! -f "$SAMPLE_FILE" ]]; then
  echo "ERROR: sample audio file not found at ${SAMPLE_FILE}" >&2
  exit 1
fi

AUTH_HEADER="Authorization: Bearer ${SESSION_TOKEN}"

pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1" >&2; exit 1; }

json_get() {
  # json_get '<json-string>' 'key' -> string value, or empty if null/missing.
  python3 -c '
import json, sys
data = json.loads(sys.argv[1])
value = data.get(sys.argv[2])
print(value if value is not None else "")
' "$1" "$2"
}

json_encode_markdown() {
  python3 -c '
import json, sys
print(json.dumps({"markdown": sys.argv[1]}))
' "$1"
}

echo "== Smoke test against ${BASE_URL} =="

echo "[1/6] Request without Authorization header is rejected"
status=$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/api/notes")
[[ "$status" == "401" ]] || fail "expected 401 without Authorization header, got ${status}"
pass "unauthenticated request got 401"

echo "[2/6] Upload sample audio file"
upload_response=$(curl -sS -X POST "${BASE_URL}/api/notes" \
  -H "$AUTH_HEADER" \
  -F "file=@${SAMPLE_FILE};type=audio/wav")
note_id=$(json_get "$upload_response" "id")
[[ -n "$note_id" ]] || fail "upload did not return a note id: ${upload_response}"
pass "uploaded note ${note_id}"

echo "[3/6] Poll GET /api/notes/{id} until processing_status == done"
final_status=""
for _ in $(seq 1 "$POLL_ATTEMPTS"); do
  detail=$(curl -sS "${BASE_URL}/api/notes/${note_id}" -H "$AUTH_HEADER")
  final_status=$(json_get "$detail" "processing_status")
  if [[ "$final_status" == "done" ]]; then
    break
  fi
  if [[ "$final_status" == "failed" ]]; then
    fail "note processing failed: ${detail}"
  fi
  sleep "$POLL_DELAY_SECONDS"
done
[[ "$final_status" == "done" ]] || fail "note did not reach 'done' within ${POLL_ATTEMPTS} attempts (last status: ${final_status})"
pass "note reached processing_status=done"

echo "[4/6] List endpoint accepts every sort_by value"
for sort_by in created_at duration_seconds status; do
  status=$(curl -s -o /dev/null -w '%{http_code}' -H "$AUTH_HEADER" \
    "${BASE_URL}/api/notes?sort_by=${sort_by}")
  [[ "$status" == "200" ]] || fail "GET /api/notes?sort_by=${sort_by} returned ${status}"
  pass "sort_by=${sort_by} -> 200"
done

echo "[5/6] PATCH .../status persists"
patch_response=$(curl -sS -X PATCH "${BASE_URL}/api/notes/${note_id}/status" \
  -H "$AUTH_HEADER" -H "Content-Type: application/json" \
  -d '{"status": "in_progress"}')
[[ "$(json_get "$patch_response" "status")" == "in_progress" ]] \
  || fail "PATCH response did not reflect new status: ${patch_response}"

verify_status=$(curl -sS "${BASE_URL}/api/notes/${note_id}" -H "$AUTH_HEADER")
[[ "$(json_get "$verify_status" "status")" == "in_progress" ]] \
  || fail "status did not persist across a fresh GET"
pass "PATCH .../status persists"

echo "[6/6] PUT .../transcript persists"
new_markdown=$'# Smoke test edit\n\nHand-edited by scripts/smoke_test.sh.\n'
put_payload=$(json_encode_markdown "$new_markdown")
put_response=$(curl -sS -X PUT "${BASE_URL}/api/notes/${note_id}/transcript" \
  -H "$AUTH_HEADER" -H "Content-Type: application/json" \
  -d "$put_payload")
[[ "$(json_get "$put_response" "transcript_markdown")" == "$new_markdown" ]] \
  || fail "PUT response did not echo the new markdown: ${put_response}"

verify_transcript=$(curl -sS "${BASE_URL}/api/notes/${note_id}" -H "$AUTH_HEADER")
[[ "$(json_get "$verify_transcript" "transcript_markdown")" == "$new_markdown" ]] \
  || fail "transcript did not persist across a fresh GET"
pass "PUT .../transcript persists"

echo
echo "All smoke tests passed."
