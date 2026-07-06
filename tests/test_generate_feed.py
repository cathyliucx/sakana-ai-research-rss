from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from generate_feed import build_rss, extract_articles, is_english_title


CONFIG = {
    "feed": {
        "title": "Sakana AI — Research",
        "description": "Filtered research feed",
        "homepage": "https://sakana.ai/blog/?label=research",
        "source_url": "https://sakana.ai/blog/?label=research",
        "public_url": "https://cathyliucx.github.io/rss/sakana-research.xml",
        "timezone": "UTC",
        "max_items": 100,
    },
    "filters": {
        "require_english_title": True,
        "include_keywords": ["paper", "benchmark", "algorithm", "agent", "model", "llm", "neural", "evolution", "research"],
        "exclude_keywords": ["hiring", "funding", "partnership", "collaboration", "製品"],
    },
}


def test_english_title_check_prefers_research_titles() -> None:
    assert is_english_title("Evolutionary Model Merge for Large Language Models")
    assert not is_english_title("研究チームからのお知らせ")


def test_extract_articles_keeps_research_and_excludes_marketing() -> None:
    html = """
    <main>
      <article>
        <a href="/blog/evolutionary-model-merge/">
          <h2>Evolutionary Model Merge for Large Language Models</h2>
          <p>February 12, 2026</p>
          <p>A research paper introducing an evolutionary algorithm for model merging.</p>
        </a>
      </article>
      <article>
        <a href="/blog/enterprise-product-launch/">
          <h2>Sakana AI Enterprise Product Launch</h2>
          <p>February 13, 2026</p>
          <p>Product launch for customers.</p>
        </a>
      </article>
      <article>
        <a href="/blog/funding-announcement/">
          <h2>Sakana AI Funding Announcement</h2>
          <p>February 14, 2026</p>
          <p>Funding news from investors.</p>
        </a>
      </article>
      <article>
        <a href="/blog/japanese-marketing/">
          <h2>進化的モデルマージの紹介</h2>
          <p>February 15, 2026</p>
          <p>研究 製品 マーケティング</p>
        </a>
      </article>
    </main>
    """

    articles = extract_articles(html, CONFIG, fetched_at=datetime(2026, 2, 20, tzinfo=UTC))

    assert [article.title for article in articles] == ["Evolutionary Model Merge for Large Language Models"]
    assert articles[0].published == datetime(2026, 2, 12, tzinfo=UTC)



def test_extract_articles_requires_research_label_when_labels_exist() -> None:
    html = """
    <article data-labels="inside-sakana" data-lang="en">
      <a href="/unofficial-guide/">
        <h2>An Unofficial Guide to Prepare for a Research Position Application</h2>
        <p>January 20, 2026</p>
      </a>
    </article>
    <article data-labels="research" data-lang="en">
      <a href="/repo/">
        <h2>RePo: Language Models with Context Re-Positioning</h2>
        <p>January 19, 2026</p>
      </a>
    </article>
    """

    articles = extract_articles(html, CONFIG, fetched_at=datetime(2026, 1, 21, tzinfo=UTC))

    assert [article.title for article in articles] == ["RePo: Language Models with Context Re-Positioning"]


def test_build_rss_contains_public_self_link_and_items() -> None:
    html = """
    <article>
      <a href="/blog/agent-benchmark/">
        <h2>New Agent Benchmark Paper</h2>
        <span>March 1, 2026</span>
        <p>A research benchmark for LLM agents.</p>
      </a>
    </article>
    """
    articles = extract_articles(html, CONFIG, fetched_at=datetime(2026, 3, 2, tzinfo=UTC))
    tree = build_rss(articles, CONFIG, generated_at=datetime(2026, 3, 2, tzinfo=UTC))
    root = tree.getroot()

    assert root.tag == "rss"
    titles = [element.text for element in root.findall("./channel/item/title")]
    assert titles == ["New Agent Benchmark Paper"]

    namespaces = {"atom": "http://www.w3.org/2005/Atom"}
    self_link = root.find("./channel/atom:link", namespaces)
    assert self_link is not None
    assert self_link.attrib["href"] == "https://cathyliucx.github.io/rss/sakana-research.xml"
