"""Verify generated bilingual pages, counterpart navigation and local links."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from build_site import BASE, GUIDES, OUT, doc_url, localized_source


class Page(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.lang = ""
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.language_link = ""
        self.feed(path.read_text("utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "html":
            self.lang = values.get("lang") or ""
        if values.get("id"):
            self.ids.add(str(values["id"]))
        for name in ("href", "src"):
            if values.get(name):
                self.links.append(str(values[name]))
        if tag == "a" and values.get("class") == "language":
            self.language_link = values.get("href") or ""


def main() -> None:
    pages = {p.relative_to(OUT).as_posix(): Page(p) for p in OUT.rglob("*.html")}
    if len(pages) != len(GUIDES) + 2:
        raise ValueError("Generated pages do not cover every guide and both homepages")
    for source in GUIDES:
        chinese = source.endswith(".zh-CN.md")
        url = doc_url(source)
        page = pages[url.removeprefix(BASE)]
        if page.lang != ("zh-CN" if chinese else "en"):
            raise ValueError(f"Incorrect page language: {source}")
        if page.language_link != doc_url(localized_source(source, not chinese)):
            raise ValueError(f"Language switch lost the current guide: {source}")
    for filename, page in pages.items():
        current = "https://lkdenchin.github.io" + BASE + filename
        for link in page.links:
            target = urlsplit(urljoin(current, link))
            if target.netloc != "lkdenchin.github.io" or not target.path.startswith(BASE):
                continue
            path = unquote(target.path.removeprefix(BASE))
            if not path or path.endswith("/"):
                path += "index.html"
            if not (OUT / path).is_file():
                raise ValueError(f"Broken local link in {filename}: {link}")
            if target.fragment and path in pages:
                if unquote(target.fragment) not in pages[path].ids:
                    raise ValueError(f"Missing anchor in {filename}: {link}")
    index = json.loads((OUT / "assets/search-index.json").read_text("utf-8"))
    for lang in ("en", "zh-CN"):
        expected = {doc_url(s) for s in GUIDES if s.endswith(".zh-CN.md") == (lang == "zh-CN")}
        actual = {row["url"] for row in index if row["lang"] == lang}
        if actual != expected:
            raise ValueError(f"Incomplete search index for {lang}")
    print(f"Site verified: {len(pages)} pages, paired language links and complete search indexes")


if __name__ == "__main__":
    main()
