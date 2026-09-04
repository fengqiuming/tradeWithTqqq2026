#!/usr/bin/env bash
# 一键推送到 GitHub，并尽量自动开启 Pages。
#
# 用法：
#   bash scripts/push_github.sh                 # 用 SSH
#   GH_TOKEN=ghp_xxx bash scripts/push_github.sh # 用 HTTPS + token（并自动开 Pages）
#
# 之所以需要这个脚本：当前开发机到 github.com 的 443 / 22 端口在 TCP 层就被阻断，
# 无法从这里推送。换一台能访问 GitHub 的机器（或换个网络）执行本脚本即可。

set -uo pipefail
REPO_SSH="git@github.com:fengqiuming/tradeWithTqqq2026.git"
REPO_HTTPS="https://github.com/fengqiuming/tradeWithTqqq2026.git"
OWNER="fengqiuming"; REPO="tradeWithTqqq2026"

cd "$(dirname "$0")/.." || exit 1

say(){ printf '\033[1m%s\033[0m\n' "$*"; }
ok(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; }
info(){ printf '  \033[33m·\033[0m %s\n' "$*"; }

# 到 github.com 的连接时通时断（502 / 超时交替出现），关键步骤都要重试
retry(){
  local n=$1; shift; local i out
  for ((i=1;i<=n;i++)); do
    if out=$("$@" 2>&1); then [ -n "$out" ] && printf '%s\n' "$out"; return 0; fi
    [ "$i" -lt "$n" ] && { printf '      第 %s 次失败，%ss 后重试…\n' "$i" "$((i*4))"; sleep $((i*4)); }
  done
  LAST_ERR="$out"; return 1
}
# 探测可达性：多次采样，只要成功一次就算通
probe(){
  local url=$1 n=${2:-5} i code
  for ((i=1;i<=n;i++)); do
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)
    case "$code" in 2*|3*|401|403) return 0;; esac
    [ "$i" -lt "$n" ] && sleep 3
  done
  return 1
}

# ---------- 1. 连通性自检 ----------
say "1/5 检查 GitHub 连通性"
ssh_ok=0; https_ok=0
if ssh -T -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 git@github.com 2>&1 | grep -qi "successfully authenticated\|You've successfully"; then
  ssh_ok=1; ok "SSH 认证通过"
elif ssh -T -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 git@github.com 2>&1 | grep -qi "permission denied"; then
  info "SSH 可达但未授权（公钥未加到 GitHub）"
else
  info "SSH 不可达"
fi

if probe "https://api.github.com" 5; then
  https_ok=1; ok "HTTPS 可达"
else
  info "HTTPS 不可达"
fi

if [ "$ssh_ok" = 0 ] && [ "$https_ok" = 0 ]; then
  bad "GitHub 完全不可达 —— 网络层被阻断。"
  echo
  echo "  当前网络无法连接 github.com（443 / 22 均超时）。请换一个网络，"
  echo "  或在另一台能访问 GitHub 的机器上执行本脚本。"
  exit 1
fi

# ---------- 2. 选择推送通道 ----------
say "2/5 选择推送通道"
if [ -n "${GH_TOKEN:-}" ]; then
  git remote set-url origin "https://${GH_TOKEN}@github.com/${OWNER}/${REPO}.git" 2>/dev/null
  ok "使用 HTTPS + GH_TOKEN"
elif [ "$ssh_ok" = 1 ]; then
  git remote set-url origin "$REPO_SSH"
  ok "使用 SSH"
elif [ "$https_ok" = 1 ]; then
  info "SSH 未授权。可改用 HTTPS："
  echo "    1) 在 github.com/settings/tokens 生成 Personal Access Token（勾 repo 权限）"
  echo "    2) 重新运行：GH_TOKEN=你的token bash scripts/push_github.sh"
  git remote set-url origin "$REPO_HTTPS"
  ok "已切换为 HTTPS（推送时终端会提示输入用户名和 token）"
fi

# ---------- 3. 推送 ----------
say "3/5 推送到 GitHub"
git branch -M main 2>/dev/null
if retry 6 git push -u origin main; then
  ok "推送成功"
else
  bad "推送失败（已重试 6 次）"
  echo "  最后错误：$LAST_ERR"
  echo "  常见原因：token 权限不足 / 仓库不存在 / 远程已有内容（需先 git pull --rebase）"
  exit 1
fi

# ---------- 4. 开启 Pages ----------
say "4/5 开启 GitHub Pages"
if [ -n "${GH_TOKEN:-}" ] && [ "$https_ok" = 1 ]; then
  resp=""; for ((i=1;i<=5;i++)); do
    resp=$(curl -s --max-time 20 -X POST \
      -H "Authorization: Bearer ${GH_TOKEN}" -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${OWNER}/${REPO}/pages" \
      -d '{"source":{"branch":"main","path":"/"}}' 2>/dev/null)
    [ -n "$resp" ] && break
    sleep 4
  done
  if echo "$resp" | grep -qi '"html_url"\|already exists'; then
    ok "Pages 已开启：https://${OWNER}.github.io/${REPO}/"
    info "首次部署需 1~2 分钟"
  else
    info "自动开启未成功，请手动到 Settings → Pages → Source 选 main / (root)"
    echo "    返回：$(echo "$resp" | head -c 200)"
  fi
else
  info "跳过自动开启。请手动完成一次："
  echo "    https://github.com/${OWNER}/${REPO}/settings/pages"
  echo "    Source → Deploy from a branch；Branch → main，目录 → /(root)，保存"
fi

# ---------- 5. 可选：配置 Actions 密钥 ----------
say "5/5 Alpha Vantage 兜底密钥（可选）"
if [ -n "${AV_API_KEY:-}" ] && [ -n "${GH_TOKEN:-}" ] && [ "$https_ok" = 1 ]; then
  info "配置 Secret 需要额外的加密步骤，请手动到"
  echo "    https://github.com/${OWNER}/${REPO}/settings/secrets/actions"
  echo "    New repository secret → 名称 AV_API_KEY"
else
  info "未配置 AV_API_KEY 也能正常运行（yfinance 是主数据源）。"
  echo "    想加兜底就到 Settings → Secrets → Actions 添加 AV_API_KEY。"
fi

echo
say "完成。之后每个工作日 21:30 UTC 会自动更新数据。"
