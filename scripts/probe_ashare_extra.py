"""Probe akshare A-share special-data interfaces for availability.

Checks the endpoints used by the A-share enhancement tools (LHB/龙虎榜,
northbound flow/北向资金, margin/两融, earnings forecast/业绩预告,
dividends/分红). Prints OK/FAIL + columns + row count per interface.
Network probe — run manually, not part of CI.

Usage:  uv run --quiet python scripts/probe_ashare_extra.py
"""

from __future__ import annotations

import traceback
from datetime import datetime

import akshare as ak


def probe(name: str, func) -> None:
    try:
        df = func()
        if df is None:
            print(f"{name}: OK (None)")
            return
        print(f"{name}: OK rows={len(df)} cols={list(df.columns)[:12]}")
        if len(df):
            print(f"   head0: {df.iloc[0].to_dict()}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: FAIL {type(exc).__name__}: {str(exc)[:160]}")


def main() -> None:
    today = datetime.now().strftime("%Y%m%d")
    print(f"today={today}\n")

    probe("stock_lhb_detail_em(龙虎榜)", lambda: ak.stock_lhb_detail_em(date=today))
    probe("stock_lhb_stock_detail_em(个股龙虎榜)", lambda: ak.stock_lhb_stock_detail_em(symbol="600519", date=today))
    probe("stock_hsgt_hist_em(北向历史)", lambda: ak.stock_hsgt_hist_em(symbol="北向资金"))
    probe("stock_hsgt_fund_flow_summary_em(北向汇总)", lambda: ak.stock_hsgt_fund_flow_summary_em())
    probe("stock_margin_detail_sse(沪两融)", lambda: ak.stock_margin_detail_sse(date=today))
    probe("stock_margin_detail_szse(深两融)", lambda: ak.stock_margin_detail_szse(date=today))
    probe("stock_yjyg_em(业绩预告)", lambda: ak.stock_yjyg_em(date=today))
    probe("stock_fhps_em(分红送配)", lambda: ak.stock_fhps_em(date=today))
    probe("stock_zt_pool_em(涨停池)", lambda: ak.stock_zt_pool_em(date=today))
    probe("stock_zh_a_spot_em(全A快照)", lambda: ak.stock_zh_a_spot_em())
    probe("stock_board_industry_name_em(行业板块)", lambda: ak.stock_board_industry_name_em())
    probe("stock_board_industry_cons_em(行业成分)", lambda: ak.stock_board_industry_cons_em(symbol="小金属"))
    probe("stock_sector_spot(新浪行业)", lambda: ak.stock_sector_spot(indicator="新浪行业"))
    probe("stock_individual_info_em(个股信息)", lambda: ak.stock_individual_info_em(symbol="600519"))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
