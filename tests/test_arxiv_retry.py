import requests


def test_arxiv_retry_wait_respects_retry_after_header():
    from scripts.sync import _arxiv_retry_wait

    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "17"
    error = requests.HTTPError("rate limited", response=response)

    assert _arxiv_retry_wait(error, 0) == 17


def test_arxiv_retry_wait_uses_longer_backoff_for_429(monkeypatch):
    from scripts.sync import _arxiv_retry_wait

    monkeypatch.setenv("ARXIV_429_BACKOFF_SECONDS", "12")
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError("rate limited", response=response)

    assert _arxiv_retry_wait(error, 1) == 12
