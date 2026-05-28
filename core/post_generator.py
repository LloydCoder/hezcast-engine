"""
HezCast Engine — Post Content Generator
Tinlance Limited | Apache 2.0

Converts a rendered video script into a full social media post bundle:
  - title       → YouTube/TikTok video title
  - caption     → main post copy with emojis
  - hashtags    → 10 researched tags
  - cta_link    → brand-specific landing URL
  - platform_variants → TikTok / Instagram / LinkedIn adaptations

One LLM call per job. Injected into Celery chain after qa_check_task.
Uses the same hybrid fallback chain as ScriptEngine:
  Claude Sonnet → GPT-4o → Ollama
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# BRAND POST CONFIG
# ─────────────────────────────────────────────

BRAND_POST_CONFIG = {
    "GiftMode": {
        "cta_link":    "https://giftmode.app",
        "brand_voice": "warm, relatable, emotionally resonant",
        "tone_notes":  "Use emojis. Speak to the guilt, panic, relief arc. End with urgency.",
        "core_tags":   ["#GiftMode", "#GiftIdeas", "#GiftApp"],
        "audience":    "consumers aged 25-40",
    },
    "Tinlance": {
        "cta_link":    "https://tinlance.com",
        "brand_voice": "authoritative, direct, credibility-first",
        "tone_notes":  "No fluff. Lead with consequence. End with a clear action.",
        "core_tags":   ["#Tinlance", "#CyberSecurity", "#AIEngineering"],
        "audience":    "business owners and founders",
    },
    "WebTemify": {
        "cta_link":    "https://webtemify.com",
        "brand_voice": "fast, energetic, developer-friendly",
        "tone_notes":  "Speed and results. Use numbers. Speak dev-to-dev.",
        "core_tags":   ["#WebTemify", "#WebDesign", "#NoCode"],
        "audience":    "founders and developers",
    },
}


class PostGenerator:
    """
    Generates a complete social media post bundle from a video script.

    Usage:
        generator = PostGenerator()
        bundle = generator.generate(
            script="Nobody told me you could forget TWICE...",
            brand="GiftMode"
        )
        path = generator.save_bundle(bundle, "/storage/inputs/job_id/post_bundle.json")
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"
        with open(config_path) as f:
            self.brand_config = json.load(f)

        self._claude_client  = None
        self._openai_client  = None

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def generate(self, script: str, brand: str) -> dict:
        """
        Generate a full social media post bundle from a video script.

        Args:
            script: The full video script text
            brand:  Brand name (GiftMode | Tinlance | WebTemify)

        Returns:
            dict with: title, caption, hashtags, cta_link, platform_variants

        Raises:
            ValueError: If script is empty or brand is unknown
            PostGenerationError: If all LLMs fail
        """
        self._validate(script, brand)

        prompt = self._build_prompt(script, brand)
        raw    = self._call_llm(prompt)
        bundle = self._parse_response(raw, brand)

        # Enforce quality rules
        bundle["hashtags"] = self._clean_hashtags(bundle.get("hashtags", []))
        bundle["cta_link"] = BRAND_POST_CONFIG[brand]["cta_link"]

        logger.info(
            f"Post bundle generated | brand={brand} | "
            f"hashtags={len(bundle['hashtags'])} | "
            f"title_len={len(bundle.get('title', ''))}"
        )
        return bundle

    def save_bundle(self, bundle: dict, output_path: str) -> str:
        """
        Save post bundle to JSON file.

        Args:
            bundle:      The post bundle dict from generate()
            output_path: Full path for output JSON file

        Returns:
            output_path (str)
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Post bundle saved: {output_path}")
        return output_path

    # ─────────────────────────────────────────
    # PROMPT BUILDER
    # ─────────────────────────────────────────

    def _build_prompt(self, script: str, brand: str) -> str:
        cfg = BRAND_POST_CONFIG[brand]
        brand_cfg = self.brand_config[brand]
        core_tags = " ".join(cfg["core_tags"])

        return f"""You are a social media content strategist for {brand}.

BRAND: {brand}
BRAND VOICE: {cfg['brand_voice']}
TONE NOTES: {cfg['tone_notes']}
AUDIENCE: {cfg['audience']}
CTA LINK: {cfg['cta_link']}
CORE HASHTAGS TO INCLUDE: {core_tags}

VIDEO SCRIPT:
{script}

TASK:
Generate a complete social media post bundle for this video. Return ONLY valid JSON:

