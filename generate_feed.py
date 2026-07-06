from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

import requests
import yaml
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo

DEFAULT_CONFIG = "config.yaml"
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("atom", ATOM_NS)

DATE_PATTERNS = (
    re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"),
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
        r"January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
        r"January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4}\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    published: datetime
    description: str
    labels: tuple[str, ...] = ()


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a mapping.")

    return config


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.casefold(), parsed.netloc.casefold(), path, "", "", ""))


def is_blog_post_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path or path in {"/", "/blog", "/blog/research"}:
        return False
    if parsed.netloc and parsed.netloc != "sakana.ai":
        return False
    rejected_prefixes = ("/assets/", "/js/", "/css/", "/feed.xml", "/careers")
    return not any(path.startswith(prefix) for prefix in rejected_prefixes)



def parse_labels(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip().casefold() for part in value.split(",") if part.strip())


def article_language(container: Tag) -> str:
    return str(container.get("data-lang", "")).strip().casefold()


def is_english_title(title: str) -> bool:
    letters = re.findall(r"[A-Za-z]", title)
    if len(letters) < 4:
        return False

    non_ascii = sum(1 for character in title if ord(character) > 127)
    return len(letters) >= max(4, non_ascii)


def contains_keyword(text: str, keywords: Iterable[str]) -> bool:
    searchable = text.casefold()
    return any(str(keyword).casefold() in searchable for keyword in keywords)


def parse_date(text: str, timezone: ZoneInfo) -> datetime | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue

        try:
            parsed = date_parser.parse(match.group(0), fuzzy=False)
        except (OverflowError, ValueError):
            continue

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)

        return parsed.astimezone(UTC)

    return None


def extract_title(anchor: Tag) -> str:
    for selector in ("h1", "h2", "h3", "h4"):
        heading = anchor.find(selector)
        if isinstance(heading, Tag):
            title = normalize_space(heading.get_text(" ", strip=True))
            if title:
                return title

    text = normalize_space(anchor.get_text(" ", strip=True))
    if "Read more" in text:
        text = text.split("Read more", 1)[0]
    return text


def find_article_container(anchor: Tag, timezone: ZoneInfo) -> tuple[Tag, datetime | None]:
    current: Tag | None = anchor
    best: tuple[Tag, datetime | None] = (anchor, None)

    for _ in range(8):
        parent = current.parent if current is not None else None
        if not isinstance(parent, Tag):
            break

        current = parent
        text = normalize_space(current.get_text(" ", strip=True))
        if len(text) > 12_000:
            break

        published = parse_date(text, timezone)
        if published is not None:
            return current, published

        if 40 <= len(text) <= 6_000:
            best = (current, None)

    return best


def build_description(container: Tag, title: str) -> str:
    text = normalize_space(container.get_text(" ", strip=True))
    text = normalize_space(text.replace(title, " ", 1))
    return text[:2_000]


def passes_filters(article: Article, filters: dict) -> bool:
    title = article.title
    searchable = f"{article.title} {article.description} {article.url}"
    labels = set(article.labels)
    exclude_labels = {str(label).casefold() for label in filters.get("exclude_labels", [])}

    if labels.intersection(exclude_labels):
        return False

    if labels and "research" not in labels:
        return False

    if filters.get("require_english_title", True) and not is_english_title(title):
        return False

    if contains_keyword(searchable, filters.get("exclude_keywords", [])):
        return False

    return "research" in labels or contains_keyword(searchable, filters.get("include_keywords", []))


def extract_articles(page_html: str, config: dict, fetched_at: datetime | None = None) -> list[Article]:
    feed_config = config.get("feed", {})
    filters = config.get("filters", {})
    timezone = ZoneInfo(str(feed_config.get("timezone", "UTC")))
    source_url = str(feed_config["source_url"])
    fallback_date = fetched_at or datetime.now(UTC)
    soup = BeautifulSoup(page_html, "html.parser")

    articles_by_url: dict[str, Article] = {}
    containers = [node for node in soup.find_all("article") if isinstance(node, Tag)]
    if not containers:
        containers = [node for node in soup.find_all("a", href=True) if isinstance(node, Tag)]

    for container in containers:
        anchor = container.find("a", href=True) if container.name != "a" else container
        if not isinstance(anchor, Tag):
            continue

        if article_language(container) not in {"", "en"}:
            continue

        url = urljoin(source_url, str(anchor.get("href")))
        if not is_blog_post_url(url):
            continue

        title = extract_title(anchor)
        if len(title) < 8 or len(title) > 260:
            continue

        card, published = (container, parse_date(container.get_text(" ", strip=True), timezone))
        if container.name == "a":
            card, published = find_article_container(anchor, timezone)

        article = Article(
            title=title,
            url=normalize_url(url),
            published=published or fallback_date,
            description=build_description(card, title),
            labels=parse_labels(str(container.get("data-labels", ""))),
        )

        if not passes_filters(article, filters):
            continue

        normalized = normalize_url(article.url)
        previous = articles_by_url.get(normalized)
        if previous is None or (not is_english_title(previous.title) and is_english_title(article.title)):
            articles_by_url[normalized] = article

    return sorted(articles_by_url.values(), key=lambda item: (item.published, item.title.casefold()), reverse=True)


def fetch_source(source_url: str, timeout_seconds: int = 30) -> str:
    response = requests.get(
        source_url,
        timeout=timeout_seconds,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "sakana-ai-research-rss/0.1 (+https://cathyliucx.github.io/rss/sakana-research.xml)",
        },
    )
    response.raise_for_status()
    return response.text


def add_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = text
    return element


def build_rss(articles: list[Article], config: dict, generated_at: datetime | None = None) -> ET.ElementTree:
    feed_config = config.get("feed", {})
    generated = generated_at or datetime.now(UTC)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    add_text(channel, "title", str(feed_config.get("title", "Sakana AI Research")))
    add_text(channel, "link", str(feed_config.get("homepage", feed_config.get("source_url", "https://sakana.ai/"))))
    add_text(channel, "description", str(feed_config.get("description", "Filtered Sakana AI research posts.")))
    add_text(channel, "language", "en")
    add_text(channel, "lastBuildDate", format_datetime(generated))
    public_url = feed_config.get("public_url")
    if public_url:
        ET.SubElement(channel, f"{{{ATOM_NS}}}link", {"href": str(public_url), "rel": "self", "type": "application/rss+xml"})

    max_items = int(feed_config.get("max_items", 100))
    for article in articles[:max_items]:
        item = ET.SubElement(channel, "item")
        add_text(item, "title", article.title)
        add_text(item, "link", article.url)
        add_text(item, "guid", article.url).set("isPermaLink", "true")
        add_text(item, "pubDate", format_datetime(article.published))
        add_text(item, "description", article.description or article.title)

    ET.indent(rss, space="  ")
    return ET.ElementTree(rss)


def write_feed(tree: ET.ElementTree, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Sakana AI research RSS feed.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--output", default=None)
    parser.add_argument("--source-html", default=None, help="Parse a saved HTML file instead of fetching the live page.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    feed_config = config.get("feed", {})
    source_url = str(feed_config["source_url"])

    if args.source_html:
        page_html = Path(args.source_html).read_text(encoding="utf-8")
    else:
        page_html = fetch_source(source_url)

    generated_at = datetime.now(UTC)
    articles = extract_articles(page_html, config, fetched_at=generated_at)
    output = args.output or feed_config.get("output", "docs/sakana-research.xml")
    write_feed(build_rss(articles, config, generated_at=generated_at), output)

    print(f"Fetched: {source_url}")
    print(f"Kept research posts: {len(articles)}")
    print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
