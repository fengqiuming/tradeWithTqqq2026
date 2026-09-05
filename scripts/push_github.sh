#!/usr/bin/env bash
# 一键推送到 GitHub，并尽量自动开启 Pages。
#
# 用法：
#   bash scripts/push_github.sh        # 自动读取 .env 中的 GH_TOKEN
#   GH_TOKEN=xxx bash scripts/push_github.sh   # 临时用环境变量覆盖
#
# 凭据来源优先级：环境变量 > .env 文件 > SSH
# .env 已加入 .gitignore，脚本启动时会强制校验它没被 git 跟踪。
#
# 之所以需要这个脚本：某些网络下到 github.com 的 443 / 22 端口在 TCP 层被阻断，
# 且连接时通时断（502 与超时交替）。脚本内置多次采样探测和指数退避重试。

set -uo pipefail
REPO_SSH="git@github.com:fengqiuming/tradeWithTqqq2026.git"
REPO_HTTPS="https://github.com/fengqiuming/tradeWithTqqq2026.git"
OWNER="fengqiuming"; REPO="tradeWithTqqq2026"

cd "$(dirname "$0")/.." || exit 1

say(){ printf '\033[1m%s\033[0m\n' "$*"; }
ok(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; }
info(){ printf '  \033[33m·\033[0m %s\n' "$*"; }

