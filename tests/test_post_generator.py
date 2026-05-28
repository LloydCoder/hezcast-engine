"""
HezCast Engine — Post Content Generator Tests
Tinlance Limited | Apache 2.0

TDD: Tests written BEFORE implementation.

Generates social media post bundles from script:
  title + caption + hashtags + cta_link
One LLM call, injected after qa_check_task in Celery chain.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def post_generator():
    from core.post_generator import PostGenerator
    return PostGenerator()

@pytest.fixture
def sample_script():
    return (
        "Nobody told me you could forget your mum's birthday TWICE. "
        "I had 2 hours, zero ideas, and a guilt trip loading. "
        "GiftMode gave me 3 perfect gift ideas in 9 seconds. Done. "
        "500,000 people use it free. Download GiftMode before you forget again."
    )

@pytest.fixture
def mock_post_response():
    return {
        "title":     "I forgot her birthday TWICE (this app saved me)",
        "caption":   (
            "Nobody warned me about the gift panic 😭 "
            "2 hours, zero ideas, full guilt mode. "
            "Then I found GiftMode and had 3 perfect options in 9 seconds. "
            "500K people already use it — and it's completely free. "
            "Download the link in bio before YOU forget 👇"
        ),
        "hashtags":  [
            "#GiftMode", "#GiftIdeas", "#BirthdayGift",
            "#LastMinuteGift", "#GiftApp", "#GiftHelper",
            "#BirthdayPanic", "#TikTokMadeMeDownloadIt",
            "#FreeApp", "#GiftSuggestions"
        ],
        "cta_link":  "https://giftmode.app",
        "platform_variants": {
            "tiktok":    "I forgot her birthday TWICE 😭 This app saved me in 9 seconds #GiftMode #GiftApp #BirthdayPanic",
            "instagram": "Nobody warned me about gift panic 😭 2 hours, zero ideas...\n\nThen GiftMode found 3 perfect gifts in 9 seconds.\n500K people already use it — FREE. Link in bio 👇",
            "linkedin":  "A lesson in last-minute problem solving: when I needed a gift in 2 hours, AI found the answer in 9 seconds. GiftMode is redefining how we discover meaningful gifts."
        }
    }


# ─────────────────────────────────────────────
# OUTPUT STRUCTURE TESTS
# ─────────────────────────────────────────────

class TestPostStructure:

    def test_generate_returns_dict(self, post_generator, sample_script):
        """generate() must return a dict"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(
                script=sample_script,
                brand="GiftMode"
            )
        assert isinstance(result, dict)

    def test_post_has_title(self, post_generator, sample_script):
        """Post must have a title field"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "title" in result
        assert len(result["title"]) > 0

    def test_post_has_caption(self, post_generator, sample_script):
        """Post must have a caption field"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "caption" in result
        assert len(result["caption"]) > 0

    def test_post_has_hashtags_list(self, post_generator, sample_script):
        """Post must have a hashtags list"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "hashtags" in result
        assert isinstance(result["hashtags"], list)

    def test_post_has_cta_link(self, post_generator, sample_script):
        """Post must have a cta_link field"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "cta_link" in result

    def test_post_has_platform_variants(self, post_generator, sample_script):
        """Post must have platform_variants dict"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "platform_variants" in result
        assert isinstance(result["platform_variants"], dict)

    def test_platform_variants_has_tiktok(self, post_generator, sample_script):
        """platform_variants must include tiktok"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "tiktok" in result["platform_variants"]

    def test_platform_variants_has_instagram(self, post_generator, sample_script):
        """platform_variants must include instagram"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "instagram" in result["platform_variants"]

    def test_platform_variants_has_linkedin(self, post_generator, sample_script):
        """platform_variants must include linkedin"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "linkedin" in result["platform_variants"]


# ─────────────────────────────────────────────
# HASHTAG QUALITY TESTS
# ─────────────────────────────────────────────

class TestHashtagQuality:

    def test_hashtags_start_with_hash(self, post_generator, sample_script):
        """Every hashtag must start with #"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        for tag in result["hashtags"]:
            assert tag.startswith("#"), f"Hashtag missing #: {tag}"

    def test_hashtags_count_between_5_and_15(self, post_generator, sample_script):
        """Must generate 5–15 hashtags"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        count = len(result["hashtags"])
        assert 5 <= count <= 15, f"Hashtag count {count} out of range"

    def test_no_duplicate_hashtags(self, post_generator, sample_script):
        """All hashtags must be unique"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        tags = [t.lower() for t in result["hashtags"]]
        assert len(tags) == len(set(tags)), "Duplicate hashtags found"

    def test_hashtags_have_no_spaces(self, post_generator, sample_script):
        """Hashtags must not contain spaces"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        for tag in result["hashtags"]:
            assert " " not in tag, f"Hashtag has space: {tag}"


# ─────────────────────────────────────────────
# TITLE QUALITY TESTS
# ─────────────────────────────────────────────

