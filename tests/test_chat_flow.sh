#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:28003/api/v1}"
KB_ID="${KB_ID:-}"
USER_ID="${USER_ID:-chat-test-user}"
CREATED_BY="${CREATED_BY:-chat-test-user}"
QUESTION="${QUESTION:-报销流程需要哪些材料？}"
TOP_K="${TOP_K:-5}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-60}"
CLEANUP="${CLEANUP:-true}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-}"
CONFIG_FILE="${CONFIG_FILE:-etc/app.yaml}"
CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${CURL_MAX_TIME:-120}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
auth_args=()
if [[ -n "${AUTH_TOKEN}" ]]; then
  auth_args=(-H "Authorization: Bearer ${AUTH_TOKEN}")
fi

ts="$(date +%Y%m%d%H%M%S)"
tmp_dir="$(mktemp -d)"
created_kb="false"

if [[ -z "${EMBEDDING_MODEL}" && -f "${CONFIG_FILE}" ]]; then
  EMBEDDING_MODEL="$(python3 - "${CONFIG_FILE}" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}
print((config.get("embedding") or {}).get("model") or "")
PY
)"
fi
EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-3-small}"

cleanup() {
  if [[ "${CLEANUP}" == "true" && "${created_kb}" == "true" && -n "${KB_ID}" ]]; then
    curl -sS -X DELETE "${BASE_URL}/knowledge-bases/${KB_ID}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      "${auth_args[@]}" >/dev/null 2>&1 || true
  fi
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

usage() {
  cat <<EOF
Usage:
  $0

Environment:
  BASE_URL       API base URL, default: http://127.0.0.1:28003/api/v1
  KB_ID          existing knowledge base ID; empty means create a temporary one
  USER_ID        chat user ID, default: chat-test-user
  CREATED_BY     document creator, default: chat-test-user
  QUESTION       question, default: 报销流程需要哪些材料？
  TOP_K          retrieval top-k, default: 5
  EMBEDDING_MODEL vector model for the temporary KB, default: read from etc/app.yaml
  CONFIG_FILE    config file used to read embedding.model, default: etc/app.yaml
  POLL_INTERVAL  document status polling interval seconds, default: 2
  POLL_ATTEMPTS  document status polling attempts, default: 60
  CLEANUP        soft-delete an automatically created KB after test, default: true
EOF
}

request_json() {
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
      "${auth_args[@]}" \
      -H "Content-Type: application/json" -d "${body}" \
      -o "${output}" -w "%{http_code}")"
    curl_exit=$?
  else
    status_code="$(curl -sS -X "${method}" "${BASE_URL}${path}" \
      --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
      --max-time "${CURL_MAX_TIME}" \
      "${auth_args[@]}" \
      -o "${output}" -w "%{http_code}")"
    curl_exit=$?
  fi
  set -e

  if [[ "${curl_exit}" -ne 0 || "${status_code}" -lt 200 || "${status_code}" -ge 300 ]]; then
    echo "request failed: ${method} ${path}, curl=${curl_exit}, status=${status_code}" >&2
    cat "${output}" >&2 2>/dev/null || true
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

build_kb_body() {
  python3 - "$ts" "$EMBEDDING_MODEL" <<'PY'
import json
import sys

print(json.dumps({
    "name": f"chat-flow-test-{sys.argv[1]}",
    "owner_id": "chat-test-owner",
    "description": "chat flow integration test",
    "visibility": "private",
    "embedding_model": sys.argv[2],
    "chunk_size": 600,
    "chunk_overlap": 100,
    "retrieval_top_k": 5,
}, ensure_ascii=False))
PY
}

build_chat_body() {
  python3 - "$KB_ID" "$USER_ID" "$QUESTION" "$TOP_K" <<'PY'
import json
import sys

print(json.dumps({
    "kb_id": int(sys.argv[1]),
    "user_id": sys.argv[2],
    "question": sys.argv[3],
    "top_k": int(sys.argv[4]),
}, ensure_ascii=False))
PY
}

