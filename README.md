# HezCast Engine

**AI Content Broadcasting System by [Tinlance Limited](https://tinlance.com)**

> *"Turn ideas into broadcast-ready content."*

One prompt. One brand. One complete content package — video, captions, hashtags, thumbnails, published to Telegram automatically.

```
Input:  "forgot birthday gift" + GiftMode brand
Output: 25s MP4 + thumbnail + caption + hashtags → Telegram channel
```

---

## What HezCast Is

HezCast is Tinlance's open-core AI content broadcasting system. The same way ThreatFade powers KalevioAI's security layer, HezCast powers content production across every Tinlance product — and yours.

**Not a video tool. Content infrastructure.**

It generates, packages, and distributes short-form video content across platforms automatically. Script → voice → video → captions → post bundle → Telegram. Fully autonomous.

---

## Open Layer (this repo — Apache 2.0)

- Script engine — hybrid LLM chain (Claude → GPT-4o → Ollama)
- Hook A/B generator — 3–5 scroll-stopping variants per topic
- Voice engine — Piper TTS with per-brand voice profiles
- Semantic clip selector — CLIP + FAISS zero-shot visual matching
- Video composer — FFmpeg, 1080×1920 vertical MP4
- Subtitle engine — faster-whisper, TikTok-style word-level captions
- QA validator — 7-point post-render quality gate
- Post content generator — title, caption, hashtags, platform variants
- Telegram publisher — auto-publish MP4 + bundle to channel
- Brand config system — GiftMode, Tinlance, WebTemify, HezCast
- Full Docker stack (CPU + GPU override)
- REST API (FastAPI + Celery + Redis)

## Commercial Layer (private — [HezCast SaaS](https://cast.tinlance.com))

- Web dashboard (live, connected to real API)
- Avatar engine (MuseTalk lip-sync)
- Telegram bot (bidirectional — send prompt, receive MP4)
- Billing system (LemonSqueezy credit engine)
- Analytics + hook performance tracking
- Multi-tenant white-label

---

## Quick Start

```bash
git clone https://github.com/Tinlance/hezcast-engine.git
cd hezcast-engine
cp .env.example .env
# Add CLAUDE_API_KEY and PEXELS_API_KEY
docker-compose up
```

```bash
curl -X POST http://localhost:8503/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "forgot birthday gift", "brand": "GiftMode"}'
# → {"job_id": "abc-123", "status": "queued"}
```

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/generate` | Submit job → returns job_id |
| GET | `/status/{job_id}` | Poll status + get output |
| GET | `/hooks/{job_id}` | View A/B hook variants |
| POST | `/hooks/{job_id}/select` | Select hook → trigger render |
| GET | `/health` | System health |
| GET | `/brands` | List configured brands |

---

## Brands

| Brand | Persona | Tone | Hooks |
|-------|---------|------|-------|
| GiftMode | Maya | Emotional UGC | 5 |
| Tinlance | Lloyd | Authority | 3 |
| WebTemify | Dev | Developer energy | 4 |
| HezCast | Lloyd | Founder energy | 5 |

---

## Output Bundle Per Job

```
/storage/outputs/{job_id}/
  ├── final.mp4          → 1080×1920 H.264 video
  ├── thumbnail_1.png    → hook style
  ├── thumbnail_2.png    → curiosity style
  ├── thumbnail_3.png    → authority style
  ├── post_bundle.json   → title + caption + hashtags + platform variants
  └── subtitles.ass      → TikTok-style captions
```

---

## Tests

```bash
pytest tests/ -v        # 287 tests — all green
pytest tests/ --cov     # coverage report
```

---

## License

Core engine: [Apache 2.0](LICENSE)
Commercial layer: Proprietary — [Tinlance Limited](https://tinlance.com)

---

**Built by [Tinlance Limited](https://tinlance.com) — AI & Cybersecurity Engineering Studio, Nigeria**
RC: 7962164 | [cast.tinlance.com](https://cast.tinlance.com)

*HezCast — God strengthens. So does your content.*
