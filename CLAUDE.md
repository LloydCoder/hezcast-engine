# CLAUDE.md — HezCast Engine
## Full Context for Claude Code Sessions

> Read this file before touching any code. It contains every architectural
> decision, convention, and context needed to work on HezCast Engine correctly.

---

## What Is HezCast

**HezCast** is an AI Content Broadcasting System by **Tinlance Limited** (RC: 7962164, Nigeria).

It converts a topic + brand into a complete content package:
- 1080×1920 MP4 video (script → voice → clips → compose → QA)
- 3 branded thumbnail variants
- Post bundle (title + caption + hashtags + platform variants)
- Auto-published to Telegram channel

**Tagline:** *"Turn ideas into broadcast-ready content."*
**Domain:** `cast.tinlance.com` (subdomain of tinlance.com)
**Target domain:** `hezcast.ai` (to purchase)
**GitHub:** `github.com/Tinlance/hezcast-engine` (public, Apache 2.0)
**SaaS repo:** `github.com/Tinlance/hezcast-saas` (private, commercial)

---

## Current Build Status

**Phases 1–9 complete. 453 tests passing. 22 modules built.**

| Phase | What | Tests | Status |
|-------|------|-------|--------|
| 1 | Script Engine + Hook A/B Generator | 41 | ✅ |
| 2 | Voice Engine + Semantic Clip Selector | 54 | ✅ |
| 3 | Video Composer + Subtitle Engine + QA | 85 | ✅ |
| 4 | FastAPI + Celery + Docker | 52 | ✅ |
| 5 | Post Generator + Telegram Publisher | 55 | ✅ |
| 6 | Setup Script + Storage + Thumbnails + URL | 68 | ✅ |
| 7 | Telegram Bot + Webhook | 49 | ✅ |
| 8 | Landing + Pricing + Dashboard Design | — | ✅ |
| 9 | Billing + Credit Gate + Onboarding | 49 | ✅ |
| **10** | **Full Next.js App** | **—** | **🔲 IN PROGRESS** |

---

## Repository Structure

```
hezcast-engine/                    ← PUBLIC repo (Apache 2.0)
├── api/
│   ├── main.py                    ← FastAPI app, port 8503
│   ├── middleware/
│   │   ├── __init__.py            ← Credit gate helpers
│   │   └── credit_gate.py
│   ├── routes/
│   │   ├── billing.py             ← POST /billing/webhook, /topup, GET /balance
│   │   ├── brands.py              ← GET /brands
│   │   ├── generate.py            ← POST /generate
│   │   ├── health.py              ← GET /health
│   │   ├── hooks.py               ← GET /hooks/{id}, POST /hooks/{id}/select
│   │   ├── onboarding.py          ← POST /onboarding/brand, GET /onboarding/*
│   │   ├── status.py              ← GET /status/{id}
│   │   └── telegram_webhook.py    ← POST /telegram/webhook
│   └── schemas.py                 ← Pydantic v2 models
├── core/
│   ├── billing.py                 ← LemonSqueezy + credit management
│   ├── clip_selector.py           ← CLIP + FAISS semantic search
│   ├── hook_generator.py          ← A/B hook variants
│   ├── post_generator.py          ← Social media bundle
│   ├── qa_validator.py            ← 7-point quality gate
│   ├── script_engine.py           ← Hybrid LLM chain
│   ├── storage_lifecycle.py       ← B2 archive + auto-delete
│   ├── subtitle_engine.py         ← faster-whisper + ASS
│   ├── telegram_bot.py            ← Bidirectional bot
│   ├── telegram_publisher.py      ← Publish to channel
│   ├── thumbnail_engine.py        ← 3 branded variants
│   ├── url_preprocessor.py        ← URL/blog-to-video
│   ├── video_composer.py          ← FFmpeg orchestration
│   └── voice_engine.py            ← Piper TTS
├── workers/
│   ├── celery_app.py              ← Celery + Redis config
│   └── tasks.py                   ← 7-stage pipeline chain
├── config/
│   └── brands.json                ← 4 brands configured
├── database/
│   └── schemas.sql                ← PostgreSQL + pgvector
├── tests/                         ← 453 tests, all green
├── docker-compose.yml             ← CPU stack, port 8503
├── docker-compose.gpu.yml         ← GPU override
├── setup.sh                       ← One-command VPS deploy
├── requirements.txt
├── .env.example
├── README.md
└── LICENSE                        ← Apache 2.0
```

