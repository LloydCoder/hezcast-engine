"""
HezCast Engine — Semantic Clip Selector
Tinlance Limited | Apache 2.0

Zero-shot semantic video clip matching using CLIP + FAISS.

Pipeline:
  1. Embed script text → 512-dim CLIP vector
  2. Search FAISS index → top-K nearest clips
  3. Re-rank by duration fit → return best match

No labels needed. CLIP understands "birthday surprise" →
finds clips of people unwrapping gifts, celebrating, smiling.

In Docker: uses real CLIP model (openai/clip-vit-base-patch32)
In tests:  _encode_text and _search_faiss are mocked
"""

import json
import logging
import os
import numpy as np
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CLIP SELECTOR
# ─────────────────────────────────────────────

class ClipSelector:
    """
    Selects the most semantically relevant stock video clip
    for a given script using CLIP embeddings + FAISS search.

    Usage:
        selector = ClipSelector()
        best = selector.select_best(
            script="I forgot her birthday. GiftMode saved me.",
            brand="GiftMode",
            target_duration=25.0
        )
        # Returns: {"id": "pexels_123", "local_path": "...", "score": 0.87, ...}
    """

    # CLIP embedding dimension (ViT-B/32)
    EMBEDDING_DIM = 512

    # Duration tolerance: clips within this many seconds of target are preferred
    DURATION_TOLERANCE_SEC = 8.0

    # Per-brand emotion tags for clip library pre-filtering
    BRAND_EMOTION_TAGS = {
        "GiftMode": [
            "happy", "surprise", "gift", "family",
            "celebration", "joy", "birthday", "love"
        ],
        "Tinlance": [
            "technology", "security", "professional",
            "data", "cyber", "network", "monitor", "alert"
        ],
        "WebTemify": [
            "coding", "laptop", "startup", "website",
            "fast", "developer", "build", "design"
        ],
    }

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"

        with open(config_path) as f:
            self.brand_config = json.load(f)

        self.project_root = Path(__file__).parent.parent
        self.index_dir = self.project_root / "storage" / "clip_index"
        self.clips_dir = self.project_root / "storage" / "clips"

        # Lazy-loaded CLIP model and FAISS indices
        self._clip_model = None
        self._clip_processor = None
        self._faiss_indices = {}      # brand → FAISS index
        self._clip_libraries = {}     # brand → list of clip dicts

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def select_best(
        self,
        script: str,
        brand: str,
        target_duration: float = 25.0
    ) -> dict:
        """
        Find the single best clip for this script and brand.

        Re-ranks top-K results by duration proximity to target.
        Falls back to highest cosine similarity if no duration match.

        Args:
            script:          The full script text (used for embedding)
            brand:           Brand name for library + emotion filter
            target_duration: Target video duration in seconds

        Returns:
            dict: Best clip with keys: id, local_path, score, duration_sec, tags

        Raises:
            ValueError: If script is empty or brand is unknown
            ClipIndexError: If clip index is empty or unbuilt
        """
        self._validate_inputs(script, brand)

        candidates = self.search(text=script, brand=brand, top_k=5)

        if not candidates:
            raise ClipIndexError(
                f"No clips found for brand '{brand}'. "
                f"Run build_index(brand='{brand}') first."
            )

        # Re-rank: prefer clips within duration tolerance
        in_range = [
            c for c in candidates
            if abs(c["duration_sec"] - target_duration) <= self.DURATION_TOLERANCE_SEC
        ]

        if in_range:
            # Among duration-matched clips, pick highest score
            best = max(in_range, key=lambda c: c["score"])
        else:
            # No duration match — fall back to highest similarity
            best = candidates[0]

        logger.info(
            f"Clip selected | brand={brand} | id={best['id']} | "
            f"score={best['score']:.3f} | duration={best['duration_sec']}s"
        )
        return best

    def search(
        self,
        text: str,
        brand: str,
        top_k: int = 3
    ) -> list[dict]:
        """
        Search clip library for semantically similar clips.

        Args:
            text:   Query text (script or scene description)
            brand:  Brand name for library selection
            top_k:  Number of results to return

        Returns:
            List of clip dicts sorted by score descending,
            each with: id, local_path, score, duration_sec, tags

        Raises:
            ValueError: If text is empty, brand unknown, or top_k < 1
        """
        self._validate_search_inputs(text, brand, top_k)

        embedding = self.embed_text(text)
        results = self._search_faiss(embedding, brand, top_k)
        return sorted(results, key=lambda x: -x["score"])

    def embed_text(self, text: str) -> np.ndarray:
        """
        Encode text to a normalized 512-dim CLIP embedding.

        Args:
            text: Any natural language string

        Returns:
            np.ndarray of shape (512,), dtype float32, L2-normalized

        Raises:
            ValueError: If text is empty
        """
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")

        raw = self._encode_text(text)

        # L2 normalize for cosine similarity via dot product
        norm = np.linalg.norm(raw)
        if norm > 0:
            raw = raw / norm

        return raw.astype(np.float32)

    def build_index(self, brand: str) -> int:
        """
        Download clips and build FAISS index for a brand.

        Args:
            brand: Brand name to build index for

        Returns:
            Number of clips indexed

        Raises:
            ValueError: If brand is unknown
        """
        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )

        clips = self._download_clips(brand)
        self._build_faiss_index(brand, clips)
        self._clip_libraries[brand] = clips

        logger.info(f"Clip index built | brand={brand} | clips={len(clips)}")
        return len(clips)

    def get_emotion_tags(self, brand: str) -> list[str]:
        """
        Get the emotion/theme tags for a brand's clip library.

        Raises:
            ValueError: If brand is unknown
        """
        if brand not in self.BRAND_EMOTION_TAGS:
            available = list(self.BRAND_EMOTION_TAGS.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available: {available}"
            )
        return self.BRAND_EMOTION_TAGS[brand].copy()

    # ─────────────────────────────────────────
    # CLIP MODEL (mockable in tests)
    # ─────────────────────────────────────────

    def _encode_text(self, text: str) -> np.ndarray:
        """
        Encode text using CLIP model.
        Lazy-loads model on first call.
        In tests: this method is mocked.
        """
        if self._clip_model is None:
            self._load_clip_model()

        import torch
        inputs = self._clip_processor(
            text=[text],
            return_tensors="pt",
            padding=True,
            truncation=True
        )
        with torch.no_grad():
            features = self._clip_model.get_text_features(**inputs)

        return features[0].numpy().astype(np.float32)

    def _load_clip_model(self) -> None:
        """Load CLIP model — only called in production Docker environment"""
        try:
            from transformers import CLIPModel, CLIPProcessor
            model_name = "openai/clip-vit-base-patch32"
            logger.info(f"Loading CLIP model: {model_name}")
            self._clip_model = CLIPModel.from_pretrained(model_name)
            self._clip_processor = CLIPProcessor.from_pretrained(model_name)
            self._clip_model.eval()
            logger.info("CLIP model loaded")
        except ImportError:
            raise ClipIndexError(
                "transformers not installed. "
                "Run: pip install transformers torch"
            )

    # ─────────────────────────────────────────
    # FAISS INDEX (mockable in tests)
    # ─────────────────────────────────────────

    def _search_faiss(
        self,
        embedding: np.ndarray,
        brand: str,
        top_k: int
    ) -> list[dict]:
        """
        Search FAISS index for nearest neighbours.
        In tests: this method is mocked.

        Returns list of clip dicts with 'score' key added.
        """
        import faiss

        index_path = self.index_dir / f"{brand.lower()}.faiss"
        meta_path = self.index_dir / f"{brand.lower()}_meta.json"

        if not index_path.exists():
            raise ClipIndexError(
                f"No FAISS index found for brand '{brand}'. "
                f"Run build_index(brand='{brand}') first."
            )

        index = faiss.read_index(str(index_path))
        with open(meta_path) as f:
            clip_meta = json.load(f)

        query = embedding.reshape(1, -1)
        faiss.normalize_L2(query)

        distances, indices = index.search(query, min(top_k, index.ntotal))

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            clip = clip_meta[idx].copy()
            # Convert L2 distance to similarity score [0, 1]
            clip["score"] = float(max(0.0, min(1.0, (2 - dist) / 2)))
            results.append(clip)

        return results

    def _build_faiss_index(self, brand: str, clips: list[dict]) -> None:
        """Build and persist FAISS flat index for a brand's clip library"""
        try:
            import faiss
        except ImportError:
            raise ClipIndexError("faiss-cpu not installed. Run: pip install faiss-cpu")

        if not clips:
            raise ClipIndexError(f"No clips to index for brand '{brand}'")

        embeddings = np.array(
            [c["embedding"] for c in clips],
            dtype=np.float32
        )
        faiss.normalize_L2(embeddings)

        index = faiss.IndexFlatIP(self.EMBEDDING_DIM)  # Inner product = cosine on normalized vecs
        index.add(embeddings)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.index_dir / f"{brand.lower()}.faiss"))

        # Save metadata (everything except embedding arrays)
        meta = [{k: v for k, v in c.items() if k != "embedding"} for c in clips]
        with open(self.index_dir / f"{brand.lower()}_meta.json", 'w') as f:
            json.dump(meta, f, indent=2)

        logger.info(f"FAISS index built | brand={brand} | clips={len(clips)}")

    def _download_clips(self, brand: str) -> list[dict]:
        """
        Download and cache top clips from Pexels for a brand.
        Uses brand emotion tags as search queries.
        In tests: this method is mocked.
        """
        pexels_key = os.getenv("PEXELS_API_KEY")
        if not pexels_key:
            raise ClipIndexError(
                "PEXELS_API_KEY not set. Cannot download clip library."
            )

        import requests

        emotion_tags = self.get_emotion_tags(brand)
        clips = []
        seen_ids = set()

        for tag in emotion_tags[:4]:  # Top 4 tags, 10 clips each = up to 40 clips
            try:
                resp = requests.get(
                    "https://api.pexels.com/videos/search",
                    headers={"Authorization": pexels_key},
                    params={"query": tag, "per_page": 10, "orientation": "portrait"},
                    timeout=15
                )
                resp.raise_for_status()
                data = resp.json()

                for video in data.get("videos", []):
                    vid_id = f"pexels_{video['id']}"
                    if vid_id in seen_ids:
                        continue
                    seen_ids.add(vid_id)

                    # Pick best quality video file
                    files = sorted(
                        video.get("video_files", []),
                        key=lambda f: f.get("width", 0),
                        reverse=True
                    )
                    best_file = next(
                        (f for f in files if f.get("width", 0) >= 1080),
                        files[0] if files else None
                    )
                    if not best_file:
                        continue

                    # Download video
                    local_path = self._download_video(
                        url=best_file["link"],
                        dest=self.clips_dir / f"{vid_id}.mp4"
                    )
                    if not local_path:
                        continue

                    # Generate CLIP embedding from video thumbnail
                    embedding = self._embed_video_thumbnail(video, local_path)

                    clips.append({
                        "id": vid_id,
                        "local_path": str(local_path),
                        "pexels_url": best_file["link"],
                        "tags": [tag],
                        "emotion_tags": [tag],
                        "duration_sec": float(video.get("duration", 10)),
                        "width": best_file.get("width", 1080),
                        "height": best_file.get("height", 1920),
                        "embedding": embedding,
                    })

            except Exception as e:
                logger.warning(f"Pexels fetch failed for tag '{tag}': {e}")
                continue

        return clips

    def _download_video(self, url: str, dest: Path) -> Optional[Path]:
        """Download a video file to local storage"""
        import requests
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                return dest  # Already cached

            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return dest
        except Exception as e:
            logger.warning(f"Video download failed: {e}")
            return None

    def _embed_video_thumbnail(self, video_meta: dict, local_path: Path) -> np.ndarray:
        """
        Generate CLIP embedding for a video.
        Uses the video's image metadata if available, else random fallback.
        """
        try:
            # Use Pexels image URL for embedding
            image_url = video_meta.get("image", "")
            if image_url and self._clip_model:
                from PIL import Image
                import requests
                from io import BytesIO

                resp = requests.get(image_url, timeout=10)
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                import torch
                inputs = self._clip_processor(images=img, return_tensors="pt")
                with torch.no_grad():
                    features = self._clip_model.get_image_features(**inputs)
                return features[0].numpy().astype(np.float32)
        except Exception as e:
            logger.debug(f"Thumbnail embedding failed: {e}")

        # Fallback: random embedding (won't be semantically meaningful)
        return np.random.rand(self.EMBEDDING_DIM).astype(np.float32)

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    def _validate_inputs(self, script: str, brand: str) -> None:
        if not script or not script.strip():
            raise ValueError("script must be a non-empty string")
        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )

    def _validate_search_inputs(self, text: str, brand: str, top_k: int) -> None:
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")
        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1 (got {top_k})")


# ─────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────

class ClipIndexError(Exception):
    """Raised when clip index is missing, empty, or unbuilt"""
    pass
