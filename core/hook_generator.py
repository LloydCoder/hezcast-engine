"""
HezCast Engine — Hook A/B Generator
Tinlance Limited | Apache 2.0

Generates N hook variants per topic based on brand config.
Each variant becomes a full script candidate for A/B selection.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from core.script_engine import ScriptEngine, ScriptGenerationError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HOOK GENERATOR
# ─────────────────────────────────────────────

class HookGenerator:
    """
    Generates multiple hook variants for A/B testing.

    The number of variants is configured per brand in brands.json.
    Each variant is a unique scroll-stopping opener that feeds
    into the full script pipeline.

    Usage:
        generator = HookGenerator()
        variants = generator.generate(
            topic="forgot birthday gift",
            brand="GiftMode"
        )
        selected = generator.select(variants, variant_num=2)
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"

        with open(config_path) as f:
            self.brand_config = json.load(f)

        self.script_engine = ScriptEngine(config_path=str(config_path))

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def generate(self, topic: str, brand: str) -> list[dict]:
        """
        Generate N hook variants for the given topic and brand.

        Args:
            topic: The pain point or scenario
            brand: Brand name (must exist in brands.json)

        Returns:
            List of variant dicts, each containing:
            - variant_num (int, 1-indexed)
            - hook_text (str)
            - full_script (str)
            - selected (bool, default False)

        Raises:
            ValueError: If topic is empty or brand unknown
            ScriptGenerationError: If LLM chain fails
        """
        self._validate_inputs(topic, brand)

        brand_data = self.brand_config[brand]
        count = brand_data["hook_variants"]

        prompt = self._build_prompt(topic, brand, count)
        raw_hooks = self._call_llm(prompt)

        # Deduplicate and trim to requested count
        unique_hooks = self._deduplicate(raw_hooks)[:count]

        variants = []
        for i, hook_text in enumerate(unique_hooks):
            full_script = self._build_full_script(
                hook=hook_text,
                topic=topic,
                brand=brand
            )
            variants.append({
                "variant_num": i + 1,
                "hook_text": hook_text,
                "full_script": full_script,
                "selected": False
            })

        logger.info(
            f"Generated {len(variants)} hook variants | "
            f"brand={brand} | topic='{topic}'"
        )

        return variants

    def select(self, variants: list[dict], variant_num: int) -> dict:
        """
        Mark a specific variant as selected.

        Args:
            variants: List returned by generate()
            variant_num: 1-indexed variant number to select

        Returns:
            The selected variant dict with selected=True

        Raises:
            ValueError: If variant_num is out of range or zero
        """
        if variant_num < 1:
            raise ValueError(
                f"variant_num must be >= 1 (got {variant_num}). "
                f"Variants are 1-indexed."
            )

        max_num = max(v["variant_num"] for v in variants)

        if variant_num > max_num:
            raise ValueError(
                f"variant_num {variant_num} out of range. "
                f"Available: 1–{max_num}"
            )

        for variant in variants:
            if variant["variant_num"] == variant_num:
                variant["selected"] = True
                logger.info(f"Hook variant {variant_num} selected")
                return variant

        raise ValueError(f"Variant {variant_num} not found in variants list")

    # ─────────────────────────────────────────
    # PROMPT BUILDER
    # ─────────────────────────────────────────

    def _build_prompt(self, topic: str, brand: str, count: int) -> str:
        brand_data = self.brand_config[brand]

        pattern_examples = "\n".join(
            f"  {i+1}. {p}"
            for i, p in enumerate(brand_data.get("hook_patterns", []))
        )

        return f"""You are a UGC hook specialist writing scroll-stopping TikTok/Reels openers for {brand}.

BRAND: {brand}
AUDIENCE: {brand_data['audience'].replace('_', ' ')}
TONE: {brand_data['tone']}
TOPIC / SCENARIO: {topic}

HOOK PATTERN EXAMPLES (use as inspiration, not templates):
{pattern_examples}

TASK:
Generate exactly {count} unique hook variants for this topic.

HOOK RULES:
- Maximum 15 words each
- Must create immediate tension, curiosity, or pattern interruption
- Written in {brand_data['tone']} tone
- Each must be distinctly different in angle and structure
- No generic hooks like "Have you ever..." or "Did you know..."
- Think: what would make someone stop scrolling in 0.5 seconds?

Return ONLY a JSON array of {count} strings. No preamble, no numbering, no explanation.
Example format: ["Hook one here", "Hook two here", "Hook three here"]
"""

    # ─────────────────────────────────────────
    # LLM INTERFACE
    # ─────────────────────────────────────────

    def _call_llm(self, prompt: str) -> list[str]:
        """
        Call LLM via fallback chain and parse hook list response.
        Delegates to ScriptEngine's fallback chain infrastructure.
        """
        chain = [
            ("claude", self.script_engine._call_claude),
            ("gpt-4o", self.script_engine._call_gpt4o),
            ("ollama", self.script_engine._call_ollama),
        ]

        last_error = None

        for llm_name, call_fn in chain:
            try:
                raw = call_fn(prompt)
                hooks = self._parse_hooks_response(raw)
                if hooks:
                    logger.debug(f"Hook LLM success: {llm_name}")
                    return hooks
            except Exception as e:
                logger.warning(f"Hook LLM {llm_name} failed: {e}")
                last_error = e
                continue

        raise ScriptGenerationError(
            f"All LLMs failed for hook generation. Last error: {last_error}"
        )

    # ─────────────────────────────────────────
    # PARSING
    # ─────────────────────────────────────────

    def _parse_hooks_response(self, raw: str) -> list[str]:
        """Parse JSON array of hook strings from LLM response"""
        cleaned = re.sub(r'```json\s*', '', raw)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        # Find JSON array
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array found in hooks response: {raw[:200]}")

        hooks = json.loads(match.group())

        if not isinstance(hooks, list):
            raise ValueError("LLM returned non-list for hooks")

        # Clean and validate each hook
        cleaned_hooks = []
        for h in hooks:
            hook = str(h).strip().strip('"').strip("'")
            if hook:
                cleaned_hooks.append(hook)

        return cleaned_hooks

    def _build_full_script(self, hook: str, topic: str, brand: str) -> str:
        """
        Build a full script starting from a specific hook.
        Injects the hook as the script opener via the script engine.
        """
        brand_data = self.brand_config[brand]

        # Build a focused prompt that uses this specific hook
        prompt = f"""Complete this UGC video script for {brand}.

HOOK (already written — do NOT change it):
{hook}

TOPIC: {topic}
BRAND TONE: {brand_data['tone']}
AUDIENCE: {brand_data['audience'].replace('_', ' ')}
CTA: {brand_data['cta']}
STYLE NOTES: {brand_data.get('script_style_notes', '')}

Write the remaining sections to complete the script. Return ONLY valid JSON:

{{
  "hook": "{hook}",
  "problem": "<expand the pain point, 1-2 sentences>",
  "agitate": "<deepen the pain, 1-2 sentences>",
  "solution": "<introduce the product as hero, 1-2 sentences>",
  "proof": "<one credibility signal, 1 sentence>",
  "cta": "<call to action using brand CTA: {brand_data['cta']}>"
}}

Return ONLY the JSON. No markdown, no explanation."""

        try:
            chain = [
                self.script_engine._call_claude,
                self.script_engine._call_gpt4o,
                self.script_engine._call_ollama,
            ]
            for call_fn in chain:
                try:
                    raw = call_fn(prompt)
                    parsed = self.script_engine._parse_llm_response(raw)
                    return self.script_engine._build_full_script(parsed)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Full script build failed for hook variant: {e}")

        # Fallback: return hook alone if full script fails
        return hook

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────

    def _deduplicate(self, hooks: list[str]) -> list[str]:
        """Remove duplicate hooks while preserving order"""
        seen = set()
        unique = []
        for hook in hooks:
            normalized = hook.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(hook)
        return unique

    def _validate_inputs(self, topic: str, brand: str) -> None:
        if not topic or not topic.strip():
            raise ValueError("topic must be a non-empty string")

        if brand not in self.brand_config:
            available = list(self.brand_config.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available brands: {available}"
            )
