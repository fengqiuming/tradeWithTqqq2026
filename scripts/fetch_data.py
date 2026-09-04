#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TQQQ 交易指引工具 —— 行情数据抓取与自检脚本

产出一个构建期快照 data/market.json，前端只读取这个静态文件，
不依赖任何运行时的第三方行情 API。

数据源优先级（任一候选通过校验即止）：
  1. yfinance        Yahoo Adj Close，权威，需海外网络（GitHub Actions 环境可用）
  2. Alpha Vantage   需要环境变量 AV_API_KEY，免费额度 25 次/天
  3. cn-fallback     腾讯（QQQ + TQQQ 同源）→ 新浪+腾讯 → 东财+腾讯

⚠️ 设计原则：任何候选数据都必须过 validate()。校验不通过就丢弃，
尝试下一个候选；全部失败则非零退出，**绝不产出坏数据**。

  这是被实测逼出来的。三个真实踩过的坑：

  1. 新浪 / 东财的 TQQQ「前复权」并未应用拆股 —— 表现为多次精确的
     -50% / -66.7% 单日跳变，序列显示 TQQQ 从 2011 年的 167「跌」到
     2026 年的 69，而同期 QQQ 涨了 13 倍。用这种数据回测，得到的
     年化收益率是纯粹的幻觉。→ 跳变检测 + 收益关系校验

  2. 新浪 QQQ 有 6 年空洞 —— 从 2004-12-31 直接跳到 2011-04-26。
     根数看着不少（4862），实际是两段拼接的残序列，光看根数发现不了。
     → 覆盖率 / 最大间隔 连续性校验

  3. 东财接口间歇性不可用（多个域名均 Connection Reset）。
     → 多候选 + 重试退避
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "market.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

# ---------- 校验阈值 ----------
MIN_QQQ_BARS = 1200          # 腾讯兜底上限约 1350 根，门槛设在其下
MIN_TQQQ_BARS = 250
MAX_STALE_DAYS = 10          # 数据新鲜度
JUMP_WARN = 0.35             # 单日 |变动| 超过 35% 记一次异常跳变
JUMP_MAX_COUNT = 5           # 超过这么多次 → 判定复权未生效
RET_RATIO_MIN = 0.3          # TQQQ 总回报 / QQQ 总回报 合理下界
RET_RATIO_MAX = 30.0         # 合理上界
MIN_COVERAGE = 0.90          # 根数 / 理论交易日数 —— 抓序列空洞
MAX_GAP_DAYS = 10            # 相邻交易日最大日历间隔（覆盖长假期）
TRADING_DAYS_PER_YEAR = 252
MA200_WARMUP = 300           # TQQQ 起点之前保留多少根 QQQ 用于均线预热
TX_MAX_BARS = 1350           # 腾讯单标的硬上限（1400 起报 limit error）


def log(msg: str = "") -> None:
    print(msg, flush=True)


def http_get(url: str, timeout: int = 40, retries: int = 3) -> str:
    """带退避重试的 GET。国内行情接口间歇性断开，重试是必需的。"""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败（重试 {retries} 次）：{last}")


# ============================================================
# 数据源 1：yfinance（推荐，海外网络）
# ============================================================
def fetch_yfinance() -> list[dict]:
    try:
        import yfinance as yf  # noqa: PLC0415
    except ImportError:
        log("  未安装 yfinance，跳过")
        return []

    out: dict[str, dict[str, float]] = {}
    try:
        for sym in ("QQQ", "TQQQ"):
            df = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False)
            if df is None or df.empty:
                log(f"  {sym}: 返回空")
                return []
            col = "Adj Close" if "Adj Close" in df.columns else "Close"
            s = df[col].dropna()
            out[sym] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    except Exception as exc:  # noqa: BLE001
        log(f"  失败: {exc}")
        return []

    return [{
        "QQQ": out["QQQ"], "TQQQ": out["TQQQ"],
        "meta": {"adjust": "yahoo-adjclose"},
    }]


