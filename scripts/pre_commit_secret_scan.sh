#!/usr/bin/env bash
# pre-commit 密钥扫描 (NEXUS 收尾)
#
# 在 commit 前跑：
#   1) 拒绝把 .env / .env.* (除 .env.example) 加入暂存
#   2) 扫描暂存 diff 里的 sk-... 模式 (DeepSeek/OpenAI/Anthropic/SiliconFlow 等)
#   3) 命中则 abort commit
#
# 用法 (任选其一):
#   bash scripts/pre_commit_secret_scan.sh            # 手动跑
#   cp scripts/pre_commit_secret_scan.sh .git/hooks/pre-commit
#
# 环境变量:
#   NEXUS_SECRET_SCAN_BYPASS=1   跳过扫描（仅紧急逃生口）

set -euo pipefail

# 颜色
RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'

# 1) 检查 .env 是否被暂存
echo "[scan] 检查暂存里是否有 .env / .env.* ..."
FORBIDDEN=$(git diff --cached --name-only --diff-filter=ACMRT \
  | grep -E "(^|/)(\.env|\.env\.[^/]+)$" \
  | grep -vE "(\.env\.example|\.env\.template)$" || true)

if [[ -n "${FORBIDDEN}" ]]; then
  echo -e "${RED}[ABORT] 以下 .env 变体被加入暂存，commit 拒绝：${NC}"
  echo "${FORBIDDEN}"
  echo -e "${YEL}提示: .env 已在 .gitignore，commit 它需要 git add -f。${NC}"
  echo -e "${YEL}      如果你确实想 commit .env.example 模板，这不应该出现。${NC}"
  exit 1
fi

# 2) 扫描暂存 diff 里的 API key 模式
echo "[scan] 扫描暂存 diff 里的 sk- / API_KEY= 模式 ..."
# 只看新增行 (+)，匹配 =sk-... 或 Bearer sk-...
# 占位符 =sk-..., =sk-ant-..., =<...> 不算命中
HITS=$(git diff --cached --diff-filter=ACMRT -U0 \
  | grep -E "^\+[^+]" \
  | grep -E "(=sk-[a-zA-Z0-9-]{8,}|Bearer sk-[a-zA-Z0-9-]{8,})" \
  | grep -vE "(=sk-\.\.\.|=sk-ant-\.\.\.|<.*>|REDACTED|sk-3f22\.\.\.|sk-ylic\.\.\.)" \
  || true)

if [[ -n "${HITS}" ]]; then
  echo -e "${RED}[ABORT] 暂存里发现疑似真实 API key：${NC}"
  echo "${HITS}"
  echo -e "${YEL}如果这是占位符或测试数据，用 =sk-... 之类；${NC}"
  echo -e "${YEL}如果确认是真 key，先去供应商控制台撤销再用 .env 加载。${NC}"
  exit 1
fi

echo -e "${GRN}[scan] OK — 无 .env 文件，无可疑 sk- 字符串。${NC}"
exit 0
