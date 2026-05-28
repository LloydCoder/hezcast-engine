"""
HezCast Engine — Script Engine
Tinlance Limited | Apache 2.0

Hybrid LLM fallback chain:
  Primary:  Claude Sonnet
  Fallback: GPT-4o
  Fallback: Ollama (local)

Generates UGC-style marketing scripts with 6-section structure:
  Hook → Problem → Agitate → Solution → Proof → CTA
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────

class ScriptGenerationError(Exception):
    """Raised when all LLMs in the fallback chain fail"""
    pass


class BrandConfigError(Exception):
    """Raised when brand config is missing or malformed"""
    pass


# ─────────────────────────────────────────────
# SCRIPT ENGINE
# ─────────────────────────────────────────────

class ScriptEngine:
    """
    Generates structured UGC marketing scripts for HezCast brands.

    Usage:
        engine = ScriptEngine()
        script = engine.generate(
            topic="forgot birthday gift",
            brand="GiftMode",
            tone="emotional"
        )
    """

    # Average speaking pace for TTS duration estimation
    WORDS_PER_SECOND = 2.6

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"

        with open(config_path) as f:
            self.brand_config = json.load(f)

        # LLM clients — lazy initialized on first use
        self._claude_client = None
        self._openai_client = None

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def generate(
        self,
        topic: str,
        brand: str,
        tone: Optional[str] = None
    ) -> dict:
        """
        Generate a full UGC script for the given topic and brand.

        Args:
            topic: The pain point or scenario to build the script around
            brand: Brand name (must exist in brands.json)
            tone:  Optional tone override (defaults to brand config tone)

        Returns:
            dict with keys: hook, problem, agitate, solution, proof, cta,
                            full_script, estimated_duration_sec, word_count, llm_used

        Raises:
            ValueError: If topic is empty or brand is unknown
            ScriptGenerationError: If all LLMs in fallback chain fail
        """
        self._validate_inputs(topic, brand)

        brand_data = self.brand_config[brand]
        effective_tone = tone or brand_data["tone"]
        prompt = self._build_prompt(topic, brand, effective_tone)

        # Route through _call_llm (patchable in tests)
        raw_result = self._call_llm(prompt)
        # _call_llm returns dict; extract llm_used if present
        llm_used = raw_result.pop("llm_used", "claude")
        result = raw_result

        # Enrich result
        result["llm_used"] = llm_used
        result["full_script"] = self._build_full_script(result)
        result["word_count"] = len(result["full_script"].split())
        result["estimated_duration_sec"] = round(
            result["word_count"] / self.WORDS_PER_SECOND, 1
        )

        logger.info(
            f"Script generated | brand={brand} | llm={llm_used} | "
            f"words={result['word_count']} | "
            f"duration={result['estimated_duration_sec']}s"
        )

        return result

    # ─────────────────────────────────────────
    # PROMPT BUILDER
    # ─────────────────────────────────────────

    def _build_prompt(self, topic: str, brand: str, tone: str) -> str:
        brand_data = self.brand_config[brand]

        hook_patterns = "\n".join(
            f"  - {p}" for p in brand_data.get("hook_patterns", [])
        )

        return f"""You are an expert UGC video scriptwriter for {brand}, a brand targeting {brand_data['audience'].replace('_', ' ')}.

BRAND CONTEXT:
- Brand: {brand}
- Tone: {tone}
- Style: {brand_data['style']}
- Audience: {brand_data['audience'].replace('_', ' ')}
- CTA: {brand_data['cta']}
- Script style notes: {brand_data.get('script_style_notes', '')}

TOPIC / SCENARIO:
{topic}

HOOK PATTERNS TO INSPIRE FROM (do not copy verbatim):
{hook_patterns}

TASK:
Write a UGC-style short-form video script (20–30 seconds when spoken) in exactly this JSON structure:

{{
  "hook": "<pattern-interrupt opener, max 15 words, creates immediate tension or curiosity>",
  "problem": "<relatable pain point expansion, 1-2 sentences>",
  "agitate": "<deepen the pain — make them feel it more, 1-2 sentences>",
  "solution": "<introduce the product/service as the hero, specific and clear, 1-2 sentences>",
  "proof": "<one credibility signal — number, result, or social proof, 1 sentence>",
  "cta": "<clear call to action matching brand CTA: {brand_data['cta']}, 1 sentence>"
}}