# ============================================================
# 数据源 2：Alpha Vantage（需 AV_API_KEY）
# ============================================================
def fetch_alphavantage() -> list[dict]:
    key = os.environ.get("AV_API_KEY")
    if not key:
        log("  未设置 AV_API_KEY，跳过")
        return []

    out: dict[str, dict[str, float]] = {}
    for sym in ("QQQ", "TQQQ"):
        url = (
            "https://www.alphavantage.co/query"
            "?function=TIME_SERIES_DAILY_ADJUSTED"
            f"&symbol={sym}&outputsize=full&apikey={key}"
        )
        try:
            j = json.loads(http_get(url, timeout=60))
        except Exception as exc:  # noqa: BLE001
            log(f"  {sym} 请求失败: {exc}")
            return []

        ts = j.get("Time Series (Daily)")
        if not ts:
            log(f"  {sym}: {str(j)[:160]}")
            return []
        out[sym] = {d: float(v["5. adjusted close"]) for d, v in ts.items()}
        time.sleep(1)  # 免费额度有限，别打太猛

    return [{
        "QQQ": out["QQQ"], "TQQQ": out["TQQQ"],
        "meta": {"adjust": "av-adjusted-close"},
    }]


# ============================================================
# 数据源 3：国内兜底
# ============================================================
def _tencent(code: str, count: int = TX_MAX_BARS) -> dict[str, float]:
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get"
        f"?param=us{code}.OQ,day,,,{count},qfq"
    )
    j = json.loads(http_get(url, timeout=30))
    node = (j.get("data") or {}).get(f"us{code}.OQ") or {}
    rows = node.get("qfqday") or node.get("day") or []
    # rows 元素：[日期, 开, 收, 高, 低, 成交量]
    return {r[0]: float(r[2]) for r in rows}


def _sina_us(symbol: str) -> dict[str, float]:
    """新浪美股日线（jsonp，需剥壳）。无 CORS，只能脚本侧调用。"""
    url = (
        "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/x/"
        f"US_MinKService.getDailyK?symbol={symbol}&___qn=3"
    )
    m = re.search(r"x\((\[.*\])\)", http_get(url), re.S)
    if not m:
        raise RuntimeError("新浪返回格式异常")
    rows = json.loads(m.group(1))
    # 字段：{d:日期, o:开, h:高, l:低, c:收, v:量, a:?}
    return {r["d"]: float(r["c"]) for r in rows}


def _eastmoney(secid: str) -> dict[str, float]:
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        "&klt=101&fqt=1&beg=19900101&end=20500101&lmt=10000"
    )
    j = json.loads(http_get(url, retries=2))
    klines = (j.get("data") or {}).get("klines") or []
    # klines 元素：日期,开,收,高,低,成交量,成交额,振幅
    return {r.split(",")[0]: float(r.split(",")[2]) for r in klines}


def fetch_cn_fallback() -> list[dict]:
    """国内可达的兜底组合，按「一致性优先」排序：

      1. 腾讯同时供 QQQ + TQQQ —— 同源、同复权口径，最一致
      2. 新浪供 QQQ + 腾讯供 TQQQ —— QQQ 更长（但有空洞，靠校验拦）
      3. 东财供 QQQ + 腾讯供 TQQQ —— 东财常不可达

    ⚠️ TQQQ 只认腾讯：东财 / 新浪的 TQQQ 复权是坏的（未应用拆股）。
    """
    plans = [
        ("腾讯(QQQ+TQQQ)", lambda: (_tencent("QQQ"), _tencent("TQQQ")), "tx-qfq"),
        ("新浪(QQQ)+腾讯(TQQQ)", lambda: (_sina_us("QQQ"), _tencent("TQQQ")), "sina+tx-qfq"),
        ("东财(QQQ)+腾讯(TQQQ)", lambda: (_eastmoney("105.QQQ"), _tencent("TQQQ")), "em+tx-qfq"),
    ]

    cands: list[dict] = []
    for label, fn, adjust in plans:
        try:
            qqq, tqqq = fn()
        except Exception as exc:  # noqa: BLE001
            log(f"  {label} 抓取失败: {exc}")
            continue
        if not qqq or not tqqq:
            log(f"  {label} 数据为空")
            continue
        log(f"  {label}: QQQ {len(qqq)} 根 / TQQQ {len(tqqq)} 根")
        cands.append({
            "QQQ": qqq, "TQQQ": tqqq,
            "meta": {
                "adjust": adjust,
                "degraded": True,
                "note": "国内兜底源，历史深度受限（腾讯单标的上限约 1350 根）；"
                        "要 TQQQ 自 2010 上市起的全历史，请在海外网络下用 yfinance",
            },
        })
    return cands


