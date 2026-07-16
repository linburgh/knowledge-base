#!/usr/bin/env bash

set -euo pipefail

ACTION="${1:-all}"
BASE_URL="${BASE_URL:-http://127.0.0.1:28003/api/v1}"
OWNER_ID="${OWNER_ID:-test-user}"
NAME_PREFIX="${NAME_PREFIX:-kb-shell-test}"
KB_ID="${KB_ID:-}"
PAGE="${PAGE:-1}"
PAGE_SIZE="${PAGE_SIZE:-20}"
CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${CURL_MAX_TIME:-30}"

ts="$(date +%Y%m%d%H%M%S)"
kb_name="${NAME_PREFIX}-${ts}"
modified_name="${kb_name}-modified"
tmp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

usage() {
  cat <<EOF
Usage:
  $0 [all|add|list|page|get|modify|remove]

Environment:
  BASE_URL   API base url, default: http://127.0.0.1:28003/api/v1
  OWNER_ID   request owner_id, default: test-user
  KB_ID      target knowledge base id, required for get/modify/remove
  PAGE       list page, default: 1
  PAGE_SIZE  list page size, default: 20
  CURL_CONNECT_TIMEOUT  curl connect timeout seconds, default: 5
  CURL_MAX_TIME         curl max request seconds, default: 30

Examples:
  $0 all
  $0 add
  $0 list
  $0 page
  KB_ID=1 $0 get
  KB_ID=1 $0 modify
  KB_ID=1 $0 remove
EOF
}

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local output="$4"
  local status_code
  local curl_exit

  echo "request ${method} ${BASE_URL}${path}"
  set +e
  if [[ -n "${body}" ]]; then
    status_code="$(curl -sS -X "${method}" "${BASE_URL}${path}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      -H "Content-Type: application/json" \
      -d "${body}" \
      -o "${output}" \
      -w "%{http_code}")"
    curl_exit=$?
  else
    status_code="$(curl -sS -X "${method}" "${BASE_URL}${path}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      -o "${output}" \
      -w "%{http_code}")"
    curl_exit=$?
  fi
  set -e

  if [[ "${curl_exit}" -ne 0 ]]; then
    echo "curl failed: ${method} ${path}, curl_exit=${curl_exit}, http_status=${status_code}" >&2
    if [[ -s "${output}" ]]; then
      echo "response:" >&2
      cat "${output}" >&2
    fi
    exit 1
  fi

  if [[ "${status_code}" -lt 200 || "${status_code}" -ge 300 ]]; then
    echo "request failed: ${method} ${path}, status=${status_code}" >&2
    echo "response:" >&2
    cat "${output}" >&2
    exit 1
  fi
}

json_get() {
  local file="$1"
  local key="$2"

  python3 - "$file" "$key" <<'PY'
import json
import sys

path, key = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
value = data.get(key)
if value is None:
    raise SystemExit(f"missing key: {key}")
print(value)
PY
}

assert_json_value() {
  local file="$1"
  local key="$2"
  local expected="$3"
  local actual

  actual="$(json_get "${file}" "${key}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "assert failed: ${key}, expected=${expected}, actual=${actual}" >&2
    echo "response:" >&2
    cat "${file}" >&2
    exit 1
  fi
}

assert_page_response() {
  local file="$1"
  local expected_page="$2"
  local expected_page_size="$3"

  python3 - "$file" "$expected_page" "$expected_page_size" <<'PY'
import json
import sys

path, expected_page, expected_page_size = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with open(path, encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data.get("rows"), list):
    raise SystemExit("assert failed: rows must be list")
if not isinstance(data.get("total"), int):
    raise SystemExit("assert failed: total must be int")
if data.get("page") != expected_page:
    raise SystemExit(f"assert failed: page, expected={expected_page}, actual={data.get('page')}")
if data.get("page_size") != expected_page_size:
    raise SystemExit(
        f"assert failed: page_size, expected={expected_page_size}, actual={data.get('page_size')}"
    )
PY
}

print_response() {
  local title="$1"
  local file="$2"

  echo "${title} response:"
  python3 - "$file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
}

