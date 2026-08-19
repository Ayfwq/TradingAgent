"""Offline unit tests for the akshare vendor (no network).

Mocks the akshare module functions so the vendor's contract — column shapes,
date filtering, symbol mapping, graceful degradation — is verified fast and
deterministically in CI. The live-network counterpart lives at
scripts/test_akshare_vendor.py (run manually / integration).

Run:  uv run --quiet python -m pytest tests/test_akshare_vendor_mock.py -q
"""

from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import akshare_data as akv


@pytest.fixture
def monkey_ak(monkeypatch):
    """Provide a stub akshare module whose functions can be overridden per-test."""

    class _StubAK:
        pass

    stub = _StubAK()

    def _set(name, func):
        setattr(stub, name, func)

    monkeypatch.setattr("akshare.stock_zh_a_daily", lambda **k: _daily_df())
    return stub


def _daily_df(n=10, start="2026-01-01"):
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.5] * n,
            "volume": [1000] * n,
        }
    )


class TestSymbolMapping:
    def test_ashare_suffixes(self):
        assert akv._to_akshare_symbol("600519.SS") == ("ashare", "sh600519")
        assert akv._to_akshare_symbol("000001.SZ") == ("ashare", "sz000001")
        assert akv._to_akshare_symbol("920002.BJ") == ("ashare", "bj920002")

    def test_bare_6digit(self):
        assert akv._to_akshare_symbol("300750") == ("ashare", "sz300750")
        assert akv._to_akshare_symbol("688981") == ("ashare", "sh688981")
        assert akv._to_akshare_symbol("832566") == ("ashare", "bj832566")

    def test_us_and_hk(self):
        assert akv._to_akshare_symbol("NVDA") == ("us", "NVDA")
        assert akv._to_akshare_symbol("0700.HK") == ("hk", "00700")

    def test_unsupported(self):
        assert akv._to_akshare_symbol("")[0] is None


class TestOhlcvContract:
    def test_load_ohlcv_capitalized_and_filtered(self, monkeypatch):
        def fake_daily(symbol, start_date, end_date, adjust="qfq"):
            return _daily_df(n=30, start="2026-01-01")

        monkeypatch.setattr("akshare.stock_zh_a_daily", fake_daily)
        df = akv.load_ohlcv_akshare("600519.SS", "2026-01-15")
        assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
        assert (df["Date"] <= pd.Timestamp("2026-01-15")).all()

    def test_load_ohlcv_no_rows_raises(self, monkeypatch):
        def fake_daily(symbol, start_date, end_date, adjust="qfq"):
            raise ValueError("boom")

        monkeypatch.setattr("akshare.stock_zh_a_daily", fake_daily)
        with pytest.raises(akv.NoMarketDataError):
            akv.load_ohlcv_akshare("600519.SS", "2026-01-15")

    def test_get_stock_data_csv_shape(self, monkeypatch):
        monkeypatch.setattr("akshare.stock_zh_a_daily", lambda **k: _daily_df())
        out = akv.get_stock_data_akshare("600519.SS", "2026-01-01", "2026-01-10")
        assert "Date,Open,High,Low,Close,Volume" in out


class TestDegradation:
    """Vendor functions must return short strings (never crash) on failure."""

    def test_fundamentals_failure_is_string(self, monkeypatch):
        def bad(*a, **k):
            raise ConnectionError("network down")

        monkeypatch.setattr("akshare.stock_financial_analysis_indicator", bad)
        out = akv.get_fundamentals_akshare("600519.SS", "2026-08-17")
        assert isinstance(out, str) and "Error" in out

    def test_news_failure_is_string(self, monkeypatch):
        def bad(*a, **k):
            raise TimeoutError("slow")

        monkeypatch.setattr("akshare.stock_news_em", bad)
        out = akv.get_news_akshare("600519.SS", "2026-08-14", "2026-08-17")
        assert isinstance(out, str)

    def test_non_ashare_returns_graceful_message(self):
        out = akv.get_fundamentals_akshare("NVDA", "2026-08-17")
        assert "unavailable" in out.lower()


