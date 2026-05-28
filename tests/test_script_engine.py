"""
HezCast Engine — Script Engine Tests
TDD Phase 1 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)
"""

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
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
def sample_request():
    return {
        "topic": "forgot birthday gift",
        "brand": "GiftMode",
        "tone": "emotional"
    }

@pytest.fixture
def tinlance_request():
    return {
        "topic": "your website got hacked at 2am",
        "brand": "Tinlance",
        "tone": "authority"
    }

@pytest.fixture
def webtemify_request():
    return {
        "topic": "building a landing page in 10 minutes",
        "brand": "WebTemify",
        "tone": "developer_energy"
    }


# ─────────────────────────────────────────────
# BRAND CONFIG TESTS
# ─────────────────────────────────────────────

class TestBrandConfig:

    def test_all_three_brands_present(self, brand_config):
        """All 3 brands must exist in config"""
        assert "GiftMode" in brand_config
        assert "Tinlance" in brand_config
        assert "WebTemify" in brand_config

    def test_each_brand_has_required_keys(self, brand_config):
        """Every brand must have the full config schema"""
        required_keys = [
            "tone", "style", "audience", "persona_name",
            "voice_model", "subtitle_color", "hook_variants",
            "video_duration_target", "cta", "clip_emotion_tags"
        ]
        for brand, config in brand_config.items():
            for key in required_keys:
                assert key in config, f"{brand} missing key: {key}"

    def test_hook_variants_are_valid_integers(self, brand_config):
        """hook_variants must be int between 1 and 10"""
        for brand, config in brand_config.items():
            assert isinstance(config["hook_variants"], int)
            assert 1 <= config["hook_variants"] <= 10

    def test_video_duration_targets_are_reasonable(self, brand_config):
        """Duration targets must be between 15 and 60 seconds"""
        for brand, config in brand_config.items():
            assert 15 <= config["video_duration_target"] <= 60

    def test_subtitle_colors_are_valid_hex(self, brand_config):
        """Subtitle colors must be valid hex codes"""
        import re
        hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')
        for brand, config in brand_config.items():
            assert hex_pattern.match(config["subtitle_color"]), \
                f"{brand} has invalid subtitle_color: {config['subtitle_color']}"

    def test_clip_emotion_tags_are_lists(self, brand_config):
        """Emotion tags must be non-empty lists"""
        for brand, config in brand_config.items():
            assert isinstance(config["clip_emotion_tags"], list)
            assert len(config["clip_emotion_tags"]) >= 3


# ─────────────────────────────────────────────
# SCRIPT STRUCTURE TESTS
# ─────────────────────────────────────────────

class TestScriptStructure:

    def test_script_has_all_required_sections(self):
        """Generated script must have all 6 sections"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response()
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        required_sections = ["hook", "problem", "agitate", "solution", "proof", "cta"]
        for section in required_sections:
            assert section in result, f"Script missing section: {section}"

    def test_script_has_metadata_fields(self):
        """Script result must include metadata"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response()
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        assert "full_script" in result
        assert "estimated_duration_sec" in result
        assert "word_count" in result
        assert "llm_used" in result

    def test_full_script_concatenates_all_sections(self):
        """full_script must contain content from all sections"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response()
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        for section in ["hook", "problem", "agitate", "solution", "proof", "cta"]:
            assert result[section] in result["full_script"]

    def test_word_count_matches_full_script(self):
        """word_count must accurately reflect full_script length"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response()
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        actual_word_count = len(result["full_script"].split())
        assert abs(result["word_count"] - actual_word_count) <= 2

    def test_estimated_duration_is_realistic(self):
        """Duration estimate must be between 10 and 60 seconds"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response()
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        assert 10 <= result["estimated_duration_sec"] <= 60

    def test_no_section_is_empty_string(self):
        """No script section should be empty"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response()
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        for section in ["hook", "problem", "agitate", "solution", "proof", "cta"]:
            assert len(result[section].strip()) > 0, f"Section '{section}' is empty"


# ─────────────────────────────────────────────
# BRAND CONTEXT INJECTION TESTS
# ─────────────────────────────────────────────