require_kb_id() {
  if [[ -z "${KB_ID}" ]]; then
    echo "KB_ID is required for action: ${ACTION}" >&2
    usage >&2
    exit 1
  fi
}

build_add_body() {
  python3 - "$kb_name" "$OWNER_ID" <<'PY'
import json
import sys

name, owner_id = sys.argv[1], sys.argv[2]
print(json.dumps({
    "name": name,
    "owner_id": owner_id,
    "description": "shell crud create",
    "visibility": "private",
    "embedding_model": "text-embedding-3-small",
    "chunk_size": 600,
    "chunk_overlap": 100,
    "retrieval_top_k": 5,
}, ensure_ascii=False))
PY
}

build_modify_body() {
  python3 - "$modified_name" "$OWNER_ID" <<'PY'
import json
import sys

name, owner_id = sys.argv[1], sys.argv[2]
print(json.dumps({
    "name": name,
    "owner_id": owner_id,
    "description": "shell crud modify",
    "visibility": "private",
    "embedding_model": "text-embedding-3-small",
    "chunk_size": 800,
    "chunk_overlap": 100,
    "retrieval_top_k": 8,
}, ensure_ascii=False))
PY
}

build_remove_body() {
  cat <<'JSON'
{}
JSON
}

run_add() {
  local body
  local output

  body="$(build_add_body)"
  output="${tmp_dir}/add.json"
  request POST "/knowledge-bases" "${body}" "${output}"
  print_response "add" "${output}"
  KB_ID="$(json_get "${output}" id)"
  assert_json_value "${output}" name "${kb_name}"
  assert_json_value "${output}" owner_id "${OWNER_ID}"
  echo "add passed, KB_ID=${KB_ID}"
}

run_get() {
  local output

  require_kb_id
  output="${tmp_dir}/get.json"
  request GET "/knowledge-bases/${KB_ID}" "" "${output}"
  print_response "get" "${output}"
  assert_json_value "${output}" id "${KB_ID}"
  echo "get passed, KB_ID=${KB_ID}"
}

run_list() {
  local output

  output="${tmp_dir}/list.json"
  request GET "/knowledge-bases?owner_id=${OWNER_ID}" "" "${output}"
  print_response "list" "${output}"
  echo "list passed"
}

run_page() {
  local output

  output="${tmp_dir}/page.json"
  request GET "/knowledge-bases/page?owner_id=${OWNER_ID}&page=${PAGE}&page_size=${PAGE_SIZE}" "" "${output}"
  print_response "page" "${output}"
  assert_page_response "${output}" "${PAGE}" "${PAGE_SIZE}"
  echo "page passed"
}

run_modify() {
  local body
  local output

  require_kb_id
  body="$(build_modify_body)"
  output="${tmp_dir}/modify.json"
  request PUT "/knowledge-bases/${KB_ID}" "${body}" "${output}"
  print_response "modify" "${output}"
  assert_json_value "${output}" id "${KB_ID}"
  assert_json_value "${output}" name "${modified_name}"
  assert_json_value "${output}" description "shell crud modify"
  echo "modify passed, KB_ID=${KB_ID}"
}

run_remove() {
  local output

  require_kb_id
  # DELETE 当前接口不需要请求体，保留 build_remove_body 便于以后接口改为带 body 时扩展。
  build_remove_body >/dev/null
  output="${tmp_dir}/remove.json"
  request DELETE "/knowledge-bases/${KB_ID}" "" "${output}"
  print_response "remove" "${output}"
  assert_json_value "${output}" id "${KB_ID}"
  assert_json_value "${output}" status "deleted"
  echo "remove passed, KB_ID=${KB_ID}"
}

echo "BASE_URL=${BASE_URL}"

case "${ACTION}" in
  all)
    run_add
    run_list
    run_page
    run_get
    run_modify
    run_remove
    echo "knowledge base CRUD test passed"
    ;;
  add)
    run_add
    ;;
  list)
    run_list
    ;;
  page)
    run_page
    ;;
  get)
    run_get
    ;;
  modify)
    run_modify
    ;;
  remove | delete)
    run_remove
    ;;
  -h | --help | help)
    usage
    ;;
  *)
    echo "unknown action: ${ACTION}" >&2
    usage >&2
    exit 1
    ;;
esac
