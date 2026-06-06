#!/usr/bin/env bash
# pre-commit 密钥扫描 (NEXUS 收尾 + per-project scope)
#
# 在 commit 前跑：
#   1) 全 monorepo: 拒绝把 .env / .env.* (除 .env.example) 加入暂存
#   2) 仅 nexus/ 子项目: 额外扫 sk-... 模式 (DeepSeek/OpenAI/Anthropic/SiliconFlow 等)
#      — 其它子项目 (AFAC2024/Agentrix/FinQwen/QueryCraft/Homework-Week17) 不强制
#      NEXUS 的 sk- 模式，因为它们是不同公司/比赛的代码，可能用别的 key 格式。
#   3) 命中则 abort commit
#
# 用法 (任选其一):
#   bash scripts/pre_commit_secret_scan.sh            # 手动跑
#   cp scripts/pre_commit_secret_scan.sh .git/hooks/pre-commit
#
# 环境变量:
#   NEXUS_SECRET_SCAN_BYPASS=1   跳过整个扫描 (紧急逃生口)
#   NEXUS_SECRET_SCAN_LOOSE=1     跳过 sk- 模式扫描, 只做 .env 拦截

set -euo pipefail

# 颜色
RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'

# 修复 (P2): 拆出 NEXUS 子项目范围，不误伤兄弟项目
NEXUS_PREFIX="nexus/"

# 1) 检查 .env 是否被暂存 (全 monorepo 范围)
echo "[scan] 检查暂存里是否有 .env / .env.* ..."
FORBIDDEN=$(git diff --cached --name-only --diff-filter=ACMRT \
  | grep -E "(^|/)(\.env|\.env\.[^/]+)$" \
  | grep -vE "(\.env\.example|\.env\.template)$" || true)

if [[ -n "${FORBIDDEN}" ]]; then
  echo -e "${RED}[ABORT] 以下 .env 变体被加入暂存, commit 拒绝:${NC}"
  echo "${FORBIDDEN}"
  echo -e "${YEL}提示: .env 已在 .gitignore, commit 它需要 git add -f。${NC}"
  echo -e "${YEL}      如果你确实想 commit .env.example 模板, 这不应该出现。${NC}"
  exit 1
fi

# 2) 仅扫描 nexus/ 子项目下的 sk- 模式
if [[ "${NEXUS_SECRET_SCAN_LOOSE:-0}" == "1" ]]; then
  echo -e "${YEL}[scan] NEXUS_SECRET_SCAN_LOOSE=1, 跳过 sk- 扫描${NC}"
  echo -e "${GRN}[scan] OK — 无 .env 文件。${NC}"
  exit 0
fi

echo "[scan] 扫描 nexus/ 子项目 diff 里的 sk- / API_KEY= 模式 ..."
# 只看新增行 (+), 匹配 =sk-... 或 Bearer sk-...
# 占位符 =sk-..., =sk-ant-..., =<...> 不算命中
# 修复 (P2): 用 -- 'nexus/*' 限定, 兄弟项目代码不再被 NEXUS 的 sk- 模式误伤
HITS=$(git diff --cached --diff-filter=ACMRT -U0 -- "$NEXUS_PREFIX" \
  | grep -E "^\+[^+]" \
  | grep -E "(=sk-[a-zA-Z0-9-]{8,}|Bearer sk-[a-zA-Z0-9-]{8,})" \
  | grep -vE "(=sk-\.\.\.|=sk-ant-\.\.\.|<.*>|REDACTED|sk-3f22\.\.\.|sk-ylic\.\.\.)" \
  || true)

if [[ -n "${HITS}" ]]; then
  echo -e "${RED}[ABORT] nexus/ 子项目暂存里发现疑似真实 API key:${NC}"
  echo "${HITS}"
  echo -e "${YEL}如果这是占位符或测试数据, 用 =sk-... 之类;${NC}"
  echo -e "${YEL}如果确认是真 key, 先去供应商控制台撤销再用 .env 加载。${NC}"
  exit 1
fi

echo -e "${GRN}[scan] OK — 无 .env 文件, nexus/ 子项目无可疑 sk- 字符串。${NC}"
exit 0
