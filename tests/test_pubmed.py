"""Tests for the PubMed efetch XML parser (no network)."""
from app.pubmed.client import parse_efetch_xml

_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle><MedlineCitation><PMID>12345</PMID>
  <Article>
   <ArticleTitle>Pembrolizumab in NSCLC</ArticleTitle>
   <Journal><Title>NEJM</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
   <Abstract>
     <AbstractText Label="BACKGROUND">Immune checkpoint blockade.</AbstractText>
     <AbstractText Label="RESULTS">Improved overall survival.</AbstractText>
   </Abstract>
   <AuthorList>
     <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
     <Author><LastName>Doe</LastName><Initials>A</Initials></Author>
   </AuthorList>
  </Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_parse_basic_article():
    articles = parse_efetch_xml(_XML)
    assert len(articles) == 1
    a = articles[0]
    assert a.pmid == "12345"
    assert a.title == "Pembrolizumab in NSCLC"
    assert a.journal == "NEJM"
    assert a.year == "2020"
    assert a.authors == ["Smith J", "Doe A"]
    assert "BACKGROUND: Immune checkpoint blockade." in a.abstract
    assert "RESULTS: Improved overall survival." in a.abstract
    assert a.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_medline_date_fallback():
    xml = b"""<?xml version="1.0"?>
    <PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>7</PMID>
      <Article><ArticleTitle>T</ArticleTitle>
        <Journal><Title>J</Title><JournalIssue><PubDate>
          <MedlineDate>2018 Jan-Feb</MedlineDate>
        </PubDate></JournalIssue></Journal>
      </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    a = parse_efetch_xml(xml)[0]
    assert a.year == "2018"


def test_empty_set():
    assert parse_efetch_xml(b"<PubmedArticleSet></PubmedArticleSet>") == []