class TestTitleQuality:

    def test_title_under_100_chars(self, post_generator, sample_script):
        """Title must be under 100 characters"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert len(result["title"]) <= 100

    def test_title_over_10_chars(self, post_generator, sample_script):
        """Title must be at least 10 characters"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert len(result["title"]) >= 10

    def test_title_not_same_as_caption(self, post_generator, sample_script):
        """Title and caption must be distinct"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict()
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert result["title"] != result["caption"]


# ─────────────────────────────────────────────
# BRAND CTA TESTS
# ─────────────────────────────────────────────

class TestBrandCTA:

    def test_giftmode_cta_link_is_giftmode_app(self, post_generator, sample_script):
        """GiftMode CTA link must reference giftmode.app"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict(cta="https://giftmode.app")
            result = post_generator.generate(script=sample_script, brand="GiftMode")
        assert "giftmode" in result["cta_link"].lower()

    def test_tinlance_cta_link_is_tinlance(self, post_generator):
        """Tinlance CTA must reference tinlance.com"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict(cta="https://tinlance.com")
            result = post_generator.generate(
                script="Your business was breached. Tinlance can help.",
                brand="Tinlance"
            )
        assert "tinlance" in result["cta_link"].lower()

    def test_webtemify_cta_link_is_webtemify(self, post_generator):
        """WebTemify CTA must reference webtemify.com"""
        with patch.object(post_generator, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_post_dict(cta="https://webtemify.com")
            result = post_generator.generate(
                script="Build a landing page in 10 minutes with WebTemify.",
                brand="WebTemify"
            )
        assert "webtemify" in result["cta_link"].lower()

    def test_unknown_brand_raises_value_error(self, post_generator, sample_script):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            post_generator.generate(script=sample_script, brand="FakeBrand")

    def test_empty_script_raises_value_error(self, post_generator):
        """Empty script must raise ValueError"""
        with pytest.raises(ValueError, match="script"):
            post_generator.generate(script="", brand="GiftMode")


# ─────────────────────────────────────────────
# PROMPT BUILDER TESTS
# ─────────────────────────────────────────────

class TestPromptBuilder:

    def test_prompt_includes_script(self, post_generator, sample_script):
        """Prompt must include the script text"""
        prompt = post_generator._build_prompt(sample_script, "GiftMode")
        assert "birthday" in prompt.lower() or "giftmode" in prompt.lower()

    def test_prompt_includes_brand(self, post_generator, sample_script):
        """Prompt must reference the brand"""
        prompt = post_generator._build_prompt(sample_script, "GiftMode")
        assert "GiftMode" in prompt

    def test_prompt_requests_all_platforms(self, post_generator, sample_script):
        """Prompt must request TikTok, Instagram, LinkedIn variants"""
        prompt = post_generator._build_prompt(sample_script, "GiftMode")
        assert "tiktok" in prompt.lower()
        assert "instagram" in prompt.lower()
        assert "linkedin" in prompt.lower()

    def test_prompt_requests_json_output(self, post_generator, sample_script):
        """Prompt must instruct JSON-only output"""
        prompt = post_generator._build_prompt(sample_script, "GiftMode")
        assert "json" in prompt.lower()

    def test_different_brands_produce_different_prompts(self, post_generator, sample_script):
        """Each brand must produce a distinct prompt"""
        p1 = post_generator._build_prompt(sample_script, "GiftMode")
        p2 = post_generator._build_prompt(sample_script, "Tinlance")
        assert p1 != p2


# ─────────────────────────────────────────────
# SAVE BUNDLE TESTS
# ─────────────────────────────────────────────

class TestSaveBundle:

    def test_save_bundle_creates_json_file(self, post_generator, tmp_path):
        """save_bundle() must write a JSON file"""
        bundle = _mock_post_dict()
        out = post_generator.save_bundle(bundle, str(tmp_path / "post_bundle.json"))
        assert Path(out).exists()

    def test_save_bundle_returns_path(self, post_generator, tmp_path):
        """save_bundle() must return the output path"""
        bundle = _mock_post_dict()
        out_path = str(tmp_path / "post_bundle.json")
        result = post_generator.save_bundle(bundle, out_path)
        assert result == out_path

    def test_save_bundle_is_valid_json(self, post_generator, tmp_path):
        """Saved file must be valid JSON"""
        bundle = _mock_post_dict()
        out_path = str(tmp_path / "post_bundle.json")
        post_generator.save_bundle(bundle, out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert "title" in data
        assert "caption" in data
        assert "hashtags" in data

    def test_save_bundle_creates_parent_dirs(self, post_generator, tmp_path):
        """save_bundle() must create parent directories"""
        bundle = _mock_post_dict()
        deep_path = str(tmp_path / "deep" / "nested" / "bundle.json")
        post_generator.save_bundle(bundle, deep_path)
        assert Path(deep_path).exists()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _mock_post_dict(cta: str = "https://giftmode.app") -> dict:
    return {
        "title":    "I forgot her birthday TWICE (this app saved me)",
        "caption":  "Nobody warned me about the gift panic 😭 GiftMode fixed it in 9 seconds.",
        "hashtags": [
            "#GiftMode", "#GiftIdeas", "#BirthdayGift",
            "#LastMinuteGift", "#GiftApp", "#GiftHelper",
            "#BirthdayPanic", "#TikTokMadeMeDownloadIt",
            "#FreeApp", "#GiftSuggestions"
        ],
        "cta_link": cta,
        "platform_variants": {
            "tiktok":    "I forgot her birthday TWICE 😭 #GiftMode #GiftApp",
            "instagram": "Nobody warned me about gift panic 😭\n\nGiftMode found 3 perfect gifts in 9 seconds. Link in bio 👇",
            "linkedin":  "A lesson in last-minute problem solving: AI found the perfect gift in 9 seconds."
        }
    }
