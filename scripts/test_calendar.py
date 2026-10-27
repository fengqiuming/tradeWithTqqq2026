#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易日历与新鲜度判定测试（无外部依赖，直接 python3 运行）。

用法：python3 scripts/test_calendar.py
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import (  # noqa: E402
    ET, expected_last_trading_day, nyse_holidays, trading_days_behind,
)

OK = True


def check(name, cond, extra=""):
    global OK
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  → {extra}" if extra else ""))
    if not cond:
        OK = False


print("=== 1. NYSE 假日抽查（规则生成的年份必须命中） ===")
H2026 = nyse_holidays(2026)
for d, label in [
    (date(2026, 1, 1), "元旦"),
    (date(2026, 1, 19), "MLK（1 月第 3 个周一）"),
    (date(2026, 2, 16), "华盛顿日（2 月第 3 个周一）"),
    (date(2026, 4, 3), "耶稣受难日（复活节推算）"),
    (date(2026, 5, 25), "Memorial（5 月最后周一）"),
    (date(2026, 7, 3), "独立日：2026-07-04 是周六 → 提前至周五"),
    (date(2026, 9, 7), "劳工节（9 月第 1 个周一）"),
    (date(2026, 10, 12), "哥伦布日（10 月第 2 个周一）"),
    (date(2026, 11, 26), "感恩节（11 月第 4 个周四）"),
    (date(2026, 12, 25), "圣诞节"),
]:
    check(f"{label} {d}", d in H2026, str(d))

# 落在周日 → 顺延周一：2026-06-19 周五正常；换 2027-06-19（周六）→ 提前至 06-18
check("六月节落在周六时提前至周五",
      date(2027, 6, 18) in nyse_holidays(2027) and date(2027, 6, 19) not in nyse_holidays(2027))
check("正常交易日不算假日（2026-10-26 周一）", date(2026, 10, 26) not in H2026)
check("周末永远不是交易日判定的一部分（周末在假日表外）",
      date(2026, 10, 24) not in H2026 and date(2026, 10, 24).weekday() == 5)

print("\n=== 2. 落后交易日计算 ===")
EXP = date(2026, 10, 26)   # 周一
check("止于 10-23（周五）→ 落后 1", trading_days_behind("2026-10-23", EXP) == 1)
check("止于 10-26 → 落后 0", trading_days_behind("2026-10-26", EXP) == 0)
check("止于 10-19（上周一）→ 落后 5", trading_days_behind("2026-10-19", EXP) == 5)
check("比预期更新（不应出现，返回 0）", trading_days_behind("2026-10-27", EXP) == 0)
# 跨哥伦布日：预期 10-13（周二），止于 10-09（周五）→ 中间隔开 10-12 假日，落后 1
check("跨哥伦布日假期不误算", trading_days_behind("2026-10-09", date(2026, 10, 13)) == 1)
# 跨感恩节：预期 11-27（周五），止于 11-25（周三）→ 11-26 假日，落后 1
check("跨感恩节假期不误算", trading_days_behind("2026-11-25", date(2026, 11, 27)) == 1)

print("\n=== 3. 预期交易日随时钟变化 ===")
# 17:00 ET 之后 → 当天（若为交易日）；之前 → 上一交易日
at = lambda md, h, mi=0: datetime(2026, md[0], md[1], h, mi, tzinfo=ET)
check("周一 20:00 ET → 预期当天周一",
      expected_last_trading_day(at((10, 26), 20, 0)) == date(2026, 10, 26))
check("周一 16:00 ET（盘中）→ 预期上一周五",
      expected_last_trading_day(at((10, 26), 16, 0)) == date(2026, 10, 23))
check("周六 → 预期上周五",
      expected_last_trading_day(at((10, 24), 20, 0)) == date(2026, 10, 23))
check("假日当天（哥伦布日 10-12）20:00 ET → 预期上周五",
      expected_last_trading_day(at((10, 12), 20, 0)) == date(2026, 10, 9))
check("元旦前一交易日回退跨年",
      expected_last_trading_day(datetime(2027, 1, 1, 20, 0, tzinfo=ET)) == date(2026, 12, 31))

print("\n" + ("交易日历测试通过" if OK else "交易日历测试失败"))
sys.exit(0 if OK else 1)