run_create_kb() {
  local output="${tmp_dir}/kb.json"
  request_json POST "/knowledge-bases" "${output}" "$(build_kb_body)"
  print_response create-kb "${output}"
  KB_ID="$(json_get "${output}" id)"
  created_kb="true"
  echo "create-kb passed, KB_ID=${KB_ID}"
}

run_upload() {
  local file_path="${tmp_dir}/chat-flow.md"
  local output="${tmp_dir}/document.json"
  cat >"${file_path}" <<'EOF'
# 报销流程

员工提交报销时，需要准备发票、费用明细和直属负责人审批单。
财务审核通过后，报销款会按照公司付款周期发放。
EOF

  local status_code
  local curl_exit
  echo "request POST ${BASE_URL}/documents/upload"
  set +e
  status_code="$(curl -sS -X POST "${BASE_URL}/documents/upload" \
    --connect-timeout "${CURL_CONNECT_TIMEOUT}" \
    --max-time "${CURL_MAX_TIME}" \
    "${auth_args[@]}" \
    -F "kb_id=${KB_ID}" -F "created_by=${CREATED_BY}" \
    -F "source_type=upload" -F "file=@${file_path};type=text/markdown" \
    -o "${output}" -w "%{http_code}")"
  curl_exit=$?
  set -e
  if [[ "${curl_exit}" -ne 0 || "${status_code}" -lt 200 || "${status_code}" -ge 300 ]]; then
    echo "upload failed: curl=${curl_exit}, status=${status_code}" >&2
    cat "${output}" >&2 2>/dev/null || true
    exit 1
  fi

  print_response upload "${output}"
  DOC_ID="$(json_get "${output}" id)"
  echo "upload passed, DOC_ID=${DOC_ID}"
}

run_wait_ready() {
  local output="${tmp_dir}/document-status.json"
  local status
  for ((attempt = 1; attempt <= POLL_ATTEMPTS; attempt++)); do
    request_json GET "/documents/${DOC_ID}" "${output}"
    status="$(json_get "${output}" status)"
    echo "document status: ${status} (${attempt}/${POLL_ATTEMPTS})"
    if [[ "${status}" == "ready" ]]; then
      print_response ready "${output}"
      return
    fi
    if [[ "${status}" == "failed" ]]; then
      cat "${output}" >&2
      exit 1
    fi
    sleep "${POLL_INTERVAL}"
  done
  echo "document did not become ready in time" >&2
  cat "${output}" >&2
  exit 1
}

run_chat() {
  local output="${tmp_dir}/chat.json"
  request_json POST "/chat" "${output}" "$(build_chat_body)"
  print_response chat "${output}"
  python3 - "${output}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data.get("answer"), str) or not data["answer"].strip():
    raise SystemExit("assert failed: answer must be non-empty")
if not isinstance(data.get("conversation_id"), int):
    raise SystemExit("assert failed: conversation_id must be int")
if not isinstance(data.get("message_id"), int):
    raise SystemExit("assert failed: message_id must be int")
if not isinstance(data.get("citations"), list):
    raise SystemExit("assert failed: citations must be list")
if not isinstance(data.get("retrieval"), dict):
    raise SystemExit("assert failed: retrieval must be object")
for citation in data["citations"]:
    for key in ("document_id", "chunk_id", "source_name", "snippet", "rank"):
        if citation.get(key) in (None, ""):
            raise SystemExit(f"assert failed: citation.{key} is required")
PY
  echo "chat passed"
}

case "${1:-all}" in
  all)
    if [[ -z "${KB_ID}" ]]; then
      run_create_kb
    fi
    run_upload
    run_wait_ready
    run_chat
    echo "chat flow test passed, KB_ID=${KB_ID}, DOC_ID=${DOC_ID}"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "unknown action: $1" >&2
    usage >&2
    exit 1
    ;;
esac
