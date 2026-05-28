"""
HezCast Engine — URL Preprocessor Tests
TDD Phase 6 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

Converts a URL or blog post into a script-ready topic summary.
Grok's quick win — pass URL to /generate, HezCast reads the content
and builds the video script automatically.
"""

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def preprocessor():
    from core.url_preprocessor import URLPreprocessor
    return URLPreprocessor()

@pytest.fixture
def mock_html_content():
    return """
    <html>
    <head><title>5 Reasons Your Website Got Hacked</title></head>
    <body>
        <h1>5 Reasons Your Website Got Hacked</h1>
        <p>Every day, thousands of websites are compromised by attackers.
        Most business owners have no idea until it's too late.
        Here are the five most common reasons your website is vulnerable:
        outdated plugins, weak passwords, no SSL, poor hosting,
        and ignoring security updates.</p>
        <p>Tinlance can help you identify and fix these vulnerabilities
        before attackers do. Our cybersecurity audit takes 24 hours
        and covers all critical attack vectors.</p>
    </body>
    </html>
    """

@pytest.fixture
def mock_extracted():
    return {
        "title":    "5 Reasons Your Website Got Hacked",
        "summary":  "Most business owners don't know their website is vulnerable until it's too late. Five common attack vectors: outdated plugins, weak passwords, no SSL, poor hosting, ignoring security updates.",
        "key_points": [
            "Thousands of websites compromised daily",
            "Most owners unaware until attacked",
            "5 common vulnerabilities identified",
            "Tinlance audit covers all attack vectors"
        ],
        "url":      "https://tinlance.com/blog/website-hacked",
        "word_count": 85,
    }


# ─────────────────────────────────────────────
# URL VALIDATION TESTS
# ─────────────────────────────────────────────

class TestURLValidation:

    def test_valid_https_url_passes(self, preprocessor):
        """Valid HTTPS URL must not raise"""
        try:
            preprocessor._validate_url("https://tinlance.com/blog/post")
        except Exception as e:
            pytest.fail(f"Valid URL raised: {e}")

    def test_valid_http_url_passes(self, preprocessor):
        """Valid HTTP URL must not raise"""
        try:
            preprocessor._validate_url("http://example.com/article")
        except Exception as e:
            pytest.fail(f"Valid HTTP URL raised: {e}")

    def test_empty_url_raises(self, preprocessor):
        """Empty URL must raise ValueError"""
        with pytest.raises(ValueError, match="url"):
            preprocessor._validate_url("")

    def test_no_protocol_raises(self, preprocessor):
        """URL without protocol must raise ValueError"""
        with pytest.raises(ValueError, match="url"):
            preprocessor._validate_url("tinlance.com/blog")

    def test_invalid_url_raises(self, preprocessor):
        """Random string must raise ValueError"""
        with pytest.raises(ValueError, match="url"):
            preprocessor._validate_url("not a url at all")


# ─────────────────────────────────────────────
# CONTENT EXTRACTION TESTS
# ─────────────────────────────────────────────

class TestContentExtraction:

    def test_extract_returns_dict(self, preprocessor, mock_html_content):
        """extract_content must return a dict"""
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.extract_content("https://tinlance.com/blog/test")
        assert isinstance(result, dict)

    def test_extract_has_title(self, preprocessor, mock_html_content):
        """Extracted content must have title"""
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.extract_content("https://tinlance.com/blog/test")
        assert "title" in result
        assert len(result["title"]) > 0

    def test_extract_has_summary(self, preprocessor, mock_html_content):
        """Extracted content must have summary"""
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.extract_content("https://tinlance.com/blog/test")
        assert "summary" in result
        assert len(result["summary"]) > 0

    def test_extract_has_key_points(self, preprocessor, mock_html_content):
        """Extracted content must have key_points list"""
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.extract_content("https://tinlance.com/blog/test")
        assert "key_points" in result
        assert isinstance(result["key_points"], list)

    def test_extract_has_url(self, preprocessor, mock_html_content):
        """Extracted content must include the source URL"""
        url = "https://tinlance.com/blog/test"
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.extract_content(url)
        assert result.get("url") == url

    def test_extract_strips_html_tags(self, preprocessor, mock_html_content):
        """Summary must not contain HTML tags"""
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.extract_content("https://tinlance.com/blog/test")
        summary = result.get("summary", "")
        assert "<" not in summary
        assert ">" not in summary

    def test_extract_fetch_failure_raises(self, preprocessor):
        """Network fetch failure must raise URLProcessingError"""
        from core.url_preprocessor import URLProcessingError
        with patch.object(preprocessor, '_fetch_url', side_effect=Exception("Network error")):
            with pytest.raises(URLProcessingError):
                preprocessor.extract_content("https://tinlance.com/blog/test")


# ─────────────────────────────────────────────
# TOPIC GENERATION TESTS
# ─────────────────────────────────────────────

class TestTopicGeneration:

    def test_to_topic_returns_string(self, preprocessor, mock_extracted):
        """to_topic must return a string"""
        result = preprocessor.to_topic(mock_extracted)
        assert isinstance(result, str)

    def test_to_topic_is_not_empty(self, preprocessor, mock_extracted):
        """to_topic must not return empty string"""
        result = preprocessor.to_topic(mock_extracted)
        assert len(result.strip()) > 0

    def test_to_topic_under_200_chars(self, preprocessor, mock_extracted):
        """Topic must be under 200 chars — concise for script engine"""
        result = preprocessor.to_topic(mock_extracted)
        assert len(result) <= 200

    def test_to_topic_includes_key_context(self, preprocessor, mock_extracted):
        """Topic must reference the main subject"""
        result = preprocessor.to_topic(mock_extracted)
        assert any(word in result.lower() for word in [
            "hack", "website", "security", "vulnerab", "attack"
        ])

    def test_to_topic_empty_extraction_raises(self, preprocessor):
        """Empty extraction must raise ValueError"""
        with pytest.raises(ValueError, match="extraction"):
            preprocessor.to_topic({})


# ─────────────────────────────────────────────
# END-TO-END PROCESS TESTS
# ─────────────────────────────────────────────

class TestEndToEndProcess:

    def test_process_url_returns_topic_string(self, preprocessor, mock_html_content):
        """process_url must return a topic string ready for script engine"""
        with patch.object(preprocessor, '_fetch_url') as mock_fetch:
            mock_fetch.return_value = mock_html_content
            result = preprocessor.process_url("https://tinlance.com/blog/test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_process_url_empty_raises(self, preprocessor):
        """Empty URL must raise ValueError"""
        with pytest.raises(ValueError, match="url"):
            preprocessor.process_url("")

    def test_process_url_invalid_raises(self, preprocessor):
        """Invalid URL must raise ValueError"""
        with pytest.raises(ValueError, match="url"):
            preprocessor.process_url("not-a-url")
