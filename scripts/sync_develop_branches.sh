#!/usr/bin/env bash

set -euo pipefail

# 将前后端仓库的 develop 安全同步到 master 与 kv-00001。
# 默认执行测试、推送和本地目标分支更新；传入 --dry-run 只检查，不写远程。

backend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
frontend_root="${backend_root}-web"
source_branch="develop"
target_branches=("master" "kv-00001")
dry_run=false

if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
elif [[ -n "${1:-}" ]]; then
  echo "用法：$0 [--dry-run]" >&2
  exit 2
fi

require_repository() {
  local repository="$1"
  local name="$2"

  if [[ ! -d "${repository}/.git" ]]; then
    echo "${name}仓库不存在：${repository}" >&2
    exit 1
  fi
  if [[ -n "$(git -C "${repository}" status --porcelain)" ]]; then
    echo "${name}仓库存在未提交修改，请先提交或清理后再同步。" >&2
    exit 1
  fi
}

run_checks() {
  local repository="$1"
  local name="$2"

  echo "[${name}] 执行同步前检查"
  if [[ "${name}" == "后端" ]]; then
    (cd "${repository}" && uv run pytest -q)
  else
    (
      cd "${repository}"
      npm run format:check
      npm run type-check
      npm run build
    )
  fi
}

sync_repository() {
  local repository="$1"
  local name="$2"
  local target=""

  echo "[${name}] 刷新远程引用"
  git -C "${repository}" fetch origin --prune
  git -C "${repository}" switch "${source_branch}"
  git -C "${repository}" pull --ff-only origin "${source_branch}"
  run_checks "${repository}" "${name}"

  if [[ "${dry_run}" == true ]]; then
    echo "[${name}] dry-run 完成，不推送分支"
    return
  fi

  git -C "${repository}" push origin "${source_branch}"
  git -C "${repository}" fetch origin --prune

  for target in "${target_branches[@]}"; do
    if git -C "${repository}" show-ref --verify --quiet "refs/remotes/origin/${target}"; then
      if ! git -C "${repository}" merge-base --is-ancestor \
        "origin/${target}" "origin/${source_branch}"; then
        echo "[${name}] origin/${target} 已与 ${source_branch} 分叉，停止同步。" >&2
        exit 1
      fi
    fi

    echo "[${name}] 同步 ${source_branch} -> ${target}"
    git -C "${repository}" push origin \
      "refs/remotes/origin/${source_branch}:refs/heads/${target}"
    git -C "${repository}" branch --force "${target}" "origin/${source_branch}"
  done
}

require_repository "${backend_root}" "后端"
require_repository "${frontend_root}" "前端"

sync_repository "${backend_root}" "后端"
sync_repository "${frontend_root}" "前端"

echo "前后端 develop 已同步到 master 与 kv-00001。"
