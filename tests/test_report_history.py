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


def test_delete_report_cleans_shared_sidecars_after_last_same_day_report(tmp_path, monkeypatch):
    monkeypatch.setitem(report_history.DEFAULT_CONFIG, "results_dir", str(tmp_path))
    memory_log = tmp_path / "memory" / "trading_memory.md"
    memory_log.parent.mkdir()
    monkeypatch.setitem(report_history.DEFAULT_CONFIG, "memory_log_path", str(memory_log))

    report_root = tmp_path / "reports"
    for report_id in ("AAPL_20260822_120000", "AAPL_20260822_130000"):
        directory = report_root / report_id
        directory.mkdir(parents=True)
        (directory / "complete_report.md").write_text("# report", encoding="utf-8")
        (directory / "metadata.json").write_text(
            json.dumps({"ticker": "AAPL", "trade_date": "2026-08-21"}),
            encoding="utf-8",
        )

    snapshot = tmp_path / "AAPL" / "TradingAgentsStrategy_logs" / "full_states_log_2026-08-21.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"final_trade_decision":"Buy"}', encoding="utf-8")
    memory_log.write_text(
        "[2026-08-21 | AAPL | Buy | pending]\n\nDECISION:\nBuy\n\n<!-- ENTRY_END -->\n\n"
        "[2026-08-21 | MSFT | Hold | pending]\n\nDECISION:\nHold",
        encoding="utf-8",
    )

    assert report_history.delete_report("AAPL_20260822_120000") is True
    assert snapshot.exists()
    assert "AAPL" in memory_log.read_text(encoding="utf-8")

    assert report_history.delete_report("AAPL_20260822_130000") is True
    assert not snapshot.exists()
    memory_contents = memory_log.read_text(encoding="utf-8")
    assert "AAPL" not in memory_contents
    assert "MSFT" in memory_contents
