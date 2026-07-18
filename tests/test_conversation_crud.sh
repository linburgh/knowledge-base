#!/usr/bin/env bash

set -euo pipefail

ACTION="${1:-all}"
BASE_URL="${BASE_URL:-http://127.0.0.1:28003/api/v1}"
KB_ID="${KB_ID:-}"
USER_ID="${USER_ID:-test-user}"
CONVERSATION_ID="${CONVERSATION_ID:-}"
MESSAGE_ID="${MESSAGE_ID:-}"
CITATION_ID="${CITATION_ID:-}"
DOCUMENT_ID="${DOCUMENT_ID:-1}"
CHUNK_ID="${CHUNK_ID:-1}"
CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${CURL_MAX_TIME:-30}"

ts="$(date +%Y%m%d%H%M%S)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

usage() {
  cat <<EOF
Usage:
  $0 [all|add|get|modify|list|add-message|list-messages|add-citation|list-citations|remove-citation|remove-message|remove]

Required environment:
  KB_ID              existing knowledge base ID; required by all and add

Resource IDs for individual actions:
  CONVERSATION_ID    conversation ID
  MESSAGE_ID         message ID
  CITATION_ID        citation ID
  DOCUMENT_ID        citation document ID, default: 1
  CHUNK_ID           citation chunk ID, default: 1

Other environment:
  BASE_URL            API base URL, default: http://127.0.0.1:28003/api/v1
  USER_ID             conversation user ID, default: test-user
  CURL_CONNECT_TIMEOUT  curl connect timeout seconds, default: 5
  CURL_MAX_TIME       curl max request seconds, default: 30

Examples:
  KB_ID=1 $0 all
  KB_ID=1 $0 add
  CONVERSATION_ID=1 $0 get
  CONVERSATION_ID=1 $0 add-message
  MESSAGE_ID=1 KB_ID=1 DOCUMENT_ID=2 CHUNK_ID=3 $0 add-citation
  CITATION_ID=1 $0 remove-citation
  MESSAGE_ID=1 $0 remove-message
  CONVERSATION_ID=1 $0 remove
EOF
}

request() {
  local method="$1"
  local path="$2"
  local output="$3"
  local body="${4:-}"
  local status_code
  local curl_exit

  echo "request ${method} ${BASE_URL}${path}"
  set +e
  if [[ -n "${body}" ]]; then
    status_code="$(curl -sS -X "${method}" "${BASE_URL}${path}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      -H "Content-Type: application/json" -d "${body}" \
      -o "${output}" -w "%{http_code}")"
    curl_exit=$?
  else
    status_code="$(curl -sS -X "${method}" "${BASE_URL}${path}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      -o "${output}" -w "%{http_code}")"
    curl_exit=$?
  fi
  set -e

  if [[ "${curl_exit}" -ne 0 ]]; then
    echo "curl failed: ${method} ${path}, exit=${curl_exit}" >&2
    cat "${output}" >&2 2>/dev/null || true
    exit 1
  fi
  if [[ "${status_code}" -lt 200 || "${status_code}" -ge 300 ]]; then
    echo "request failed: ${method} ${path}, status=${status_code}" >&2
    cat "${output}" >&2
    exit 1
  fi
}

json_get() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    value = json.load(f).get(sys.argv[2])
if value is None:
    raise SystemExit(f"missing key: {sys.argv[2]}")
print(value)
PY
}

print_response() {
  echo "$1 response:"
  python3 - "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
PY
}

assert_value() {
  local actual
  actual="$(json_get "$1" "$2")"
  if [[ "${actual}" != "$3" ]]; then
    echo "assert failed: $2, expected=$3, actual=${actual}" >&2
    cat "$1" >&2
    exit 1
  fi
}

assert_array() {
  python3 - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    if not isinstance(json.load(f), list):
        raise SystemExit("assert failed: response must be an array")
PY
}

require_value() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "${value}" ]]; then
    echo "${name} is required for action: ${ACTION}" >&2
    usage >&2
    exit 1
  fi
}

build_conversation_body() {
  python3 - "$KB_ID" "$USER_ID" "$ts" <<'PY'
import json
import sys

print(json.dumps({
    "kb_id": int(sys.argv[1]),
    "user_id": sys.argv[2],
    "title": f"conversation-shell-test-{sys.argv[3]}",
    "status": "active",
}, ensure_ascii=False))
PY
}

build_modify_body() {
  cat <<'JSON'
{"title":"conversation-shell-test-modified","status":"archived"}
JSON
}

build_message_body() {
  cat <<'JSON'
{"role":"user","content":"conversation CRUD shell test question","metadata":{"source":"test_conversation_crud.sh"}}
JSON
}

build_citation_body() {
  python3 - "$DOCUMENT_ID" "$CHUNK_ID" <<'PY'
import json
import sys

print(json.dumps({
    "document_id": int(sys.argv[1]),
    "chunk_id": int(sys.argv[2]),
    "source_name": "conversation-crud-test.md",
    "page": 1,
    "snippet": "conversation CRUD citation snippet",
    "score": 0.95,
    "rank": 1,
}, ensure_ascii=False))
PY
}