# ============================================================
# 数据自检
# ============================================================
def validate(qqq: dict[str, float], tqqq: dict[str, float]) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。errors 非空即表示该候选数据不可用。"""
    errs: list[str] = []
    warns: list[str] = []

    def _parse(d: str) -> datetime:
        return datetime.strptime(d, "%Y-%m-%d")

    # 1) 数据量
    if len(qqq) < MIN_QQQ_BARS:
        errs.append(f"QQQ 仅 {len(qqq)} 根，少于要求的 {MIN_QQQ_BARS} 根")
    if len(tqqq) < MIN_TQQQ_BARS:
        errs.append(f"TQQQ 仅 {len(tqqq)} 根，少于要求的 {MIN_TQQQ_BARS} 根")

    # 2) 基本结构：日期可解析、价格为有限正数
    for name, series in (("QQQ", qqq), ("TQQQ", tqqq)):
        bad = sum(1 for v in series.values() if v != v or v <= 0 or v == float("inf"))
        if bad:
            errs.append(f"{name} 有 {bad} 个非正 / NaN 价格")
        try:
            [_parse(d) for d in series]
        except Exception:  # noqa: BLE001
            errs.append(f"{name} 日期格式异常")

    if errs:
        return errs, warns

    # 3) 新鲜度
    latest = max(tqqq) if tqqq else max(qqq)
    age = (datetime.now() - _parse(latest)).days
    if age > MAX_STALE_DAYS:
        errs.append(f"数据过期：最新交易日 {latest}，距今 {age} 天")
    elif age > 4:
        warns.append(f"数据略有延迟，最新交易日 {latest}（{age} 天前）")

    # 4) 序列连续性 —— 抓「根数看着够、实际有整段空洞」
    for name, series in (("QQQ", qqq), ("TQQQ", tqqq)):
        ks = sorted(series, key=_parse)
        span_days = (_parse(ks[-1]) - _parse(ks[0])).days
        span_years = span_days / 365.25
        expected = span_years * TRADING_DAYS_PER_YEAR
        coverage = len(ks) / expected if expected > 0 else 0
        if coverage < MIN_COVERAGE:
            errs.append(
                f"{name} 序列有空洞：{span_years:.1f} 年跨度只有 {len(ks)} 根，"
                f"覆盖率 {coverage:.0%}（应 ≥{MIN_COVERAGE:.0%}）"
            )

        gaps = [
            (ks[i], (_parse(ks[i]) - _parse(ks[i - 1])).days)
            for i in range(1, len(ks))
            if (_parse(ks[i]) - _parse(ks[i - 1])).days > MAX_GAP_DAYS
        ]
        if gaps:
            worst = max(gaps, key=lambda g: g[1])
            errs.append(
                f"{name} 有 {len(gaps)} 处日期断层，最长 {worst[1]} 天（止于 {worst[0]}）"
            )

    # 5) 拆股跳变检测 —— 抓「复权未生效」
    for name, series in (("QQQ", qqq), ("TQQQ", tqqq)):
        ks = sorted(series, key=_parse)
        jumps = []
        for i in range(1, len(ks)):
            a, b = series[ks[i - 1]], series[ks[i]]
            if a > 0 and abs(b / a - 1) > JUMP_WARN:
                jumps.append((ks[i], b / a - 1))
        if jumps:
            sample = "，".join(f"{d}:{c:+.0%}" for d, c in jumps[:4])
            warns.append(f"{name} 检测到 {len(jumps)} 次 >{JUMP_WARN:.0%} 单日跳变（{sample}）")
            if len(jumps) > JUMP_MAX_COUNT:
                errs.append(
                    f"{name} 疑似复权未生效：{len(jumps)} 次 >{JUMP_WARN:.0%} 跳变，"
                    f"正常的 3 倍杠杆 ETF 不应如此密集地出现极端跳变"
                )

    # 6) 长期收益关系：3 倍杠杆 ETF 相对正股的长期表现应落在合理区间
    common = sorted(set(qqq) & set(tqqq), key=_parse)
    if len(common) >= 500:
        r_qqq = qqq[common[-1]] / qqq[common[0]]
        r_tqqq = tqqq[common[-1]] / tqqq[common[0]]
        ratio = r_tqqq / r_qqq
        span_y = (_parse(common[-1]) - _parse(common[0])).days / 365.25
        if not (RET_RATIO_MIN <= ratio <= RET_RATIO_MAX):
            errs.append(
                f"TQQQ/QQQ 收益关系异常：{span_y:.1f} 年内 QQQ ×{r_qqq:.2f}、"
                f"TQQQ ×{r_tqqq:.2f}，比值 {ratio:.3f} 落在合理区间 "
                f"[{RET_RATIO_MIN}, {RET_RATIO_MAX}] 之外 —— 极可能是复权错误"
            )
        else:
            warns.append(
                f"收益关系自检通过：{span_y:.1f} 年 QQQ ×{r_qqq:.2f}、TQQQ ×{r_tqqq:.2f}"
            )

    return errs, warns


# ============================================================
# 组装输出
# ============================================================
def build_payload(qqq: dict[str, float], tqqq: dict[str, float],
                  source: str, warns: list[str], meta: dict) -> dict:
    def _parse(d: str) -> datetime:
        return datetime.strptime(d, "%Y-%m-%d")

    dates = sorted(qqq, key=_parse)
    t_dates = sorted(tqqq, key=_parse)

    # 只保留 TQQQ 起点前 MA200_WARMUP 根之后的 QQQ，保证均线预热又不浪费体积
    if t_dates and t_dates[0] in qqq:
        start = max(0, dates.index(t_dates[0]) - MA200_WARMUP)
        dates = dates[start:]

    return {
        "meta": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": source,
            "adjust": meta.get("adjust", "unknown"),
            "degraded": bool(meta.get("degraded")),
            "note": meta.get("note", ""),
            "qqq": {"start": dates[0], "end": dates[-1], "bars": len(dates)},
            "tqqq": {"start": t_dates[0], "end": t_dates[-1], "bars": len(t_dates)},
            "backtest_from": t_dates[0],
            "warnings": warns,
        },
        "dates": dates,
        "qqq": [round(qqq[d], 4) for d in dates],
        # TQQQ 上市前用 null 占位，保持与 dates 等长、按下标对齐
        "tqqq": [round(tqqq[d], 4) if d in tqqq else None for d in dates],
    }


# ============================================================
def main() -> int:
    log("=" * 62)
    log("TQQQ 交易指引工具 · 行情数据抓取")
    log("=" * 62)

    providers = [
        ("yfinance", fetch_yfinance),
        ("alphavantage", fetch_alphavantage),
        ("cn-fallback", fetch_cn_fallback),
    ]

    chosen = None
    for pname, provider in providers:
        log(f"\n[数据源] {pname}")
        try:
            cands = provider()
        except Exception as exc:  # noqa: BLE001
            log(f"  异常: {exc}")
            continue
        if not cands:
            log("  无可用候选")
            continue

        for idx, cand in enumerate(cands, 1):
            qqq, tqqq = cand["QQQ"], cand["TQQQ"]
            if len(cands) > 1:
                log(f"  — 候选 {idx}/{len(cands)}: QQQ {len(qqq)} / TQQQ {len(tqqq)} 根")
            errs, warns = validate(qqq, tqqq)
            for w in warns:
                log(f"    [警告] {w}")
            if errs:
                for e in errs:
                    log(f"    [校验失败] {e}")
                log("    → 丢弃该候选")
                continue
            chosen = (pname, qqq, tqqq, warns, cand.get("meta", {}))
            log(f"  [通过] 采用 {pname} 候选 {idx}")
            break
        if chosen:
            break

    if chosen is None:
        log("\n所有数据源均未通过校验 —— 不生成 market.json")
        return 1

    name, qqq, tqqq, warns, meta = chosen
    payload = build_payload(qqq, tqqq, name, warns, meta)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, separators=(",", ":"))

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(OUT)

    # 同时输出一份 .js 包装。原因：用 file:// 直接双击打开 HTML 时，
    # fetch('data/market.json') 会被 CORS 拦掉，而 <script src> 不会。
    # 有它才能做到「不启服务器、双击即用」。
    js_path = OUT.with_suffix(".js")
    tmp_js = js_path.with_suffix(".js.tmp")
    tmp_js.write_text(
        "/* 自动生成，请勿手工编辑。由 scripts/fetch_data.py 产出 */\n"
        f"window.MARKET_DATA = {body};\n",
        encoding="utf-8",
    )
    tmp_js.replace(js_path)

    m = payload["meta"]
    size_kb = OUT.stat().st_size / 1024
    log(f"\n已写入 {OUT.relative_to(ROOT)}  ({size_kb:.0f} KB)")
    log(f"  QQQ  {m['qqq']['start']} → {m['qqq']['end']}  ({m['qqq']['bars']} 根)")
    log(f"  TQQQ {m['tqqq']['start']} → {m['tqqq']['end']}  ({m['tqqq']['bars']} 根)")
    log(f"  回测起点 {m['backtest_from']}（TQQQ 数据起点，另需 MA200 预热）")
    if m["degraded"]:
        log("  ⚠️  降级模式：国内兜底源，历史深度受限")
        log(f"     {m['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
