#!/usr/bin/env bash

set -euo pipefail

ACTION="${1:-all}"
BASE_URL="${BASE_URL:-http://127.0.0.1:28003/api/v1}"
OWNER_ID="${OWNER_ID:-test-user}"
CREATED_BY="${CREATED_BY:-test-user}"
NAME_PREFIX="${NAME_PREFIX:-doc-ingestion-test}"
KB_ID="${KB_ID:-}"
DOC_ID="${DOC_ID:-}"
FILE_PATH="${FILE_PATH:-}"
FILE_SIZE_MB="${FILE_SIZE_MB:-1}"
FILE_EXT="${FILE_EXT:-.md}"
CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${CURL_MAX_TIME:-120}"

ts="$(date +%Y%m%d%H%M%S)"
kb_name="${NAME_PREFIX}-${ts}"
tmp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

usage() {
  cat <<EOF
Usage:
  $0 [all|create-kb|upload|get|list|index]

Environment:
  BASE_URL   API base url, default: http://127.0.0.1:28003/api/v1
  OWNER_ID   knowledge base owner_id, default: test-user
  CREATED_BY document created_by, default: test-user
  KB_ID      target knowledge base id, required for upload/list when not using all
  DOC_ID     target document id, required for get/index when not using all
  FILE_PATH  upload file path, default: generated markdown file
  FILE_SIZE_MB generated file size in MiB when FILE_PATH is empty, default: 1
  FILE_EXT   generated file extension when FILE_PATH is empty, default: .md
  CURL_CONNECT_TIMEOUT  curl connect timeout seconds, default: 5
  CURL_MAX_TIME         curl max request seconds, default: 120

Examples:
  $0 all
  $0 create-kb
  KB_ID=1 $0 upload
  KB_ID=1 $0 list
  DOC_ID=1 $0 get
  DOC_ID=1 $0 index
  KB_ID=1 FILE_PATH=tests/tmp/upload_5mb.txt $0 upload
  KB_ID=1 FILE_SIZE_MB=10 FILE_EXT=.txt $0 upload
  KB_ID=1 FILE_SIZE_MB=50 FILE_EXT=.md $0 upload
EOF
}

request_json() {
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

  assert_http_ok "${method}" "${path}" "${output}" "${curl_exit}" "${status_code}"
}

request_upload() {
  local output="$1"
  local status_code
  local curl_exit

  echo "request POST ${BASE_URL}/documents/upload"
  set +e
  status_code="$(curl -sS -X POST "${BASE_URL}/documents/upload" \
    --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
    --max-time "${CURL_MAX_TIME}" \
    -F "kb_id=${KB_ID}" \
    -F "created_by=${CREATED_BY}" \
    -F "source_type=upload" \
    -F "file=@${FILE_PATH}" \
    -o "${output}" \
    -w "%{http_code}")"
  curl_exit=$?
  set -e

  assert_http_ok "POST" "/documents/upload" "${output}" "${curl_exit}" "${status_code}"
}

assert_http_ok() {
  local method="$1"
  local path="$2"
  local output="$3"
  local curl_exit="$4"
  local status_code="$5"

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

require_doc_id() {
  if [[ -z "${DOC_ID}" ]]; then
    echo "DOC_ID is required for action: ${ACTION}" >&2
    usage >&2
    exit 1
  fi
}

ensure_file_path() {
  if [[ -n "${FILE_PATH}" ]]; then
    if [[ ! -f "${FILE_PATH}" ]]; then
      echo "FILE_PATH does not exist: ${FILE_PATH}" >&2
      exit 1
    fi
    return
  fi

  if [[ "${FILE_EXT}" != .* ]]; then
    FILE_EXT=".${FILE_EXT}"
  fi

  FILE_PATH="${tmp_dir}/document_ingestion_sample_${FILE_SIZE_MB}mb${FILE_EXT}"
  python3 - "$FILE_PATH" "$FILE_SIZE_MB" "$FILE_EXT" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
size_mb = int(sys.argv[2])
ext = sys.argv[3].lower()
target_size = size_mb * 1024 * 1024

if target_size <= 0:
    raise SystemExit("FILE_SIZE_MB must be greater than 0")

if ext in {".txt", ".md", ".markdown"}:
    seed = (
        "# Document Ingestion Test\n\n"
        "This file is generated by tests/test_document_ingestion.sh.\n"
        "It is used to validate upload size, file type, loader and splitter behavior.\n\n"
    ).encode("utf-8")
    with path.open("wb") as f:
        written = 0
        while written < target_size:
            chunk = seed[: target_size - written]
            f.write(chunk)
            written += len(chunk)
else:
    with path.open("wb") as f:
        f.write(b"\0" * target_size)
PY
  echo "generated upload file: ${FILE_PATH} (${FILE_SIZE_MB} MiB, ${FILE_EXT})"
}

build_kb_body() {
  python3 - "$kb_name" "$OWNER_ID" <<'PY'
import json
import sys

name, owner_id = sys.argv[1], sys.argv[2]
print(json.dumps({
    "name": name,
    "owner_id": owner_id,
    "description": "document ingestion shell test",
    "visibility": "private",
    "embedding_model": "text-embedding-3-small",
    "chunk_size": 600,
    "chunk_overlap": 100,
    "retrieval_top_k": 5,
}, ensure_ascii=False))
PY
}

run_create_kb() {
  local body
  local output

  body="$(build_kb_body)"
  output="${tmp_dir}/create_kb.json"
  request_json POST "/knowledge-bases" "${body}" "${output}"
  print_response "create-kb" "${output}"
  KB_ID="$(json_get "${output}" id)"
  echo "create-kb passed, KB_ID=${KB_ID}"
}

run_upload() {
  local output

  require_kb_id
  ensure_file_path
  output="${tmp_dir}/upload_document.json"
  request_upload "${output}"
  print_response "upload" "${output}"
  DOC_ID="$(json_get "${output}" id)"
  echo "upload passed, DOC_ID=${DOC_ID}, FILE_PATH=${FILE_PATH}"
}

run_get() {
  local output

  require_doc_id
  output="${tmp_dir}/get_document.json"
  request_json GET "/documents/${DOC_ID}" "" "${output}"
  print_response "get" "${output}"
  echo "get passed, DOC_ID=${DOC_ID}"
}

run_list() {
  local output

  require_kb_id
  output="${tmp_dir}/list_documents.json"
  request_json GET "/documents?kb_id=${KB_ID}" "" "${output}"
  print_response "list" "${output}"
  echo "list passed, KB_ID=${KB_ID}"
}

run_index() {
  local output

  require_doc_id
  output="${tmp_dir}/index_document.json"
  request_json POST "/documents/${DOC_ID}/index" "" "${output}"
  print_response "index" "${output}"
  echo "index passed, DOC_ID=${DOC_ID}"
}

echo "BASE_URL=${BASE_URL}"

case "${ACTION}" in
  all)
    if [[ -z "${KB_ID}" ]]; then
      run_create_kb
    fi
    run_upload
    run_get
    run_list
    echo "document ingestion test passed, KB_ID=${KB_ID}, DOC_ID=${DOC_ID}"
    ;;
  create-kb)
    run_create_kb
    ;;
  upload)
    run_upload
    ;;
  get)
    run_get
    ;;
  list)
    run_list
    ;;
  index)
    run_index
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
