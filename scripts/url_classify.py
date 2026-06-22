"""URL 分类工具：区分学术论文与非论文资源。

独立模块，不依赖 slugify 等重型依赖，供 build.py 和 ingest_source.py 共用。
"""
from __future__ import annotations
from typing import Dict

ACADEMIC_DOMAINS = {
    "arxiv.org", "openaccess.thecvf.com", "sciencedirect.com",
    "dl.acm.org", "openreview.net", "proceedings.mlr.press",
    "ieeexplore.ieee.org", "link.springer.com", "springer.com",
    "papers.nips.cc", "aclanthology.org", "papers.ssrn.com",
    "onlinelibrary.wiley.com", "www.worldscientific.com",
    "dblp.org", "semanticscholar.org", "scholar.google.com",
    "proceedings.neurips.cc", "jmlr.org",
}

RESOURCE_TYPE_RULES = [
    (("youtube.com", "youtu.be", "vimeo.com"), "video"),
    (("reddit.com",), "reddit"),
    (("medium.com", "substack.com", "dev.to", "hashnode.dev"), "blog"),
    (("stackoverflow.com", "stackexchange.com"), "forum"),
    (("github.com", "github.io"), "project"),
    (("twitter.com", "x.com"), "social"),
]


def is_academic_url(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return any(d in lowered for d in ACADEMIC_DOMAINS)


def detect_resource_type(url: str) -> str:
    if not url:
        return "website"
    lowered = url.lower()
    for domains, rtype in RESOURCE_TYPE_RULES:
        if any(d in lowered for d in domains):
            return rtype
    return "website"


def entry_is_paper(entry: Dict) -> bool:
    if entry.get("abstract"):
        return True
    for value in (entry.get("links") or {}).values():
        if is_academic_url(str(value)):
            return True
    return False