run_add() {
  require_value KB_ID
  local output="${tmp_dir}/add.json"
  request POST "/conversations" "${output}" "$(build_conversation_body)"
  print_response add "${output}"
  CONVERSATION_ID="$(json_get "${output}" id)"
  assert_value "${output}" kb_id "${KB_ID}"
  assert_value "${output}" user_id "${USER_ID}"
  echo "add passed, CONVERSATION_ID=${CONVERSATION_ID}"
}

run_get() {
  require_value CONVERSATION_ID
  local output="${tmp_dir}/get.json"
  request GET "/conversations/${CONVERSATION_ID}" "${output}"
  print_response get "${output}"
  assert_value "${output}" id "${CONVERSATION_ID}"
  echo "get passed"
}

run_modify() {
  require_value CONVERSATION_ID
  local output="${tmp_dir}/modify.json"
  request PUT "/conversations/${CONVERSATION_ID}" "${output}" "$(build_modify_body)"
  print_response modify "${output}"
  assert_value "${output}" id "${CONVERSATION_ID}"
  assert_value "${output}" title "conversation-shell-test-modified"
  assert_value "${output}" status archived
  echo "modify passed"
}

run_list() {
  local output="${tmp_dir}/list.json"
  request GET "/conversations?kb_id=${KB_ID}&user_id=${USER_ID}" "${output}"
  print_response list "${output}"
  assert_array "${output}"
  echo "list passed"
}

run_add_message() {
  require_value CONVERSATION_ID
  local output="${tmp_dir}/add-message.json"
  request POST "/conversations/${CONVERSATION_ID}/messages" "${output}" "$(build_message_body)"
  print_response add-message "${output}"
  MESSAGE_ID="$(json_get "${output}" id)"
  assert_value "${output}" conversation_id "${CONVERSATION_ID}"
  assert_value "${output}" role user
  echo "add-message passed, MESSAGE_ID=${MESSAGE_ID}"
}

run_list_messages() {
  require_value CONVERSATION_ID
  local output="${tmp_dir}/list-messages.json"
  request GET "/conversations/${CONVERSATION_ID}/messages" "${output}"
  print_response list-messages "${output}"
  assert_array "${output}"
  echo "list-messages passed"
}

run_add_citation() {
  require_value MESSAGE_ID
  require_value KB_ID
  local output="${tmp_dir}/add-citation.json"
  request POST "/conversations/messages/${MESSAGE_ID}/citations?kb_id=${KB_ID}" "${output}" "$(build_citation_body)"
  print_response add-citation "${output}"
  CITATION_ID="$(json_get "${output}" id)"
  assert_value "${output}" message_id "${MESSAGE_ID}"
  assert_value "${output}" kb_id "${KB_ID}"
  echo "add-citation passed, CITATION_ID=${CITATION_ID}"
}

run_list_citations() {
  require_value MESSAGE_ID
  local output="${tmp_dir}/list-citations.json"
  request GET "/conversations/messages/${MESSAGE_ID}/citations" "${output}"
  print_response list-citations "${output}"
  assert_array "${output}"
  echo "list-citations passed"
}

run_remove_citation() {
  require_value CITATION_ID
  local output="${tmp_dir}/remove-citation.json"
  request DELETE "/conversations/citations/${CITATION_ID}" "${output}"
  print_response remove-citation "${output}"
  assert_value "${output}" id "${CITATION_ID}"
  echo "remove-citation passed"
}

run_remove_message() {
  require_value MESSAGE_ID
  local output="${tmp_dir}/remove-message.json"
  request DELETE "/conversations/messages/${MESSAGE_ID}" "${output}"
  print_response remove-message "${output}"
  assert_value "${output}" id "${MESSAGE_ID}"
  echo "remove-message passed"
}

run_remove() {
  require_value CONVERSATION_ID
  local output="${tmp_dir}/remove.json"
  request DELETE "/conversations/${CONVERSATION_ID}" "${output}"
  print_response remove "${output}"
  assert_value "${output}" id "${CONVERSATION_ID}"
  assert_value "${output}" status deleted
  echo "remove passed"
}

echo "BASE_URL=${BASE_URL}"

case "${ACTION}" in
  all)
    require_value KB_ID
    run_add
    run_get
    run_modify
    run_list
    run_add_message
    run_list_messages
    run_add_citation
    run_list_citations
    run_remove_citation
    run_remove_message
    run_remove
    echo "conversation CRUD test passed"
    ;;
  add) run_add ;;
  get) run_get ;;
  modify) run_modify ;;
  list) run_list ;;
  add-message) run_add_message ;;
  list-messages) run_list_messages ;;
  add-citation) run_add_citation ;;
  list-citations) run_list_citations ;;
  remove-citation) run_remove_citation ;;
  remove-message) run_remove_message ;;
  remove|delete) run_remove ;;
  -h|--help|help) usage ;;
  *) echo "unknown action: ${ACTION}" >&2; usage >&2; exit 1 ;;
esac