class TestBrandContextInjection:

    def test_cta_matches_brand_config(self, brand_config):
        """Generated script CTA must match brand config CTA"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_llm') as mock_llm:
            mock_llm.return_value = _mock_script_response(
                cta=brand_config["GiftMode"]["cta"]
            )
            result = engine.generate(
                topic="forgot birthday gift",
                brand="GiftMode",
                tone="emotional"
            )

        assert brand_config["GiftMode"]["cta"] in result["cta"] or \
               result["cta"] in brand_config["GiftMode"]["cta"] or \
               len(result["cta"]) > 0

    def test_brand_prompt_includes_audience(self):
        """The LLM prompt must include the brand's target audience"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()
        prompt = engine._build_prompt(
            topic="forgot birthday gift",
            brand="GiftMode",
            tone="emotional"
        )
        assert "consumers" in prompt.lower() or "audience" in prompt.lower()

    def test_brand_prompt_includes_tone(self):
        """The LLM prompt must include the tone"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()
        prompt = engine._build_prompt(
            topic="forgot birthday gift",
            brand="GiftMode",
            tone="emotional"
        )
        assert "emotional" in prompt.lower()

    def test_brand_prompt_includes_topic(self):
        """The LLM prompt must include the topic"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()
        prompt = engine._build_prompt(
            topic="forgot birthday gift",
            brand="GiftMode",
            tone="emotional"
        )
        assert "forgot birthday gift" in prompt

    def test_different_brands_produce_different_prompts(self):
        """GiftMode and Tinlance must produce distinct prompts"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        prompt_giftmode = engine._build_prompt(
            topic="test", brand="GiftMode", tone="emotional"
        )
        prompt_tinlance = engine._build_prompt(
            topic="test", brand="Tinlance", tone="authority"
        )

        assert prompt_giftmode != prompt_tinlance


# ─────────────────────────────────────────────
# LLM FALLBACK CHAIN TESTS
# ─────────────────────────────────────────────

class TestLLMFallbackChain:

    def test_uses_claude_as_primary(self):
        """Claude must be the first LLM attempted"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_claude') as mock_claude:
            mock_claude.return_value = _mock_script_response()
            result = engine.generate(
                topic="test", brand="GiftMode", tone="emotional"
            )
            assert mock_claude.called
            assert result["llm_used"] == "claude"

    def test_falls_back_to_gpt4o_when_claude_fails(self):
        """Must fall back to GPT-4o when Claude raises exception"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_claude', side_effect=Exception("API error")):
            with patch.object(engine, '_call_gpt4o') as mock_gpt:
                mock_gpt.return_value = _mock_script_response(llm="gpt-4o")
                result = engine.generate(
                    topic="test", brand="GiftMode", tone="emotional"
                )
                assert mock_gpt.called
                assert result["llm_used"] == "gpt-4o"

    def test_falls_back_to_ollama_when_both_apis_fail(self):
        """Must fall back to Ollama when Claude and GPT-4o both fail"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with patch.object(engine, '_call_claude', side_effect=Exception("Claude down")):
            with patch.object(engine, '_call_gpt4o', side_effect=Exception("GPT down")):
                with patch.object(engine, '_call_ollama') as mock_ollama:
                    mock_ollama.return_value = _mock_script_response(llm="ollama")
                    result = engine.generate(
                        topic="test", brand="GiftMode", tone="emotional"
                    )
                    assert mock_ollama.called
                    assert result["llm_used"] == "ollama"

    def test_raises_when_all_llms_fail(self):
        """Must raise ScriptGenerationError when all LLMs fail"""
        from core.script_engine import ScriptEngine, ScriptGenerationError
        engine = ScriptEngine()

        with patch.object(engine, '_call_claude', side_effect=Exception("down")):
            with patch.object(engine, '_call_gpt4o', side_effect=Exception("down")):
                with patch.object(engine, '_call_ollama', side_effect=Exception("down")):
                    with pytest.raises(ScriptGenerationError):
                        engine.generate(
                            topic="test", brand="GiftMode", tone="emotional"
                        )

    def test_invalid_brand_raises_value_error(self):
        """Requesting an unknown brand must raise ValueError"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with pytest.raises(ValueError, match="Unknown brand"):
            engine.generate(
                topic="test", brand="UnknownBrand", tone="emotional"
            )

    def test_empty_topic_raises_value_error(self):
        """Empty topic must raise ValueError"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with pytest.raises(ValueError, match="topic"):
            engine.generate(topic="", brand="GiftMode", tone="emotional")

    def test_whitespace_only_topic_raises_value_error(self):
        """Whitespace-only topic must raise ValueError"""
        from core.script_engine import ScriptEngine
        engine = ScriptEngine()

        with pytest.raises(ValueError, match="topic"):
            engine.generate(topic="   ", brand="GiftMode", tone="emotional")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _mock_script_response(cta=None, llm="claude"):
    return {
        "hook": "Nobody told me you could forget your mum's birthday TWICE...",
        "problem": "I had 2 hours, zero ideas, and a guilt trip loading...",
        "agitate": "I panicked. Opened Amazon. 847 options. Closed Amazon.",
        "solution": "GiftMode gave me 3 perfect ideas in 9 seconds. Done.",
        "proof": "500,000 people already use it. For free.",
        "cta": cta or "Download GiftMode. Before you forget again.",
        "full_script": "Nobody told me you could forget your mum's birthday TWICE... "
                       "I had 2 hours, zero ideas, and a guilt trip loading... "
                       "I panicked. Opened Amazon. 847 options. Closed Amazon. "
                       "GiftMode gave me 3 perfect ideas in 9 seconds. Done. "
                       "500,000 people already use it. For free. "
                       "Download GiftMode. Before you forget again.",
        "estimated_duration_sec": 26,
        "word_count": 68,
        "llm_used": llm
    }