---

## Tech Stack

### Backend (hezcast-engine — built)
- **FastAPI** + Pydantic v2 — API server, port 8503
- **Celery** + Redis — async task queue
- **PostgreSQL 16** + pgvector — database
- **FFmpeg** — video rendering
- **Piper TTS** — voice synthesis
- **faster-whisper** — transcription
- **CLIP** + FAISS — semantic clip search
- **MuseTalk** — avatar lip-sync (commercial layer)
- **Backblaze B2** — video archive storage
- **LemonSqueezy** — billing + subscriptions
- **Anthropic Claude Sonnet** — primary LLM
- **OpenAI GPT-4o** — fallback LLM
- **Ollama** — local LLM fallback
- **Sentry** + PostHog — observability
- **Docker** — containerization

### Frontend (hezcast-saas — Phase 10, in progress)
- **Next.js 15** + React 19
- **Tailwind CSS**
- **Clerk** — auth (free tier, 10K MAU)
- **Recharts** — analytics charts
- **Vercel** — deployment (free tier)
- **LemonSqueezy** — checkout buttons

---

## Brand Configuration

4 brands in `config/brands.json`:

| Brand | Persona | Tone | Hooks | Duration |
|-------|---------|------|-------|----------|
| GiftMode | Maya | emotional | 5 | 25s |
| Tinlance | Lloyd | authority | 3 | 30s |
| WebTemify | Dev | developer_energy | 4 | 22s |
| HezCast | Lloyd | founder_energy | 5 | 25s |

---

## Pipeline (7 stages)

```
POST /generate
  → generate_hooks_task      (script + 3-5 hook variants)
  → [user selects hook]
  → synthesize_voice_task    (Piper TTS → voice.wav)
  → select_clip_task         (CLIP+FAISS → background.mp4)
  → compose_video_task       (FFmpeg → final.mp4)
  → generate_subs_task       (Whisper → subtitles.ass)
  → qa_check_task            (7-point validation)
  → generate_thumbnails_task (3 branded variants)
  → generate_post_and_publish_task (bundle + Telegram)
```

---

## Pricing System

| Plan | Price | Credits | Brands |
|------|-------|---------|--------|
| Free | $0 | 3/mo | 1 |
| Starter | $19/mo | 15/mo | 1 |
| Pro | $49/mo | 60/mo | 5 |
| Agency | $149/mo | 300/mo | Unlimited |

1 credit = 1 video render. Credits roll over (30/60/never days by plan).

---

## API Endpoints (all live on port 8503)

```
GET  /health
GET  /brands
POST /generate
GET  /status/{job_id}
GET  /hooks/{job_id}
POST /hooks/{job_id}/select
POST /telegram/webhook
GET  /telegram/webhook/info
POST /telegram/webhook/register
POST /billing/webhook
POST /billing/topup
GET  /billing/balance
GET  /billing/plans
POST /onboarding/brand
GET  /onboarding/brands
GET  /onboarding/complete
```

---

## Environment Variables

See `.env.example` for full list. Key ones:

```bash
CLAUDE_API_KEY=          # Primary LLM
OPENAI_API_KEY=          # GPT-4o fallback
PEXELS_API_KEY=          # Stock video clips
TELEGRAM_BOT_TOKEN=      # Bot interface
TELEGRAM_CHAT_ID=        # Channel to publish to
LEMONSQUEEZY_WEBHOOK_SECRET=  # Billing webhooks
B2_KEY_ID=               # Backblaze B2 archive
DB_PASSWORD=             # PostgreSQL
DOMAIN=cast.tinlance.com # For webhook registration
```

