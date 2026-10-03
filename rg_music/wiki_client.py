"""Polite client for the MediaWiki Action API (en.wikipedia.org).

Follows the Wikimedia API etiquette:
  * a descriptive User-Agent with a way to contact the author;
  * sequential requests with a minimum delay between them;
  * ``maxlag`` so we back off when the servers are under load;
  * retries with exponential backoff that honour ``Retry-After``.

Raw responses are cached on disk, so re-running the parser never
re-downloads a page unless you pass ``refresh=True``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

API_URL = "https://en.wikipedia.org/w/api.php"
DEFAULT_CONTACT = "https://github.com/your-username/rg-music-catalog"


@dataclass
class WikiPage:
    requested_title: str
    title: str  # title after following redirects
    pageid: int
    revid: int
    html: str
    fetched_at: str

    @property
    def url(self) -> str:
        return "https://en.wikipedia.org/wiki/" + self.title.replace(" ", "_")


class WikiError(RuntimeError):
    pass


def _cache_key(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", title.strip())


class WikiClient:
    def __init__(
        self,
        cache_dir: Path | str = "data/raw",
        min_delay: float = 1.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        contact: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_delay = min_delay
        self.max_retries = max_retries
        self.timeout = timeout
        contact = contact or os.environ.get("WIKI_CONTACT", DEFAULT_CONTACT)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            f"rg-music-catalog/0.1 ({contact}) python-requests/{requests.__version__}"
        )
        self._last_request = 0.0

    # ------------------------------------------------------------------ http
    def _throttle(self) -> None:
        wait = self.min_delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get(self, params: dict) -> dict:
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                delay = 2**attempt
                log.warning("network error (%s), retry %d in %ss", exc, attempt, delay)
                time.sleep(delay)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                delay = float(resp.headers.get("Retry-After", 2**attempt))
                log.warning("HTTP %s, retry %d in %ss", resp.status_code, attempt, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()

            data = resp.json()
            err = data.get("error")
            if err and err.get("code") == "maxlag":
                delay = float(resp.headers.get("Retry-After", 5))
                log.warning("server lagged, retry %d in %ss", attempt, delay)
                time.sleep(delay)
                continue
            if err:
                raise WikiError(f"{err.get('code')}: {err.get('info')}")
            return data
        raise WikiError(f"giving up after {self.max_retries} attempts: {params}")

    # ------------------------------------------------------------------ api
    def get_page(self, title: str, refresh: bool = False) -> WikiPage:
        """Return the rendered HTML of an article, following redirects."""
        key = _cache_key(title)
        html_path = self.cache_dir / f"{key}.html"
        meta_path = self.cache_dir / f"{key}.json"

        if not refresh and html_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            log.info("cache hit: %s", title)
            return WikiPage(html=html_path.read_text(encoding="utf-8"), **meta)

        log.info("fetching: %s", title)
        data = self._get(
            {
                "action": "parse",
                "page": title,
                "prop": "text|revid",
                "redirects": "1",
                "disableeditsection": "1",
                "disabletoc": "1",
            }
        )
        parsed = data["parse"]
        page = WikiPage(
            requested_title=title,
            title=parsed["title"],
            pageid=parsed["pageid"],
            revid=parsed["revid"],
            html=parsed["text"],
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        html_path.write_text(page.html, encoding="utf-8")
        meta = {k: v for k, v in page.__dict__.items() if k != "html"}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return page

    def resolve_titles(self, titles: list[str], batch: int = 50) -> dict[str, tuple[str, int | None]]:
        """Map every title to (canonical title after redirects, pageid or None if missing)."""
        out: dict[str, tuple[str, int | None]] = {}
        unique = list(dict.fromkeys(titles))
        for i in range(0, len(unique), batch):
            chunk = unique[i:i + batch]
            data = self._get({"action": "query", "titles": "|".join(chunk), "redirects": "1"})["query"]
            step = {m["from"]: m["to"] for m in data.get("normalized", [])}
            redirect = {m["from"]: m["to"] for m in data.get("redirects", [])}
            pages = {p["title"]: p for p in data.get("pages", [])}
            for title in chunk:
                final = step.get(title, title)
                final = redirect.get(final, final)
                page = pages.get(final, {})
                out[title] = (final, None if page.get("missing") else page.get("pageid"))
        return out