{{
  "title": "<YouTube/TikTok video title — punchy, under 80 chars, no emojis>",
  "caption": "<main post copy — 3-5 sentences, emojis welcome, brand voice, ends with CTA>",
  "hashtags": [<list of 10 unique hashtags, all starting with #, no spaces, include the core tags>],
  "cta_link": "{cfg['cta_link']}",
  "platform_variants": {{
    "tiktok": "<TikTok caption — punchy, under 150 chars, 3-5 hashtags inline>",
    "instagram": "<Instagram caption — 2-4 sentences, line breaks, emojis, hashtags at end>",
    "linkedin": "<LinkedIn caption — professional, insight-focused, no hashtag spam, 2-3 sentences>"
  }}
}}

RULES:
1. Title must be between 10–80 characters
2. Caption must reference {brand} by name
3. All hashtags must start with # and have no spaces
4. Platform variants must be genuinely adapted — not copy-pasted
5. LinkedIn tone must be professional, no emojis
6. Return ONLY the JSON object. No preamble, no markdown fences.
"""

    # ─────────────────────────────────────────
    # LLM INTERFACE (mockable)
    # ─────────────────────────────────────────

    def _call_llm(self, prompt: str) -> dict:
        """
        Call LLM via fallback chain.
        Mocked in tests via patch('core.post_generator.PostGenerator._call_llm').
        """
        chain = [
            ("claude",  self._call_claude),
            ("gpt-4o",  self._call_gpt4o),
            ("ollama",  self._call_ollama),
        ]
        last_error = None
        for name, fn in chain:
            try:
                raw  = fn(prompt)
                data = self._parse_response(raw, brand="GiftMode")  # parse test
                logger.debug(f"Post LLM success: {name}")
                return data
            except Exception as e:
                logger.warning(f"Post LLM {name} failed: {e}")
                last_error = e
        raise PostGenerationError(f"All LLMs failed. Last: {last_error}")

    def _call_claude(self, prompt: str) -> str:
        import anthropic
        if self._claude_client is None:
            key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise ValueError("CLAUDE_API_KEY not set")
            self._claude_client = anthropic.Anthropic(api_key=key)
        msg = self._claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    def _call_gpt4o(self, prompt: str) -> str:
        from openai import OpenAI
        if self._openai_client is None:
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise ValueError("OPENAI_API_KEY not set")
            self._openai_client = OpenAI(api_key=key)
        resp = self._openai_client.chat.completions.create(
            model="gpt-4o", max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content

    def _call_ollama(self, prompt: str) -> str:
        import requests
        url   = os.getenv("OLLAMA_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")
        resp  = requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json()["response"]

    # ─────────────────────────────────────────
    # PARSING & CLEANING
    # ─────────────────────────────────────────

    def _parse_response(self, raw, brand: str = "") -> dict:
        """Parse LLM JSON response into bundle dict"""
        # Handle dict passthrough (from mock or already-parsed)
        if isinstance(raw, dict):
            return raw

        cleaned = re.sub(r'```json\s*', '', str(raw))
        cleaned = re.sub(r'```\s*',     '', cleaned).strip()
        match   = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON in post response: {raw[:200]}")

        parsed = json.loads(match.group())

        # Ensure all required keys exist
        for key in ["title", "caption", "hashtags", "cta_link", "platform_variants"]:
            if key not in parsed:
                parsed[key] = self._fallback_value(key, brand)

        # Ensure platform_variants has all three platforms
        pv = parsed.get("platform_variants", {})
        for platform in ["tiktok", "instagram", "linkedin"]:
            if platform not in pv:
                pv[platform] = parsed.get("caption", "")
        parsed["platform_variants"] = pv

        return parsed

    def _fallback_value(self, key: str, brand: str) -> object:
        """Provide fallback values for missing keys"""
        fallbacks = {
            "title":              f"New video from {brand}",
            "caption":            f"Check out our latest from {brand}.",
            "hashtags":           BRAND_POST_CONFIG.get(brand, {}).get("core_tags", ["#HezCast"]),
            "cta_link":           BRAND_POST_CONFIG.get(brand, {}).get("cta_link", ""),
            "platform_variants":  {"tiktok": "", "instagram": "", "linkedin": ""},
        }
        return fallbacks.get(key, "")

    def _clean_hashtags(self, tags: list) -> list:
        """Ensure all hashtags are valid: start with #, no spaces, unique"""
        cleaned = []
        seen    = set()
        for tag in tags:
            tag = str(tag).strip()
            if not tag.startswith("#"):
                tag = f"#{tag}"
            # Remove spaces within tag
            tag = tag.replace(" ", "")
            normalized = tag.lower()
            if normalized not in seen and len(tag) > 1:
                seen.add(normalized)
                cleaned.append(tag)
        return cleaned[:15]  # Cap at 15

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    def _validate(self, script: str, brand: str) -> None:
        if not script or not script.strip():
            raise ValueError("script must be a non-empty string")
        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class PostGenerationError(Exception):
    """Raised when all LLMs fail for post generation"""
    pass
