from datetime import datetime as RealDatetime


def test_fetch_all_hf_papers_caps_daily_window_by_default(monkeypatch):
    from scripts import hf_source

    calls = {}

    class FixedDatetime(RealDatetime):
        @classmethod
        def now(cls):
            return cls(2026, 7, 2)

    def fake_daily(start_date, end_date):
        calls["daily"] = (start_date, end_date)
        return []

    monkeypatch.setattr(hf_source, "datetime", FixedDatetime)
    monkeypatch.setattr(hf_source, "fetch_hf_daily_papers", fake_daily)

    hf_source.fetch_all_hf_papers(
        {
            "research": {
                "date_from": "2023-01-01",
                "sources": {"huggingface_daily": True, "huggingface_trending": False},
            }
        }
    )

    assert calls["daily"] == ("2026-06-25", "2026-07-02")


def test_fetch_all_hf_papers_uses_configured_daily_window(monkeypatch):
    from scripts import hf_source

    calls = {}

    class FixedDatetime(RealDatetime):
        @classmethod
        def now(cls):
            return cls(2026, 7, 2)

    def fake_daily(start_date, end_date):
        calls["daily"] = (start_date, end_date)
        return []

    monkeypatch.setattr(hf_source, "datetime", FixedDatetime)
    monkeypatch.setattr(hf_source, "fetch_hf_daily_papers", fake_daily)

    hf_source.fetch_all_hf_papers(
        {
            "research": {
                "date_from": "2023-01-01",
                "huggingface_daily_max_days": 2,
                "sources": {"huggingface_daily": True, "huggingface_trending": False},
            }
        }
    )

    assert calls["daily"] == ("2026-06-30", "2026-07-02")