---

## Deployment

- **VPS:** 185.252.232.253 (existing Tinlance VPS)
- **Port:** 8503 (alongside trading bot on 8502)
- **Setup:** `./setup.sh` — one command deploys everything
- **Domain:** `cast.tinlance.com` → points to VPS
- **SSL:** Let's Encrypt via certbot
- **Frontend:** Vercel (cast.tinlance.com after DNS update)

---

## Coding Conventions

### Python (backend)
- All modules have custom exceptions (e.g. `ScriptGenerationError`)
- TDD enforced — tests written before implementation
- Mock pattern: `patch.object(engine, '_method_name')` for external calls
- Fallback chains: Claude → GPT-4o → Ollama for all LLM calls
- Non-fatal tasks: thumbnail, subtitle, Telegram publish failures
  never block job completion
- Job store: `_jobs` dict in `api/routes/generate.py` (shared state)
- Everything logs with `logger.info/warning/error`

### TypeScript (frontend — Phase 10)
- Strict mode enabled
- API calls via `lib/api.ts` client
- Polling: `useEffect` + `setInterval` for active jobs only
- Auth: Clerk middleware protects `/dashboard` and `/admin`
- Admin route: only accessible to `chinaemerem` Clerk user

---

## Key Decisions Made

1. **Open-core model** — engine is Apache 2.0, SaaS layer is private
2. **Docker-first** — deploys anywhere, CPU or GPU
3. **Telegram-first mobile** — bot is the mobile interface, no native app needed
4. **LemonSqueezy** — already in Tinlance stack (GiftMode, KalevioAI)
5. **Backblaze B2** — already in Tinlance stack, S3-compatible
6. **Clerk** — already in Tinlance stack (KalevioAI)
7. **HezCast brand** — named after Daddy Hezekiah (spiritual father)
8. **Credits never expire on Agency** — key differentiator vs HeyGen
9. **URL-to-video** — pass any blog URL to /generate
10. **HezCast promotes itself** — HezCast is one of its own brands

---

## Phase 10 — What Needs Building

The full Next.js 15 app in `hezcast-saas/` repo:

```
hezcast-saas/
├── app/
│   ├── page.tsx                    ← Landing page
│   ├── pricing/page.tsx            ← Pricing page
│   ├── sign-in/[[...sign-in]]/     ← Clerk
│   ├── sign-up/[[...sign-up]]/     ← Clerk
│   ├── dashboard/
│   │   ├── layout.tsx              ← Auth-protected shell
│   │   ├── page.tsx                ← Generate (default)
│   │   ├── jobs/page.tsx
│   │   ├── analytics/page.tsx
│   │   ├── brands/page.tsx
│   │   ├── billing/page.tsx
│   │   └── settings/page.tsx
│   └── admin/
│       ├── layout.tsx              ← Admin-only guard
│       └── page.tsx
├── components/
├── lib/
│   ├── api.ts                      ← FastAPI client
│   └── auth.ts                     ← Clerk helpers
├── middleware.ts                   ← Clerk route protection
├── next.config.ts
├── tailwind.config.ts
└── package.json
```

**Deploy target:** Vercel → `cast.tinlance.com`

---

## DO NOT

- Do not change port 8503 (trading bot is on 8502)
- Do not remove any existing tests
- Do not commit `.env` files
- Do not commit voice model `.onnx` files
- Do not commit avatar photos from `config/personas/`
- Do not add new LLM dependencies without updating the fallback chain
- Do not use `Arial`, `Inter`, `Roboto` for UI fonts
- Do not use purple gradient on white for any UI

---

## Contact

**Chinaemerem Nwachukwu**
Founder, Tinlance Limited
GitHub: @LloydCoder | X: @lloydambition @lloydcoder
Email: nwachukwuchinaemerem8@gmail.com