RULES:
1. Hook must stop the scroll — be unexpected, specific, or emotionally charged
2. Write in the brand tone: {tone}
3. Use first-person voice ("I", "you") for consumer brands, authoritative third-person for B2B
4. Keep total word count between 55–80 words
5. CTA must reference the brand name
6. Return ONLY valid JSON. No preamble, no explanation, no markdown fences.
"""

    # ─────────────────────────────────────────
    # FALLBACK CHAIN
    # ─────────────────────────────────────────

    def _execute_fallback_chain(self, prompt: str) -> tuple[dict, str]:
        """Try each LLM in order. Return (result, llm_name) on first success."""

        chain = [
            ("claude", self._call_claude),
            ("gpt-4o", self._call_gpt4o),
            ("ollama", self._call_ollama),
        ]

        last_error = None

        for llm_name, call_fn in chain:
            try:
                logger.debug(f"Attempting LLM: {llm_name}")
                raw = call_fn(prompt)
                # Support both str (real LLM) and dict (test mocks) returns
                if isinstance(raw, dict):
                    parsed = raw
                    # Validate required keys
                    required = ["hook", "problem", "agitate", "solution", "proof", "cta"]
                    for key in required:
                        if key not in parsed:
                            raise ValueError(f"Response missing key: {key}")
                else:
                    parsed = self._parse_llm_response(raw)
                return parsed, llm_name
            except Exception as e:
                logger.warning(f"LLM {llm_name} failed: {e}")
                last_error = e
                continue

        raise ScriptGenerationError(
            f"All LLMs failed. Last error: {last_error}"
        )

    # ─────────────────────────────────────────
    # LLM CALLERS
    # ─────────────────────────────────────────

    def _call_claude(self, prompt: str) -> str:
        """Call Anthropic Claude Sonnet"""
        import anthropic

        if self._claude_client is None:
            api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("CLAUDE_API_KEY not set")
            self._claude_client = anthropic.Anthropic(api_key=api_key)

        message = self._claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text

    def _call_gpt4o(self, prompt: str) -> str:
        """Call OpenAI GPT-4o"""
        from openai import OpenAI

        if self._openai_client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            self._openai_client = OpenAI(api_key=api_key)

        response = self._openai_client.chat.completions.create(
            model="gpt-4o",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    def _call_ollama(self, prompt: str) -> str:
        """Call local Ollama instance"""
        import requests

        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3")

        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.8, "num_predict": 512}
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()["response"]

    def _call_llm(self, prompt: str) -> dict:
        """
        Unified LLM interface — primary entry point for generate().
        Patchable in tests. Delegates to fallback chain in production.
        """
        result, llm_name = self._execute_fallback_chain(prompt)
        result["llm_used"] = llm_name
        return result

    # ─────────────────────────────────────────
    # PARSING & ASSEMBLY
    # ─────────────────────────────────────────

    def _parse_llm_response(self, raw: str) -> dict:
        """
        Parse LLM JSON response into script dict.
        Handles markdown fences and trailing text.
        """
        # Strip markdown fences if present
        cleaned = re.sub(r'```json\s*', '', raw)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        # Extract JSON object
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {raw[:200]}")

        parsed = json.loads(match.group())

        required = ["hook", "problem", "agitate", "solution", "proof", "cta"]
        for key in required:
            if key not in parsed:
                raise ValueError(f"LLM response missing required key: {key}")
            if not str(parsed[key]).strip():
                raise ValueError(f"LLM response has empty value for key: {key}")

        return parsed

    def _build_full_script(self, script: dict) -> str:
        """Concatenate all script sections into a single narration string"""
        sections = ["hook", "problem", "agitate", "solution", "proof", "cta"]
        return " ".join(script[s] for s in sections if s in script)

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    def _validate_inputs(self, topic: str, brand: str) -> None:
        if not topic or not topic.strip():
            raise ValueError("topic must be a non-empty string")

        if brand not in self.brand_config:
            available = list(self.brand_config.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available brands: {available}"
            )
