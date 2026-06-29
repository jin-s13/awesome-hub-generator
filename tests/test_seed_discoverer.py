import logging

from scripts import seed_discoverer


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_references_returns_empty_after_repeated_rate_limits(monkeypatch, caplog):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response(429)

    monkeypatch.setattr(seed_discoverer.requests, "get", fake_get)
    monkeypatch.setattr(seed_discoverer.time, "sleep", lambda *_args, **_kwargs: None)
    caplog.set_level(logging.WARNING)

    refs = seed_discoverer.fetch_references("2502.10498", max_refs=10)

    assert refs == []
    assert len(calls) == 3
    assert "returned no data" in caplog.text


def test_fetch_references_parses_arxiv_reference(monkeypatch):
    payload = {
        "data": [
            {
                "citedPaper": {
                    "title": "World Model Reference",
                    "abstract": "A useful reference.",
                    "authors": [{"name": "Ada Lovelace"}],
                    "year": 2026,
                    "externalIds": {"ArXiv": "2601.00001"},
                }
            }
        ]
    }

    monkeypatch.setattr(seed_discoverer.requests, "get", lambda *args, **kwargs: _Response(200, payload))

    refs = seed_discoverer.fetch_references("2502.10498", max_refs=10)

    assert refs == [
        {
            "title": "World Model Reference",
            "abstract": "A useful reference.",
            "authors": ["Ada Lovelace"],
            "year": 2026,
            "arxiv_id": "2601.00001",
            "links": {"paper": "https://arxiv.org/abs/2601.00001"},
        }
    ]
