"""Vendor router must respect the configured chain and never silently hide a
broken primary.

Regressions for #988 (explicit single-vendor config still fell back to others),
#289 (fallback ran for unchosen vendors), and #989 (serious primary failures
were swallowed without a trace).
"""
import copy
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


def _reset_config():
    # Hard reset: set_config() merges, so empty DEFAULT dicts (e.g. tool_vendors)
    # don't clear keys leaked by other tests. Replace the global outright.
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _no_data(symbol, *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows")


def _returns(value):
    def impl(symbol, *a, **k):
        return value
    return impl


def _raises(exc):
    def impl(symbol, *a, **k):
        raise exc
    return impl


@pytest.mark.unit
class VendorRoutingTests(unittest.TestCase):
    def setUp(self):
        _reset_config()

    def tearDown(self):
        _reset_config()

    def _route(self, vendors_for_get_stock_data):
        return mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": vendors_for_get_stock_data},
            clear=False,
        )

    def test_explicit_single_vendor_does_not_fall_back(self):
        # #988: with yfinance pinned, a healthy alpha_vantage must NOT be used.
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
        av = mock.Mock(side_effect=_returns("AV_DATA"))
        with self._route({"yfinance": _no_data, "alpha_vantage": av}):
            result = interface.route_to_vendor("get_stock_data", "FAKE", "2026-01-01", "2026-01-10")
        self.assertIn("NO_DATA_AVAILABLE", result)
        av.assert_not_called()  # the unchosen vendor was never tried

    def test_explicit_multi_vendor_falls_back_within_chain(self):
        # Listing both vendors opts in to ordered fallback.
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})
        with self._route({"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA")}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "AV_DATA")

    def test_failure_text_from_vendor_falls_back(self):
        # akshare/yfinance compatibility paths historically returned a failure
        # message instead of raising. The router must not treat that text as a
        # successful report and stop before the next configured vendor.
        set_config({"data_vendors": {"fundamental_data": "akshare,yfinance"}})
        with self._route_method(
            "get_fundamentals",
            {
                "akshare": lambda *a, **k: "通过 akshare 无法获取 'AAPL' 的基本面数据（不支持的市场代码）。",
                "yfinance": lambda *a, **k: "YF_DATA",
            },
        ):
            result = interface.route_to_vendor("get_fundamentals", "AAPL", "2026-09-23")
        self.assertEqual(result, "YF_DATA")

    def test_alpha_vantage_error_json_falls_back(self):
        set_config({"data_vendors": {"fundamental_data": "alpha_vantage,yfinance"}})
        with self._route_method(
            "get_fundamentals",
            {
                "alpha_vantage": lambda *a, **k: '{"Error Message":"Invalid API call."}',
                "yfinance": lambda *a, **k: "YF_DATA",
            },
        ):
            result = interface.route_to_vendor("get_fundamentals", "AAPL", "2026-09-23")
        self.assertEqual(result, "YF_DATA")

    def test_empty_news_from_first_vendor_falls_back_for_all_supported_markets(self):
        for ticker in ("AAPL", "600519.SS", "0700.HK"):
            with self.subTest(ticker=ticker):
                _reset_config()
                set_config({"data_vendors": {"news_data": "akshare,yfinance,alpha_vantage"}})
                seen = []

                def empty_news(symbol, *args, _seen=seen, **kwargs):
                    _seen.append(("akshare", symbol))
                    return f"未找到 {symbol} 的新闻。"

                def yahoo_news(symbol, *args, _seen=seen, **kwargs):
                    _seen.append(("yfinance", symbol))
                    return f"## {symbol} 的新闻\n### 标题"

                with self._route_method(
                    "get_news",
                    {
                        "akshare": empty_news,
                        "yfinance": yahoo_news,
                        "alpha_vantage": mock.Mock(side_effect=AssertionError("must stop after success")),
                    },
                ):
                    result = interface.route_to_vendor(
                        "get_news", ticker, "2026-09-18", "2026-09-25"
                    )

                self.assertIn("标题", result)
                self.assertEqual(seen, [("akshare", ticker), ("yfinance", ticker)])

    def test_alpha_vantage_empty_feed_falls_back(self):
        set_config({"data_vendors": {"news_data": "alpha_vantage,yfinance"}})
        with self._route_method(
            "get_news",
            {
                "alpha_vantage": lambda *a, **k: '{"items": 0, "feed": []}',
                "yfinance": lambda *a, **k: "YF_NEWS",
            },
        ):
            result = interface.route_to_vendor("get_news", "AAPL", "2026-09-18", "2026-09-25")
        self.assertEqual(result, "YF_NEWS")

    def test_all_empty_news_sources_return_explicit_unavailable_result(self):
        set_config({"data_vendors": {"news_data": "akshare,yfinance,alpha_vantage"}})
        with self._route_method(
            "get_news",
            {
                "akshare": lambda *a, **k: "未找到 AAPL 的新闻。",
                "yfinance": lambda *a, **k: "在 2026-09-18 至 2026-09-25 期间未找到 AAPL 的新闻。",
                "alpha_vantage": lambda *a, **k: '{"items": 0, "feed": []}',
            },
        ):
            result = interface.route_to_vendor("get_news", "AAPL", "2026-09-18", "2026-09-25")
        self.assertIn("NEWS_UNAVAILABLE", result)
        self.assertIn("akshare", result)
        self.assertIn("yfinance", result)
        self.assertIn("alpha_vantage", result)
        self.assertIn("不要编造新闻", result)

    def test_news_route_reports_actual_vendor(self):
        set_config({"data_vendors": {"news_data": "akshare,yfinance"}})
        with self._route_method(
            "get_news",
            {
                "akshare": lambda *a, **k: "未找到 AAPL 的新闻。",
                "yfinance": lambda *a, **k: "YF_NEWS",
            },
        ):
            result, vendor = interface.route_to_vendor_with_source(
                "get_news", "AAPL", "2026-09-18", "2026-09-25"
            )
        self.assertEqual((result, vendor), ("YF_NEWS", "yfinance"))

    def test_primary_error_is_logged_not_masked(self):
        # #989: primary errors + fallback no-data -> NO_DATA, but the failure
        # must be visible in logs (broken primary not hidden).
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})
        with self._route({"yfinance": _raises(ValueError("boom")), "alpha_vantage": _no_data}), \
                self.assertLogs("tradingagents.dataflows.interface", level="WARNING") as cm:
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("NO_DATA_AVAILABLE", result)
        joined = "\n".join(cm.output)
        self.assertIn("boom", joined)            # the real error surfaced in logs
        self.assertIn("yfinance", joined)

    def test_unknown_configured_vendor_raises(self):
        set_config({"data_vendors": {"core_stock_apis": "bogus_vendor"}})
        with self.assertRaises(ValueError) as ctx:
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("bogus_vendor", str(ctx.exception))

    def test_default_sentinel_uses_all_vendors(self):
        # No explicit choice ("default") keeps the resilient full-chain behavior.
        set_config({"data_vendors": {"core_stock_apis": "default"}})
        with self._route({"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA")}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "AV_DATA")

    def _route_method(self, method, vendors):
        return mock.patch.dict(interface.VENDOR_METHODS, {method: vendors}, clear=False)

    def test_optional_category_degrades_instead_of_raising(self):
        # An optional enrichment vendor (FRED macro) that raises must NOT abort
        # the run — the router returns a sentinel so the analysis proceeds.
        set_config({"data_vendors": {"macro_data": "fred"}})
        with self._route_method(
            "get_macro_indicators", {"fred": _raises(ValueError("FRED 400: bad series"))}
        ):
            result = interface.route_to_vendor("get_macro_indicators", "cpi", "2026-01-01")
        self.assertIn("DATA_UNAVAILABLE", result)
        self.assertIn("macro_data", result)

    def test_core_category_still_raises_on_error(self):
        # A core category (single configured vendor) propagates the error so a
        # broken primary is loud, not silently degraded.
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
        with self._route({"yfinance": _raises(ValueError("boom"))}), \
                self.assertRaises(ValueError):
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")


if __name__ == "__main__":
    unittest.main()
