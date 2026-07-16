"""
PubMed client via the free NCBI E-utilities API.

Two-step flow (the E-utilities contract):
  1. esearch  — query → list of PMIDs
  2. efetch   — PMIDs → article XML (title, abstract, journal, authors, year)

urllib is used (not httpx) for consistency with app/clinicaltrials/client.py —
it rides the OS TLS stack and has no extra dependency.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from app.config import get_settings

# NCBI asks all E-utilities clients to identify themselves.
_TOOL_PARAMS = {"tool": "query-to-visualization", "email": "dev@example.com"}


@dataclass
class PubMedArticle:
    pmid: str
    title: str
    journal: str = ""
    year: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


def _get_with_retry(url: str, params: dict) -> bytes:
    """GET with exponential back-off on 429/5xx and transient network errors."""
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"Accept": "*/*"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("Max retries exceeded")


def _base_params() -> dict:
    settings = get_settings()
    params = dict(_TOOL_PARAMS)
    api_key = settings.ncbi_api_key.get_secret_value()
    if api_key:
        params["api_key"] = api_key
    return params


def _esearch(query: str, max_results: int) -> list[str]:
    params = {
        **_base_params(),
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",
    }
    raw = _get_with_retry(f"{get_settings().pubmed_base_url}/esearch.fcgi", params)
    data = json.loads(raw)
    return data.get("esearchresult", {}).get("idlist", [])


def _text(el: ET.Element | None) -> str:
    """Flatten an element's full text (AbstractText may contain inline markup like <i>)."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_efetch_xml(raw: bytes) -> list[PubMedArticle]:
    """Parse efetch PubmedArticleSet XML into PubMedArticle records."""
    root = ET.fromstring(raw)
    articles: list[PubMedArticle] = []
    for node in root.iter("PubmedArticle"):
        medline = node.find("MedlineCitation")
        if medline is None:
            continue
        pmid = _text(medline.find("PMID"))
        art = medline.find("Article")
        if art is None or not pmid:
            continue

        title = _text(art.find("ArticleTitle"))
        journal = _text(art.find("Journal/Title"))
        # Year may live in PubDate/Year or as the prefix of PubDate/MedlineDate ("2020 Jan-Feb").
        year = _text(art.find("Journal/JournalIssue/PubDate/Year"))
        if not year:
            medline_date = _text(art.find("Journal/JournalIssue/PubDate/MedlineDate"))
            year = medline_date[:4] if medline_date[:4].isdigit() else ""

        # AbstractText can appear multiple times with Label attributes (BACKGROUND, METHODS, …).
        parts = []
        for abst in art.findall("Abstract/AbstractText"):
            label = abst.get("Label")
            body = _text(abst)
            parts.append(f"{label}: {body}" if label else body)
        abstract = " ".join(p for p in parts if p)

        authors = []
        for author in art.findall("AuthorList/Author"):
            last = _text(author.find("LastName"))
            initials = _text(author.find("Initials"))
            if last:
                authors.append(f"{last} {initials}".strip())

        articles.append(PubMedArticle(
            pmid=pmid, title=title, journal=journal, year=year,
            authors=authors, abstract=abstract,
        ))
    return articles


def search_articles(query: str, max_results: int = 5) -> list[PubMedArticle]:
    """
    Search PubMed and return articles with metadata + abstracts.
    Returns an empty list when nothing matches.
    """
    max_results = max(1, min(max_results, 10))  # keep tool responses bounded
    pmids = _esearch(query, max_results)
    if not pmids:
        return []
    params = {
        **_base_params(),
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    raw = _get_with_retry(f"{get_settings().pubmed_base_url}/efetch.fcgi", params)
    return parse_efetch_xml(raw)
