import json

from web import report_history


def test_list_and_load_persisted_report_tree(tmp_path, monkeypatch):
    monkeypatch.setitem(report_history.DEFAULT_CONFIG, "results_dir", str(tmp_path))
    directory = tmp_path / "reports" / "AAPL_20260822_120000"
    (directory / "1_analysts").mkdir(parents=True)
    (directory / "2_research").mkdir()
    (directory / "3_trading").mkdir()
    (directory / "4_risk").mkdir()
    (directory / "5_portfolio").mkdir()
    (directory / "complete_report.md").write_text("# report", encoding="utf-8")
    (directory / "5_portfolio" / "decision.md").write_text(
        "**Rating**: Buy\n\n**Executive Summary**: 中文摘要", encoding="utf-8"
    )
    (directory / "3_trading" / "trader.md").write_text(
        "**Entry Price**: 100", encoding="utf-8"
    )
    (directory / "1_analysts" / "news.md").write_text("新闻报告", encoding="utf-8")
    (directory / "metadata.json").write_text(
        json.dumps({
            "ticker": "AAPL",
            "trade_date": "2026-08-21",
            "asset_type": "stock",
            "generated_at": "2026-08-22 12:00:00",
        }),
        encoding="utf-8",
    )

    listed = report_history.list_reports(ticker="AAPL")
    assert listed["total"] == 1
    assert listed["reports"][0]["trade_date"] == "2026-08-21"

    detail = report_history.get_report("AAPL_20260822_120000")
    assert detail["result"]["decision"] == "Buy"
    assert detail["result"]["trader_fields"]["entry_price"] == "100"
    assert detail["result"]["reports"]["news"] == "新闻报告"