class TestSpecialContextTools:
    def test_lhb_match_and_miss(self, monkeypatch):
        def fake_lhb(start_date, end_date):
            return pd.DataFrame(
                {
                    "代码": ["600519"],
                    "名称": ["贵州茅台"],
                    "上榜日": [pd.Timestamp("2026-08-12")],
                    "涨跌幅": [3.5],
                    "龙虎榜净买额": [123456.0],
                    "上榜原因": ["日涨幅偏离值达7%"],
                    "上榜后1日": [1.2],
                    "上榜后2日": [0.8],
                    "上榜后5日": [2.1],
                }
            )

        monkeypatch.setattr("akshare.stock_lhb_detail_em", fake_lhb)
        out = akv.get_lhb_context("600519.SS", "2026-08-17")
        assert "600519" in out and "上榜原因" in out

        monkeypatch.setattr("akshare.stock_lhb_detail_em", lambda **k: pd.DataFrame({"代码": ["000001"]}))
        out2 = akv.get_lhb_context("600519.SS", "2026-08-17")
        assert "No LHB" in out2

    def test_limit_up_pool(self, monkeypatch):
        def fake_pool(date):
            return pd.DataFrame(
                {
                    "代码": ["002820", "603330"],
                    "名称": ["桂发祥", "天洋新材"],
                    "涨跌幅": [9.96, 10.0],
                    "连板数": [2, 4],
                    "封板资金": [1e8, 2e8],
                    "所属行业": ["休闲食品", "塑料"],
                    "换手率": [2.4, 5.0],
                }
            )

        monkeypatch.setattr("akshare.stock_zt_pool_em", fake_pool)
        out = akv.get_limit_up_context("600519.SS", "2026-08-17")
        assert "NOT on today" in out and "Total limit-up" in out

        out2 = akv.get_limit_up_context("002820.SZ", "2026-08-17")
        assert "IS LIMIT-UP" in out2

    def test_sector_context(self, monkeypatch):
        def fake_spot(indicator):
            return pd.DataFrame(
                {
                    "label": ["a", "b"],
                    "板块": ["机械行业", "生物制药"],
                    "涨跌幅": [3.6, -0.1],
                    "股票代码": ["sh600860", "sh600613"],
                    "股票名称": ["京城股份", "神奇制药"],
                    "个股-涨跌幅": [10.0, 9.9],
                    "个股-当前价": [9.4, 7.0],
                }
            )

        monkeypatch.setattr("akshare.stock_sector_spot", fake_spot)
        out = akv.get_sector_context("600519.SS", "2026-08-17")
        assert "机械行业" in out
        out2 = akv.get_sector_context("600860.SS", "2026-08-17")
        assert "IS the leader stock" in out2

    def test_earnings_forecast(self, monkeypatch):
        def fake_yjyg(date):
            return pd.DataFrame(
                {
                    "股票代码": ["600519"],
                    "股票简称": ["贵州茅台"],
                    "预测指标": ["归属于上市公司股东的净利润"],
                    "业绩变动": ["预计增长"],
                    "预告类型": ["预增"],
                    "公告日期": [pd.Timestamp("2026-07-10")],
                }
            )

        monkeypatch.setattr("akshare.stock_yjyg_em", fake_yjyg)
        out = akv.get_earnings_forecast("600519.SS", "2026-08-17")
        assert "业绩预告" in out or "600519" in out

    def test_northbound_flow(self, monkeypatch):
        def fake_hist(symbol):
            return pd.DataFrame(
                {"日期": pd.bdate_range("2026-08-01", periods=15), "当日成交净买额": [1.0] * 15}
            )

        def fake_summary():
            return pd.DataFrame({"板块": ["沪股通"], "资金方向": ["北向"], "成交净买额": [0.0]})

        monkeypatch.setattr("akshare.stock_hsgt_hist_em", fake_hist)
        monkeypatch.setattr("akshare.stock_hsgt_fund_flow_summary_em", fake_summary)
        out = akv.get_northbound_flow("2026-08-17")
        assert "北向资金" in out


class TestRealizedReturns:
    def test_returns_computed(self, monkeypatch):
        closes = [10.0, 10.5, 11.0]

        def fake_daily(symbol, start_date, end_date, adjust="qfq"):
            n = len(closes)
            return pd.DataFrame(
                {
                    "date": pd.bdate_range("2026-05-15", periods=n),
                    "open": closes, "high": closes, "low": closes,
                    "close": closes, "volume": [1] * n,
                }
            )

        monkeypatch.setattr("akshare.stock_zh_a_daily", fake_daily)
        raw, alpha, days = akv.get_market_returns("600519.SS", "2026-05-15", 2, "000001.SS")
        assert raw == pytest.approx(0.10)
        assert days == 2
        assert alpha is not None

    def test_returns_none_on_error(self, monkeypatch):
        def bad(*a, **k):
            raise ConnectionError("no network")

        monkeypatch.setattr("akshare.stock_zh_a_daily", bad)
        assert akv.get_market_returns("600519.SS", "2026-05-15", 5, "000001.SS") == (None, None, None)

