"""
HezCast Engine — URL Preprocessor
Tinlance Limited | Apache 2.0

Converts any URL (blog post, article, landing page) into a
script-ready topic string for the HezCast pipeline.

Flow:
  URL → fetch HTML → extract title + body → clean text →
  summarize key points → produce concise topic string

The topic string feeds directly into ScriptEngine.generate()
as if the user typed it manually.

Usage in API:
  POST /generate
  {"url": "https://tinlance.com/blog/why-your-site-got-hacked", "brand": "Tinlance"}

  Same as:
  POST /generate
  {"topic": "most businesses don't know their site is vulnerable until it's too late", "brand": "Tinlance"}
"""

import logging
import re
import requests
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Max characters to extract from page body
MAX_BODY_CHARS = 3000

# Request timeout
FETCH_TIMEOUT = 15


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML parser — extracts text, strips tags"""

    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form"}

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._current_skip = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            self._current_skip = tag

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = text
        elif self._skip_depth == 0:
            self.text_parts.append(text)

    def get_text(self) -> str:
        return " ".join(self.text_parts)


class URLPreprocessor:
    """
    Fetches and processes a URL into a HezCast-ready topic string.

    Usage:
        preprocessor = URLPreprocessor()
        topic = preprocessor.process_url("https://tinlance.com/blog/post")
        # topic → "most businesses don't know their site is vulnerable..."

        # Then pass to script engine:
        script = script_engine.generate(topic=topic, brand="Tinlance")
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; HezCast/2.0; "
                "+https://cast.tinlance.com)"
            )
        })

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def process_url(self, url: str) -> str:
        """
        Full pipeline: URL → fetch → extract → topic string.

        Args:
            url: Any valid HTTP/HTTPS URL

        Returns:
            Topic string (max 200 chars) ready for ScriptEngine

        Raises:
            ValueError:          If URL is empty or invalid
            URLProcessingError:  If fetch or extraction fails
        """
        self._validate_url(url)
        extracted = self.extract_content(url)
        return self.to_topic(extracted)

    def extract_content(self, url: str) -> dict:
        """
        Fetch URL and extract structured content.

        Args:
            url: Valid HTTP/HTTPS URL

        Returns:
            dict with: title, summary, key_points, url, word_count

        Raises:
            URLProcessingError: If fetch or parsing fails
        """
        self._validate_url(url)

        try:
            html = self._fetch_url(url)
        except Exception as e:
            raise URLProcessingError(f"Failed to fetch {url}: {e}")

        try:
            title, body = self._parse_html(html)
            summary    = self._summarize(body)
            key_points = self._extract_key_points(body)

            return {
                "title":      title,
                "summary":    summary,
                "key_points": key_points,
                "url":        url,
                "word_count": len(body.split()),
            }
        except Exception as e:
            raise URLProcessingError(f"Failed to extract content from {url}: {e}")

    def to_topic(self, extraction: dict) -> str:
        """
        Convert extracted content dict to a concise topic string.

        Args:
            extraction: Dict from extract_content()

        Returns:
            Topic string, max 200 chars

        Raises:
            ValueError: If extraction is empty
        """
        if not extraction:
            raise ValueError("extraction must be a non-empty dict")

        title   = extraction.get("title", "")
        summary = extraction.get("summary", "")
        points  = extraction.get("key_points", [])

        # Build topic from most valuable signals
        parts = []

        if title:
            # Clean title — remove site name suffixes like "| Tinlance"
            clean_title = re.split(r'\s*[|\-–—]\s*', title)[0].strip()
            parts.append(clean_title)

        if summary:
            # First sentence of summary
            first_sentence = summary.split('.')[0].strip()
            if first_sentence and first_sentence.lower() != clean_title.lower():
                parts.append(first_sentence)

        if points:
            # First key point
            parts.append(points[0])

        topic = ". ".join(p for p in parts if p)

        # Enforce 200 char limit
        if len(topic) > 200:
            topic = topic[:197] + "..."

        return topic.strip()

    # ─────────────────────────────────────────
    # FETCHING (mockable in tests)
    # ─────────────────────────────────────────

    def _fetch_url(self, url: str) -> str:
        """
        Fetch URL content. In tests: mocked via patch.

        Raises:
            Exception: On network error, timeout, or non-200 status
        """
        response = self.session.get(url, timeout=FETCH_TIMEOUT)
        response.raise_for_status()
        return response.text

    # ─────────────────────────────────────────
    # PARSING
    # ─────────────────────────────────────────

    def _parse_html(self, html: str) -> tuple[str, str]:
        """
        Parse HTML and return (title, body_text).
        Strips all HTML tags, scripts, nav, footer.
        """
        parser = _HTMLTextExtractor()
        parser.feed(html)

        title = parser.title or ""
        body  = parser.get_text()

        # Clean body text
        body = re.sub(r'\s+', ' ', body).strip()
        body = body[:MAX_BODY_CHARS]

        return title, body

    def _summarize(self, body: str) -> str:
        """Extract a clean 1-3 sentence summary from body text"""
        if not body:
            return ""

        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', body)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        # Take first 3 meaningful sentences
        summary_sentences = sentences[:3]
        return " ".join(summary_sentences)

    def _extract_key_points(self, body: str) -> list[str]:
        """
        Extract 3-5 key points from body text.
        Looks for numbered lists, bullet points, or leading sentences.
        """
        points = []

        # Look for numbered lists: "1. something" or "1) something"
        numbered = re.findall(r'(?:^|\n)\s*\d+[.)]\s*(.+?)(?:\n|$)', body)
        if numbered:
            points.extend([p.strip() for p in numbered[:5] if len(p.strip()) > 10])

        # If no numbered list, extract first 4 sentences as points
        if len(points) < 3:
            sentences = re.split(r'(?<=[.!?])\s+', body)
            for s in sentences:
                s = s.strip()
                if len(s) > 15 and s not in points:
                    points.append(s)
                if len(points) >= 5:
                    break

        return points[:5]

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    def _validate_url(self, url: str) -> None:
        """
        Validate URL format.

        Raises:
            ValueError: If URL is empty, missing protocol, or malformed
        """
        if not url or not url.strip():
            raise ValueError("url must be a non-empty string")

        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(
                    f"url must start with http:// or https:// (got: '{url}')"
                )
            if not parsed.netloc:
                raise ValueError(f"url has no domain: '{url}'")
        except ValueError:
            raise
        except Exception:
            raise ValueError(f"url is malformed: '{url}'")


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class URLProcessingError(Exception):
    """Raised when URL fetching or content extraction fails"""
    pass
