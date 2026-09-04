# TQQQ 交易指引工具

按《TQQQ 交易策略分析笔记》里的规则，用真实市场数据给出每日交易信号，
并可以对策略本身做回测和参数检验。

**架构：构建期抓取数据 → 静态快照 → 纯前端读取。运行时不调用任何行情 API。**

```
scripts/fetch_data.py  ──▶  data/market.json + market.js  ──▶  index.html
      (GitHub Actions 每日定时)        (构建期快照)            (纯静态，零依赖)
```

## 快速开始

```bash
pip install -r requirements.txt
python3 scripts/fetch_data.py
open index.html          # 双击也行，不需要起服务器
```

页面会显示：今日所处区间与建议操作、QQQ/MA200 走势、可交互回测、个人交易记录。

> 数据文件同时输出 `.json` 和 `.js` 两份。原因是 `file://` 协议下
> `fetch()` 读本地 JSON 会被 CORS 拦掉，而 `<script src>` 不会 ——
> 有 `.js` 这份才能做到「不启服务器、双击即用」。

## 数据源与自检

抓取按优先级尝试，任一候选通过校验即止：

| 优先级 | 数据源 | 说明 |
|---|---|---|
| 1 | **yfinance** | Yahoo `Adj Close`，权威，TQQQ 自 2010-02 上市起全历史。需海外网络，**GitHub Actions 环境可用** |
| 2 | **Alpha Vantage** | 需 `AV_API_KEY` 环境变量（免费额度 25 次/天）。Yahoo 抽风时兜底 |
| 3 | **国内兜底** | 腾讯（QQQ + TQQQ 同源）→ 新浪+腾讯 → 东财+腾讯 |

### 为什么必须做自检

实测踩过的三个坑，任何一个都会让回测结果变成幻觉：

1. **新浪 / 东财的 TQQQ「前复权」根本没应用拆股** —— 表现为多次精确的
   `-50%` / `-66.7%` 单日跳变，序列显示 TQQQ 从 2011 年的 167「跌」到
   2026 年的 69，而同期 QQQ 涨了 13 倍。
   → 由**跳变检测**和**长期收益关系校验**拦截。

2. **新浪 QQQ 有 6 年空洞** —— 从 `2004-12-31` 直接跳到 `2011-04-26`。
   根数看着不少（4862），实际是两段拼接的残序列，光看根数发现不了。
   → 由**覆盖率 / 最大间隔**连续性校验拦截。

3. **东财接口间歇性不可用**（多个域名均 Connection Reset）。
   → 多候选 + 重试退避。

校验不通过就丢弃该候选、尝试下一个；全部失败则**非零退出、不产出文件**。

### 已知限制

- 国内兜底源下，腾讯单标的硬上限约 **1350 根**（1400 起报 `limit error`，
  且不支持往回翻页），回测区间约 4.6 年。
- 要 TQQQ 自 2010 年上市起的全历史，必须在海外网络下用 yfinance，
  即依赖 GitHub Actions 自动更新。

## 策略规则（原文档的歧义已在此定死）

| 项 | 定义 |
|---|---|
| 信号标的 | **只看 QQQ** 的 200 日简单均线，不看 TQQQ 自身均线 |
| 牛市 | `QQQ > MA200 × 1.04` |
| 熊市 | `QQQ < MA200 × 0.97` |
| 缓冲带 | 0.97 ~ 1.04 倍之间，**维持上一状态，不触发新信号** |
| 加仓 | 牛市中 QQQ 单日**收盘**较前一日跌 ≥1%，把账户全部现金买入 TQQQ（含已有仓位时继续加） |
| 熊转牛 | 突破牛市线**立即全仓买入，不等回调** |
| 牛转熊 | 跌破熊市线**清仓换现金** |
| 移动止损 | 持仓期间 TQQQ 较**本次持仓周期内最高收盘价**回撤 ≥40% 无条件清仓 |
| 成交价 | 一律按**当日收盘价** |
| 定投 | 每月首个交易日存入，与市场状态无关 |

### 原文档没说清的歧义（已做成可选项）

**止损后如何重新入场** —— 文档只说「无条件清仓」，没说能否立即买回。
这是策略里对结果影响最大的一个歧义，页面参数区提供两种口径：

- `必须重新突破牛市线`（默认，保守）：清仓后须等 QQQ 重新站上 MA200×1.04
- `牛市中遇回调即可买回`（宽松）：清仓后只要牛市区间内遇 1% 回调就买回

## 回测口径

- **年化收益用 IRR**（XIRR，按实际现金流天数求解）。定投策略有持续现金流，
  用「终值/本金」开方会严重失真。
- **最大回撤用时间加权净值（TWR）** 计算，剔除定投流入的影响。
  否则新钱不断进场会掩盖真实回撤。
- 同时给出「定投 QQQ 正股」和「定投 TQQQ 不止损」两条基准线做对照。

## 部署

仓库：<https://github.com/fengqiuming/tradeWithTqqq2026>

### 推送

```bash
# 方式 A：SSH（需本机公钥已加到 GitHub）
bash scripts/push_github.sh

# 方式 B：HTTPS + Personal Access Token（推荐，顺带自动开启 Pages）
GH_TOKEN=你的token bash scripts/push_github.sh
```

脚本会自动做连通性探测、选择通道、失败重试、推送，并在 token 可用时
通过 API 开启 Pages。

生成 token：<https://github.com/settings/tokens> → Generate new token (classic)
→ 勾选 **`repo`** 和 **`workflow`**。

> `workflow` 权限是必需的：本项目要推送 `.github/workflows/update-data.yml`，
> 只有 `repo` 权限的 token 会被 GitHub 直接拒绝。

> 某些网络下到 github.com 的连接会时通时断（502 与超时交替）。脚本内置了
> 多次采样探测和指数退避重试，通一次就能推上去。

### 开启 Pages

带 token 跑脚本会自动完成 —— **前提是 token 要带 `Pages: Read and write` 权限**。
缺这个权限时 API 返回 `403 Resource not accessible by personal access token`，
手动开即可，三步：

仓库 **Settings → Pages → Source** 选 `Deploy from a branch`，
Branch 选 `main`、目录选 `/(root)`，保存。

部署完成后访问 <https://fengqiuming.github.io/tradeWithTqqq2026/>。

### 每日自动更新

`.github/workflows/update-data.yml` 在每个工作日 21:30 UTC（美股收盘后）自动
抓取、校验并提交新数据。也可随时手动触发：Actions → 更新行情数据 → Run workflow。

要在 Yahoo 不可用时启用兜底，到 **Settings → Secrets → Actions** 添加
`AV_API_KEY`。不配也能正常运行，只是少一层保险。

## 目录结构

```
index.html                        前端（单文件，零依赖，可离线运行）
scripts/fetch_data.py             数据抓取 + 自检
scripts/test_backtest.js          回测引擎冒烟测试（node）
scripts/check_frontend.js         前端静态检查（node）
data/market.json  data/market.js  构建期数据快照
requirements.txt                  仅抓取脚本需要
.github/workflows/update-data.yml 每日自动更新
```

## 开发

```bash
python3 scripts/fetch_data.py
node scripts/test_backtest.js      # 校验回测数学 + 参数敏感性
node scripts/check_frontend.js     # 语法 / DOM 选择器 / 资源完整性
```

## 免责

这是个人研究工具，输出的是按固定规则机械计算的结果，不是投资建议。
3 倍杠杆 ETF 有显著的波动损耗和路径依赖风险，历史回测不代表未来表现。
