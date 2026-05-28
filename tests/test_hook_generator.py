"""
HezCast Engine — Hook A/B Generator Tests
TDD Phase 1 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)
"""

import pytest
from unittest.mock import patch, MagicMock
import json
from pathlib import Path


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def brand_config():
    config_path = Path(__file__).parent.parent / "config" / "brands.json"
    with open(config_path) as f:
        return json.load(f)

@pytest.fixture
def mock_hooks_giftmode():
    return [
        "Nobody told me you could forget your mum's birthday TWICE...",
        "I had 2 hours to find a gift. I was absolutely cooked.",
        "POV: You just remembered her birthday is TODAY.",
        "The gift panic is real. This app cured it in 9 seconds.",
        "She said 'it's fine.' It was not fine. I needed this app."
    ]

@pytest.fixture
def mock_hooks_tinlance():
    return [
        "Your website went down at 2am. Nobody told you for 6 hours.",
        "I watched a client lose $40,000 in one Saturday morning breach.",
        "Most founders think they're too small to be hacked. They're wrong.",
    ]


# ─────────────────────────────────────────────
# VARIANT COUNT TESTS
# ─────────────────────────────────────────────

class TestHookVariantCount:

    def test_giftmode_generates_5_variants(self, brand_config, mock_hooks_giftmode):
        """GiftMode is configured for 5 hook variants"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            variants = generator.generate(
                topic="forgot birthday gift",
                brand="GiftMode"
            )

        assert len(variants) == brand_config["GiftMode"]["hook_variants"]
        assert len(variants) == 5

    def test_tinlance_generates_3_variants(self, brand_config, mock_hooks_tinlance):
        """Tinlance is configured for 3 hook variants"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_tinlance):
            variants = generator.generate(
                topic="website hacked",
                brand="Tinlance"
            )

        assert len(variants) == brand_config["Tinlance"]["hook_variants"]
        assert len(variants) == 3

    def test_webtemify_generates_4_variants(self, brand_config):
        """WebTemify is configured for 4 hook variants"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        mock_hooks = [f"Hook variant {i}" for i in range(4)]
        with patch.object(generator, '_call_llm', return_value=mock_hooks):
            variants = generator.generate(
                topic="landing page fast",
                brand="WebTemify"
            )

        assert len(variants) == brand_config["WebTemify"]["hook_variants"]
        assert len(variants) == 4


# ─────────────────────────────────────────────
# VARIANT STRUCTURE TESTS
# ─────────────────────────────────────────────

class TestHookVariantStructure:

    def test_each_variant_has_required_fields(self, mock_hooks_giftmode):
        """Each variant must have index, hook_text, and full_script"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script') as mock_script:
                mock_script.return_value = "Full script content here."
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        for variant in variants:
            assert "variant_num" in variant
            assert "hook_text" in variant
            assert "full_script" in variant

    def test_variant_numbers_are_sequential(self, mock_hooks_giftmode):
        """Variant numbers must start at 1 and be sequential"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        for i, variant in enumerate(variants):
            assert variant["variant_num"] == i + 1

    def test_no_duplicate_hooks(self, mock_hooks_giftmode):
        """All hook variants must be unique"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        hooks = [v["hook_text"] for v in variants]
        assert len(hooks) == len(set(hooks)), "Duplicate hooks detected"

    def test_hook_text_is_not_empty(self, mock_hooks_giftmode):
        """No hook variant should have empty text"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        for variant in variants:
            assert len(variant["hook_text"].strip()) > 0

    def test_hook_text_is_under_20_words(self, mock_hooks_giftmode):
        """Hooks must be punchy — under 20 words for TikTok format"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        for variant in variants:
            word_count = len(variant["hook_text"].split())
            assert word_count <= 20, \
                f"Hook too long ({word_count} words): {variant['hook_text']}"


# ─────────────────────────────────────────────
# HOOK SELECTION TESTS
# ─────────────────────────────────────────────

class TestHookSelection:

    def test_select_variant_marks_selected_true(self, mock_hooks_giftmode):
        """Selecting a variant must set selected=True on that variant"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        selected = generator.select(variants, variant_num=2)
        assert selected["selected"] is True
        assert selected["variant_num"] == 2

    def test_select_variant_returns_correct_hook(self, mock_hooks_giftmode):
        """Selecting variant 3 must return that specific hook"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        selected = generator.select(variants, variant_num=3)
        assert selected["hook_text"] == mock_hooks_giftmode[2]

    def test_select_invalid_variant_raises_error(self, mock_hooks_giftmode):
        """Selecting out-of-range variant_num must raise ValueError"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        with pytest.raises(ValueError, match="variant_num"):
            generator.select(variants, variant_num=99)

    def test_select_zero_raises_error(self, mock_hooks_giftmode):
        """variant_num=0 must raise ValueError (1-indexed)"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        with pytest.raises(ValueError):
            generator.select(variants, variant_num=0)


# ─────────────────────────────────────────────
# HOOK QUALITY TESTS
# ─────────────────────────────────────────────

class TestHookQuality:

    def test_hooks_contain_topic_reference(self, mock_hooks_giftmode):
        """At least one hook must reference the topic context"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with patch.object(generator, '_call_llm', return_value=mock_hooks_giftmode):
            with patch.object(generator, '_build_full_script', return_value="script"):
                variants = generator.generate(
                    topic="forgot birthday gift",
                    brand="GiftMode"
                )

        # At least one hook should relate to gifts/birthday
        all_hooks_text = " ".join(v["hook_text"].lower() for v in variants)
        topic_words = ["gift", "birthday", "forgot", "panic"]
        assert any(word in all_hooks_text for word in topic_words)

    def test_prompt_instructs_pattern_interrupt(self):
        """Hook generation prompt must instruct for pattern-interrupt style"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        prompt = generator._build_prompt(
            topic="forgot birthday gift",
            brand="GiftMode",
            count=5
        )

        pattern_interrupt_signals = ["hook", "attention", "scroll", "ugc", "tiktok"]
        assert any(signal in prompt.lower() for signal in pattern_interrupt_signals)

    def test_prompt_includes_brand_audience(self):
        """Prompt must include brand audience context"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        prompt = generator._build_prompt(
            topic="forgot birthday gift",
            brand="GiftMode",
            count=5
        )

        assert "audience" in prompt.lower() or "consumer" in prompt.lower()

    def test_invalid_brand_raises_value_error(self):
        """Unknown brand must raise ValueError"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with pytest.raises(ValueError, match="Unknown brand"):
            generator.generate(topic="test", brand="FakeBrand")

    def test_empty_topic_raises_value_error(self):
        """Empty topic must raise ValueError"""
        from core.hook_generator import HookGenerator
        generator = HookGenerator()

        with pytest.raises(ValueError, match="topic"):
            generator.generate(topic="", brand="GiftMode")
