from unittest.mock import Mock, patch

from web.instrument_search import InstrumentSearchService


def _response(text: str):
    response = Mock()
    response.text = text
    response.raise_for_status.return_value = None
    return response


def test_search_ashare_company_name_without_ai():
    service = InstrumentSearchService()
    text = 'var suggestvalue="贵州茅台,11,600519,sh600519,贵州茅台,,贵州茅台,99,1,ESG,,;";'
    with patch("web.instrument_search.requests.get", return_value=_response(text)):
        result = service.search("贵州茅台", use_ai=False)

    assert result["status"] == "matched"
    assert result["results"][0]["ticker"] == "600519.SS"
    assert result["results"][0]["verified"] is True


def test_search_hk_and_us_canonical_symbols():
    service = InstrumentSearchService()
    text = (
        'var suggestvalue="腾讯控股,31,00700,00700,腾讯控股,,腾讯控股,99,1,ESG,,;'
        '腾讯音乐,41,tme,tme,腾讯音乐,,腾讯音乐,99,1,ESG,,;";'
    )
    with patch("web.instrument_search.requests.get", return_value=_response(text)):
        result = service.search("腾讯", use_ai=False)

    assert [item["ticker"] for item in result["results"]] == ["0700.HK", "TME"]


def test_market_filter_excludes_other_markets():
    service = InstrumentSearchService()
    text = (
        'var suggestvalue="苹果,41,aapl,aapl,苹果,,苹果,99,1,ESG,,;'
        '苹果概念,11,300000,sz300000,苹果概念,,苹果概念,99,1,,,;";'
    )
    with patch("web.instrument_search.requests.get", return_value=_response(text)):
        result = service.search("苹果", market="us", use_ai=False)

    assert [item["ticker"] for item in result["results"]] == ["AAPL"]


def test_directory_order_keeps_primary_equity_ahead_of_name_containing_etf():
    service = InstrumentSearchService()
    text = (
        'var suggestvalue="英伟达,41,nvda,nvda,英伟达,,英伟达,99,1,ESG,,;'
        'PurePlay Nvidia ETF,41,nvps,nvps,PurePlay Nvidia ETF,,PurePlay Nvidia ETF,99,1,,,;";'
    )
    with patch("web.instrument_search.requests.get", return_value=_response(text)):
        result = service.search("NVIDIA", use_ai=False)

    assert [item["ticker"] for item in result["results"]] == ["NVDA", "NVPS"]


def test_ai_expansion_must_still_be_verified_by_directory():
    service = InstrumentSearchService()
    empty = _response('var suggestvalue="";')
    verified = _response('var suggestvalue="英伟达,41,nvda,nvda,英伟达,,英伟达,99,1,ESG,,;";')
    with (
        patch("web.instrument_search.requests.get", side_effect=[empty, verified]),
        patch.object(service, "_expand_with_configured_model", return_value=["英伟达"]),
    ):
        result = service.search("做显卡和AI芯片的美国公司")

    assert result["ai_used"] is True
    assert result["results"][0]["ticker"] == "NVDA"
    assert "证券目录验证" in result["results"][0]["match_reason"]


def test_ai_failure_degrades_without_inventing_ticker():
    service = InstrumentSearchService()
    with (
        patch("web.instrument_search.requests.get", return_value=_response('var suggestvalue="";')),
        patch.object(service, "_expand_with_configured_model", side_effect=RuntimeError("quota")),
    ):
        result = service.search("某个没有明确名称的公司")

    assert result["status"] == "ai_unavailable"
    assert result["results"] == []
