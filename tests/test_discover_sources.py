"""Tests for GitHub awesome source discovery."""

import json

from scripts.discover_sources import GitHubDiscoverer, SourceInfo


class FakeResponse:
    def __init__(self, status_code, text="", headers=None, payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload
        if payload is not None and not text:
            self.text = json.dumps(payload)

    def json(self):
        if self._payload is not None:
            return self._payload
        return json.loads(self.text or "{}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=30, headers=None):
        self.calls.append((url, params, timeout, headers or {}))
        return self.responses.pop(0)


def test_github_discoverer_uses_bearer_token_and_api_version():
    discoverer = GitHubDiscoverer(token="ghp_test", api_version="2026-03-10")

    assert discoverer.session.headers["Authorization"] == "Bearer ghp_test"
    assert discoverer.session.headers["Accept"] == "application/vnd.github+json"
    assert discoverer.session.headers["X-GitHub-Api-Version"] == "2026-03-10"


def test_github_discoverer_reads_gh_token_from_environment(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_from_env")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    discoverer = GitHubDiscoverer()

    assert discoverer.session.headers["Authorization"] == "Bearer ghp_from_env"


def test_github_discoverer_falls_back_to_github_token_environment(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "github_token_from_env")

    discoverer = GitHubDiscoverer()

    assert discoverer.session.headers["Authorization"] == "Bearer github_token_from_env"


def test_search_rate_limit_waits_for_retry_after_and_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr("scripts.discover_sources.time.sleep", lambda seconds: sleeps.append(seconds))
    discoverer = GitHubDiscoverer(max_rate_limit_sleep_seconds=10, search_interval_seconds=0)
    discoverer.session = FakeSession(
        [
            FakeResponse(403, "secondary limit", headers={"retry-after": "2"}),
            FakeResponse(200, payload={"items": [{"full_name": "owner/repo"}]}),
        ]
    )

    items = discoverer._search_repos("awesome CAD")

    assert items == [{"full_name": "owner/repo"}]
    assert sleeps == [2]
    assert len(discoverer.session.calls) == 2


def test_rate_limit_reset_longer_than_cap_stops_discovery(monkeypatch):
    sleeps = []
    monkeypatch.setattr("scripts.discover_sources.time.sleep", lambda seconds: sleeps.append(seconds))
    discoverer = GitHubDiscoverer(max_rate_limit_sleep_seconds=5, search_interval_seconds=0)
    discoverer.session = FakeSession(
        [
            FakeResponse(
                403,
                "rate limit",
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"},
            )
        ]
    )

    sources = discoverer.discover(["CAD", "B-Rep", "CSG"])

    assert sources == []
    assert sleeps == []
    assert len(discoverer.session.calls) == 1


def test_conditional_request_uses_cached_etag_on_304(tmp_path):
    cache_path = tmp_path / "github-cache.json"
    discoverer = GitHubDiscoverer(cache_path=cache_path, core_interval_seconds=0)
    discoverer.session = FakeSession(
        [
            FakeResponse(200, headers={"etag": '"v1"'}, payload={"full_name": "owner/repo"}),
            FakeResponse(304),
        ]
    )

    first = discoverer._get_json("https://api.github.com/repos/owner/repo", bucket="core")
    second = discoverer._get_json("https://api.github.com/repos/owner/repo", bucket="core")

    assert first == {"full_name": "owner/repo"}
    assert second == {"full_name": "owner/repo"}
    assert discoverer.session.calls[1][3]["If-None-Match"] == '"v1"'


def test_search_rate_limit_does_not_block_core_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr("scripts.discover_sources.time.sleep", lambda seconds: sleeps.append(seconds))
    discoverer = GitHubDiscoverer(max_rate_limit_sleep_seconds=5, search_interval_seconds=0, core_interval_seconds=0)
    discoverer.session = FakeSession(
        [
            FakeResponse(
                403,
                "search limit",
                headers={"x-ratelimit-resource": "search", "x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"},
            ),
            FakeResponse(200, payload={"full_name": "owner/repo"}),
        ]
    )

    assert discoverer._search_repos("awesome CAD") == []
    assert discoverer._get_json("https://api.github.com/repos/owner/repo", bucket="core") == {"full_name": "owner/repo"}
    assert sleeps == []
    assert len(discoverer.session.calls) == 2


def test_discover_filters_irrelevant_high_star_sources(monkeypatch):
    monkeypatch.setattr("scripts.discover_sources.time.sleep", lambda seconds: None)
    discoverer = GitHubDiscoverer(search_interval_seconds=0)
    discoverer.session = FakeSession(
        [
            FakeResponse(
                200,
                payload={
                    "items": [
                        {
                            "full_name": "misc/osint-tools",
                            "html_url": "https://github.com/misc/osint-tools",
                            "stargazers_count": 9000,
                            "description": "Unrelated OSINT resources",
                            "default_branch": "main",
                            "topics": ["awesome", "security"],
                        },
                        {
                            "full_name": "cad/awesome-neural-cad",
                            "html_url": "https://github.com/cad/awesome-neural-cad",
                            "stargazers_count": 100,
                            "description": "Curated CAD generation and B-Rep papers",
                            "default_branch": "main",
                            "topics": ["awesome", "cad", "brep"],
                        },
                    ]
                },
            ),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
            FakeResponse(200, payload={"items": []}),
        ]
    )

    sources = discoverer.discover(["CAD", "B-Rep"], min_stars=5, max_sources=10)

    assert [source.full_name for source in sources] == ["cad/awesome-neural-cad"]


def test_source_relevance_requires_cad_anchor_for_ai4cad_terms():
    terms = GitHubDiscoverer._keyword_terms(["AI for CAD", "CAD program", "computer-aided design"])
    irrelevant = {
        "full_name": "misc/awesome-programmers",
        "html_url": "https://github.com/misc/awesome-programmers",
        "stargazers_count": 1000,
        "description": "Curated programming resources and design links",
        "default_branch": "main",
        "topics": ["awesome", "programming"],
    }
    relevant = {
        "full_name": "cad/awesome-neural-cad",
        "html_url": "https://github.com/cad/awesome-neural-cad",
        "stargazers_count": 100,
        "description": "Curated neural CAD and B-Rep generation papers",
        "default_branch": "main",
        "topics": ["awesome", "cad", "brep"],
    }

    assert not GitHubDiscoverer._source_matches_terms(GitHubDiscoverer._item_to_source(irrelevant), terms)
    assert GitHubDiscoverer._source_matches_terms(GitHubDiscoverer._item_to_source(relevant), terms)


def test_discover_ranks_relevant_awesome_repos_above_generic_high_star_repos(monkeypatch):
    discoverer = GitHubDiscoverer()

    items = [
        {
            "full_name": "josephmisiti/awesome-machine-learning",
            "html_url": "https://github.com/josephmisiti/awesome-machine-learning",
            "stargazers_count": 73122,
            "description": "A curated list of awesome machine learning frameworks",
            "default_branch": "master",
            "topics": ["awesome-list", "machine-learning"],
        },
        {
            "full_name": "EvoAgentX/Awesome-Self-Evolving-Agents",
            "html_url": "https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents",
            "stargazers_count": 2300,
            "description": "Awesome papers for Self-Evolving AI Agents",
            "default_branch": "main",
            "topics": ["awesome-list", "llm-agents", "self-evolving-agents"],
        },
        {
            "full_name": "EvoMap/awesome-agent-evolution",
            "html_url": "https://github.com/EvoMap/awesome-agent-evolution",
            "stargazers_count": 145,
            "description": "AI Agent evolution, memory systems, multi-agent architectures, and self-improvement projects",
            "default_branch": "main",
            "topics": ["awesome-list", "ai-agents", "agent-evolution"],
        },
    ]

    def fake_search(query, sort="stars", order="desc", per_page=10):
        if query == "topic:awesome-list":
            return items
        return []

    monkeypatch.setattr(discoverer, "_search_repos", fake_search)
    monkeypatch.setattr("scripts.discover_sources.time.sleep", lambda _: None)

    sources = discoverer.discover(
        ["agent skill learning", "skill evolution", "self-improving agent"],
        min_stars=5,
        max_sources=3,
    )

    assert [source.full_name for source in sources] == [
        "EvoAgentX/Awesome-Self-Evolving-Agents",
        "EvoMap/awesome-agent-evolution",
        "josephmisiti/awesome-machine-learning",
    ]


def test_discover_uses_query_expansion_terms_for_relevance_ranking():
    generic = SourceInfo(
        full_name="josephmisiti/awesome-machine-learning",
        html_url="https://github.com/josephmisiti/awesome-machine-learning",
        stars=73122,
        description="A curated list of awesome machine learning frameworks",
        default_branch="master",
        topics=["awesome-list", "machine-learning"],
    )
    relevant = SourceInfo(
        full_name="EvoMap/awesome-agent-evolution",
        html_url="https://github.com/EvoMap/awesome-agent-evolution",
        stars=145,
        description="AI Agent evolution and self-improvement projects",
        default_branch="main",
        topics=["awesome-list", "ai-agents"],
    )

    ranked = GitHubDiscoverer.rank_sources(
        [generic, relevant],
        keywords=["agent skill learning"],
        query_expansion=["agent evolution", "self-improvement"],
    )

    assert [source.full_name for source in ranked] == [
        "EvoMap/awesome-agent-evolution",
        "josephmisiti/awesome-machine-learning",
    ]


def test_discover_does_not_query_auto_derived_ranking_terms(monkeypatch):
    discoverer = GitHubDiscoverer()
    queries = []

    def fake_search(query, sort="stars", order="desc", per_page=10):
        queries.append(query)
        return []

    monkeypatch.setattr(discoverer, "_search_repos", fake_search)
    monkeypatch.setattr("scripts.discover_sources.time.sleep", lambda _: None)

    discoverer.discover(
        ["agent skill learning"],
        min_stars=5,
        max_sources=3,
        query_expansion=["agent evolution"],
    )

    joined = "\n".join(queries)
    assert "agent evolution" in joined
    assert "self evolving agents" not in joined
    assert "llm agents" not in joined
