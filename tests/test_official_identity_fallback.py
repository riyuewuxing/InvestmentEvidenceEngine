from investment_evidence_engine import sources


def test_official_spec_skips_wrong_identity(monkeypatch):
    first = "https://www.sse.com.cn/a"
    second = "https://www.sse.com.cn/b"
    spec = sources.OfficialSourceSpec("test", first, ("目标 公告",), (second,))
    seen = []

    def fetch(url, timeout):
        seen.append(url)
        return sources.FetchedOfficialSource(url, "目标公告" if url == second else "登录页面", "a" * 64, "text/html")

    monkeypatch.setattr(sources, "fetch_official_url", fetch)
    result, failures = sources.fetch_official_spec(spec)
    assert result.url == second
    assert seen == [first, second]
    assert failures == [first + "::EXPECTED_IDENTITY_TOKENS_MISSING"]