# ---------- 0. 载入 .env ----------
# 逐行解析而不是直接 source，避免值里的特殊字符被 shell 解释。
load_env(){
  local f="$1" line k v
  [ -f "$f" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"                       # 兼容 CRLF
    line="${line#"${line%%[![:space:]]*}"}"    # 去前导空白
    case "$line" in ''|'#'*) continue;; esac
    k="${line%%=*}"; v="${line#*=}"
    [ -n "$k" ] && [ "$k" != "$line" ] || continue
    case "$v" in
      \"*\") v="${v#\"}"; v="${v%\"}";;
      \'*\') v="${v#\'}"; v="${v%\'}";;
    esac
    v="${v%"${v##*[![:space:]]}"}"             # 去尾部空白
    # 环境变量已存在则不覆盖（允许命令行临时覆盖）
    if [ -z "${!k:-}" ]; then export "$k=$v"; fi
  done < "$f"
}
load_env ".env"

# ---------- 0.5 凭据安全检查 ----------
# .env 绝不能进版本库。宁可拒绝执行，也不能冒险推送。
if [ -f .env ]; then
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    bad ".env 已被 git 跟踪！立即中止。"
    echo "    修复：git rm --cached .env && git commit -m 'chore: 移除误提交的 .env'"
    echo "    并确认 token 已泄露，请到 GitHub 上 revoke 后重新生成。"
    exit 1
  fi
  if ! git check-ignore -q .env; then
    bad ".env 未被 .gitignore 覆盖！已中止，避免凭据入仓。"
    echo "    修复：确认 .gitignore 中包含 .env"
    exit 1
  fi
  ok ".env 已加载，且确认未被 git 跟踪"
fi

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
# 注意：token 不拼进 remote URL。一旦推送失败，git 会把完整 URL 打进错误信息，
# 那样 token 就泄露到终端日志了。改用 http.extraheader 传 Authorization。
GIT_AUTH=()
if [ -n "${GH_TOKEN:-}" ]; then
  git remote set-url origin "$REPO_HTTPS"
  GIT_AUTH=(-c "http.extraheader=AUTHORIZATION: Basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')")
  ok "使用 HTTPS + GH_TOKEN（经 http.extraheader 传递）"
elif [ "$ssh_ok" = 1 ]; then
  git remote set-url origin "$REPO_SSH"
  ok "使用 SSH"
elif [ "$https_ok" = 1 ]; then
  git remote set-url origin "$REPO_HTTPS"
  info "未提供凭据。把 token 写进 .env（GH_TOKEN=...）即可免交互，"
  echo "    或运行时传入：GH_TOKEN=你的token bash scripts/push_github.sh"
  ok "已切换为 HTTPS（终端会提示输入用户名和 token）"
fi

# 输出前抹掉 token，防止泄露到日志
scrub(){
  local s="$1"
  [ -n "${GH_TOKEN:-}" ] && s="${s//$GH_TOKEN/***}"
  printf '%s' "$s"
}

# ---------- 3. 先同步远端，再推送 ----------
# Actions 每天会提交新数据，本地很容易落后。直接 push 会撞上 rejected，
# 而这类失败是确定性的（重试多少次都一样），所以先 fetch + rebase。
say "3/5 同步并推送到 GitHub"
git branch -M main 2>/dev/null

behind=""
if retry 4 git "${GIT_AUTH[@]}" fetch origin main; then
  behind=$(git rev-list --count HEAD..FETCH_HEAD 2>/dev/null || echo "")
  if [ -n "$behind" ] && [ "$behind" != "0" ]; then
    info "远端领先 $behind 个提交（多半是 Actions 的数据更新），先 rebase"
    if ! retry 4 git rebase FETCH_HEAD; then
      bad "rebase 失败，请手动处理冲突后再推送"
      echo "  $(scrub "$LAST_ERR")"
      exit 1
    fi
    ok "已 rebase 到远端最新"
  fi
else
  info "fetch 失败（网络抖动），直接尝试推送"
fi

if retry 6 git "${GIT_AUTH[@]}" push -u origin main; then
  ok "推送成功"
else
  bad "推送失败（已重试 6 次）"
  echo "  最后错误：$(scrub "$LAST_ERR")"
  echo "  常见原因：token 权限不足（需 Contents:RW + Workflows:RW）/ 仓库不存在 /"
  echo "            本地与远端存在冲突（手动 git pull --rebase 后重试）"
  exit 1
fi

# ---------- 4. 开启 Pages ----------
say "4/5 检查 GitHub Pages"
PAGES_URL="https://${OWNER}.github.io/${REPO}/"
if [ -n "${GH_TOKEN:-}" ] && [ "$https_ok" = 1 ]; then
  # 先查现状。GET 只需 Contents 读权限，POST 才要 Pages 写权限，
  # 所以「没权限」和「还没开」要分开判断，别把已上线的站点说成没开。
  stat=""; for ((i=1;i<=5;i++)); do
    stat=$(curl -s --max-time 20 -H "Authorization: Bearer ${GH_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${OWNER}/${REPO}/pages" 2>/dev/null)
    [ -n "$stat" ] && break
    sleep 4
  done
  if echo "$stat" | grep -qi '"html_url"'; then
    ok "Pages 已启用：$PAGES_URL"
  else
    resp=""; for ((i=1;i<=5;i++)); do
      resp=$(curl -s --max-time 20 -X POST \
        -H "Authorization: Bearer ${GH_TOKEN}" -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/${OWNER}/${REPO}/pages" \
        -d '{"source":{"branch":"main","path":"/"}}' 2>/dev/null)
      [ -n "$resp" ] && break
      sleep 4
    done
    if echo "$resp" | grep -qi '"html_url"\|already exists'; then
      ok "Pages 已开启：$PAGES_URL"
      info "首次部署需 1~2 分钟"
    else
      info "自动开启未成功（多半是 token 缺 Pages:Read and write 权限），手动开即可："
      echo "    https://github.com/${OWNER}/${REPO}/settings/pages"
      echo "    Source → Deploy from a branch；Branch → main，目录 → /(root)，保存"
      echo "    返回：$(scrub "${resp:0:160}")"
    fi
  fi
else
  info "跳过。请手动完成一次："
  echo "    https://github.com/${OWNER}/${REPO}/settings/pages"
  echo "    Source → Deploy from a branch；Branch → main，目录 → /(root)，保存"
fi

# ---------- 5. 可选：配置 Actions 密钥 ----------
say "5/5 Alpha Vantage 兜底密钥（可选）"
if [ -n "${AV_API_KEY:-}" ]; then
  info ".env 中已配置 AV_API_KEY，但需要同步到 GitHub 才能被 Actions 使用："
  echo "    https://github.com/${OWNER}/${REPO}/settings/secrets/actions"
  echo "    New repository secret → 名称 AV_API_KEY → 值填 .env 里的那个"
  echo "    （脚本不自动写入：那需要 token 额外具备 Secrets 写权限，风险不划算）"
else
  info "未配置 AV_API_KEY 也能正常运行（yfinance 是主数据源）。"
  echo "    想加兜底就申请后填入 .env 的 AV_API_KEY，再到"
  echo "    Settings → Secrets → Actions 添加同名密钥。"
fi

echo
say "完成。之后每个工作日 21:30 UTC 会自动更新数据。"
