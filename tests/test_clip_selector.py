"""
HezCast Engine — Semantic Clip Selector Tests
TDD Phase 2 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

CLIP + FAISS zero-shot semantic video search.
Matches script text to emotionally relevant stock clips.
"""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def clip_selector():
    from core.clip_selector import ClipSelector
    return ClipSelector()

@pytest.fixture
def sample_scripts():
    return {
        "GiftMode": "I forgot her birthday. GiftMode found the perfect gift in seconds.",
        "Tinlance": "Your server was breached. Nobody noticed for six hours.",
        "WebTemify": "I built a full landing page in under ten minutes."
    }

@pytest.fixture
def mock_clip_library():
    """Simulated clip library with embeddings"""
    np.random.seed(42)
    clips = []
    tags_pool = [
        ["happy", "celebration", "gift", "family"],
        ["surprise", "gift", "birthday", "joy"],
        ["technology", "security", "data", "professional"],
        ["cyber", "hacking", "alert", "monitor"],
        ["coding", "laptop", "startup", "fast"],
        ["website", "design", "developer", "build"],
        ["nature", "outdoors", "travel", "landscape"],
        ["food", "cooking", "restaurant", "meal"],
    ]
    for i, tags in enumerate(tags_pool):
        clips.append({
            "id": f"pexels_{1000 + i}",
            "local_path": f"/storage/clips/clip_{1000 + i}.mp4",
            "tags": tags,
            "emotion_tags": tags[:2],
            "duration_sec": 10.0 + i,
            "embedding": np.random.rand(512).astype(np.float32)
        })
    return clips

@pytest.fixture
def mock_embedder():
    """Mock CLIP text encoder returning deterministic embeddings"""
    def embed(text: str) -> np.ndarray:
        np.random.seed(hash(text) % 2**31)
        return np.random.rand(512).astype(np.float32)
    return embed


# ─────────────────────────────────────────────
# EMBEDDING TESTS
# ─────────────────────────────────────────────

class TestTextEmbedding:

    def test_embed_text_returns_numpy_array(self, clip_selector):
        """embed_text must return a numpy array"""
        with patch.object(clip_selector, '_load_clip_model'):
            with patch.object(clip_selector, '_encode_text') as mock_encode:
                mock_encode.return_value = np.random.rand(512).astype(np.float32)
                result = clip_selector.embed_text("gift for birthday")
        assert isinstance(result, np.ndarray)

    def test_embed_text_correct_dimension(self, clip_selector):
        """Embedding must be 512-dimensional (CLIP ViT-B/32)"""
        with patch.object(clip_selector, '_encode_text') as mock_encode:
            mock_encode.return_value = np.random.rand(512).astype(np.float32)
            result = clip_selector.embed_text("gift for birthday")
        assert result.shape == (512,)

    def test_embed_text_is_normalized(self, clip_selector):
        """Embedding must be L2-normalized for cosine similarity"""
        with patch.object(clip_selector, '_encode_text') as mock_encode:
            raw = np.random.rand(512).astype(np.float32)
            mock_encode.return_value = raw
            result = clip_selector.embed_text("gift for birthday")
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 0.01, f"Embedding not normalized: norm={norm}"

    def test_embed_text_float32_dtype(self, clip_selector):
        """Embedding must be float32 for FAISS compatibility"""
        with patch.object(clip_selector, '_encode_text') as mock_encode:
            mock_encode.return_value = np.random.rand(512).astype(np.float32)
            result = clip_selector.embed_text("gift for birthday")
        assert result.dtype == np.float32

    def test_empty_text_raises_value_error(self, clip_selector):
        """Empty text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            clip_selector.embed_text("")

    def test_different_texts_produce_different_embeddings(self, clip_selector):
        """Different texts must produce different embeddings"""
        with patch.object(clip_selector, '_encode_text') as mock_encode:
            mock_encode.side_effect = [
                np.random.rand(512).astype(np.float32),
                np.random.rand(512).astype(np.float32)
            ]
            emb1 = clip_selector.embed_text("birthday gift")
            emb2 = clip_selector.embed_text("cybersecurity breach")
        assert not np.allclose(emb1, emb2)


# ─────────────────────────────────────────────
# CLIP LIBRARY TESTS
# ─────────────────────────────────────────────

class TestClipLibrary:

    def test_build_index_returns_clip_count(self, clip_selector, mock_clip_library):
        """build_index must return the number of clips indexed"""
        with patch.object(clip_selector, '_download_clips', return_value=mock_clip_library):
            with patch.object(clip_selector, '_build_faiss_index'):
                count = clip_selector.build_index(brand="GiftMode")
        assert count == len(mock_clip_library)

    def test_build_index_requires_valid_brand(self, clip_selector):
        """build_index must raise ValueError for unknown brand"""
        with pytest.raises(ValueError, match="Unknown brand"):
            clip_selector.build_index(brand="FakeBrand")

    def test_clip_library_minimum_size(self, clip_selector, mock_clip_library):
        """Clip library must have at least 5 clips to be usable"""
        with patch.object(clip_selector, '_download_clips', return_value=mock_clip_library):
            with patch.object(clip_selector, '_build_faiss_index'):
                count = clip_selector.build_index(brand="GiftMode")
        assert count >= 5

    def test_each_clip_has_required_fields(self, clip_selector, mock_clip_library):
        """Every clip in library must have required fields"""
        required = ["id", "local_path", "tags", "duration_sec", "embedding"]
        for clip in mock_clip_library:
            for field in required:
                assert field in clip, f"Clip missing field: {field}"

    def test_clip_embeddings_are_correct_shape(self, clip_selector, mock_clip_library):
        """All clip embeddings must be 512-dimensional"""
        for clip in mock_clip_library:
            assert clip["embedding"].shape == (512,), \
                f"Clip {clip['id']} has wrong embedding shape: {clip['embedding'].shape}"


# ─────────────────────────────────────────────
# SEMANTIC SEARCH TESTS
# ─────────────────────────────────────────────

class TestSemanticSearch:

    def test_search_returns_list(self, clip_selector, mock_clip_library):
        """search() must return a list"""
        scored = [{**c, "score": 0.8} for c in mock_clip_library[:3]]
        with patch.object(clip_selector, '_encode_text') as mock_enc:
            mock_enc.return_value = np.random.rand(512).astype(np.float32)
            with patch.object(clip_selector, '_search_faiss') as mock_search:
                mock_search.return_value = scored
                results = clip_selector.search(
                    text="birthday gift surprise",
                    brand="GiftMode",
                    top_k=3
                )
        assert isinstance(results, list)

    def test_search_returns_requested_count(self, clip_selector, mock_clip_library):
        """search() must return exactly top_k results"""
        scored = [{**c, "score": 0.8} for c in mock_clip_library[:3]]
        with patch.object(clip_selector, '_encode_text') as mock_enc:
            mock_enc.return_value = np.random.rand(512).astype(np.float32)
            with patch.object(clip_selector, '_search_faiss') as mock_search:
                mock_search.return_value = scored
                results = clip_selector.search(
                    text="birthday gift",
                    brand="GiftMode",
                    top_k=3
                )
        assert len(results) == 3

    def test_search_result_has_required_fields(self, clip_selector, mock_clip_library):
        """Each result must have id, local_path, score, duration_sec"""
        required = ["id", "local_path", "score", "duration_sec"]
        with patch.object(clip_selector, '_encode_text') as mock_enc:
            mock_enc.return_value = np.random.rand(512).astype(np.float32)
            with patch.object(clip_selector, '_search_faiss') as mock_search:
                enriched = [{**c, "score": 0.9 - i * 0.1} for i, c in enumerate(mock_clip_library[:3])]
                mock_search.return_value = enriched
                results = clip_selector.search(
                    text="birthday gift",
                    brand="GiftMode",
                    top_k=3
                )
        for result in results:
            for field in required:
                assert field in result, f"Result missing field: {field}"

    def test_results_sorted_by_score_descending(self, clip_selector, mock_clip_library):
        """Results must be sorted by similarity score, highest first"""
        with patch.object(clip_selector, '_encode_text') as mock_enc:
            mock_enc.return_value = np.random.rand(512).astype(np.float32)
            with patch.object(clip_selector, '_search_faiss') as mock_search:
                enriched = [
                    {**mock_clip_library[0], "score": 0.45},
                    {**mock_clip_library[1], "score": 0.92},
                    {**mock_clip_library[2], "score": 0.71},
                ]
                mock_search.return_value = sorted(enriched, key=lambda x: -x["score"])
                results = clip_selector.search(
                    text="birthday gift",
                    brand="GiftMode",
                    top_k=3
                )
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scores_are_between_0_and_1(self, clip_selector, mock_clip_library):
        """Similarity scores must be in [0, 1] range"""
        with patch.object(clip_selector, '_encode_text') as mock_enc:
            mock_enc.return_value = np.random.rand(512).astype(np.float32)
            with patch.object(clip_selector, '_search_faiss') as mock_search:
                enriched = [{**c, "score": 0.7 + i * 0.05} for i, c in enumerate(mock_clip_library[:3])]
                mock_search.return_value = enriched
                results = clip_selector.search(
                    text="birthday gift",
                    brand="GiftMode",
                    top_k=3
                )
        for result in results:
            assert 0.0 <= result["score"] <= 1.0

    def test_search_empty_text_raises_value_error(self, clip_selector):
        """Empty search text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            clip_selector.search(text="", brand="GiftMode", top_k=3)

    def test_search_invalid_brand_raises_value_error(self, clip_selector):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            clip_selector.search(text="some text", brand="FakeBrand", top_k=3)

    def test_top_k_zero_raises_value_error(self, clip_selector):
        """top_k=0 must raise ValueError"""
        with pytest.raises(ValueError, match="top_k"):
            clip_selector.search(text="birthday gift", brand="GiftMode", top_k=0)


# ─────────────────────────────────────────────
# BEST CLIP SELECTION TESTS
# ─────────────────────────────────────────────

class TestBestClipSelection:

    def test_select_best_returns_single_clip(self, clip_selector, mock_clip_library):
        """select_best must return exactly one clip dict"""
        with patch.object(clip_selector, 'search') as mock_search:
            mock_search.return_value = [
                {**mock_clip_library[0], "score": 0.92},
                {**mock_clip_library[1], "score": 0.78},
                {**mock_clip_library[2], "score": 0.61},
            ]
            result = clip_selector.select_best(
                script="birthday gift forgotten panic",
                brand="GiftMode",
                target_duration=25.0
            )
        assert isinstance(result, dict)
        assert "local_path" in result

    def test_select_best_prefers_matching_duration(self, clip_selector, mock_clip_library):
        """select_best should prefer clips close to target duration"""
        clips_with_scores = [
            {**mock_clip_library[0], "score": 0.85, "duration_sec": 8.0},   # too short
            {**mock_clip_library[1], "score": 0.82, "duration_sec": 25.0},  # perfect
            {**mock_clip_library[2], "score": 0.80, "duration_sec": 60.0},  # too long
        ]
        with patch.object(clip_selector, 'search', return_value=clips_with_scores):
            result = clip_selector.select_best(
                script="birthday gift",
                brand="GiftMode",
                target_duration=25.0
            )
        # Should pick the clip closest to target duration
        assert result["duration_sec"] == 25.0

    def test_select_best_falls_back_to_top_score(self, clip_selector, mock_clip_library):
        """select_best falls back to highest score when no duration match"""
        clips = [
            {**mock_clip_library[0], "score": 0.95, "duration_sec": 5.0},
            {**mock_clip_library[1], "score": 0.70, "duration_sec": 6.0},
        ]
        with patch.object(clip_selector, 'search', return_value=clips):
            result = clip_selector.select_best(
                script="test",
                brand="GiftMode",
                target_duration=30.0
            )
        assert result["score"] == 0.95

    def test_select_best_empty_text_raises(self, clip_selector):
        """Empty script text must raise ValueError"""
        with pytest.raises(ValueError, match="script"):
            clip_selector.select_best(script="", brand="GiftMode", target_duration=25.0)

    def test_select_best_invalid_brand_raises(self, clip_selector):
        """Unknown brand raises ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            clip_selector.select_best(
                script="test text",
                brand="FakeBrand",
                target_duration=25.0
            )


# ─────────────────────────────────────────────
# BRAND EMOTION TAG TESTS
# ─────────────────────────────────────────────

class TestBrandEmotionTags:

    def test_get_emotion_tags_for_all_brands(self, clip_selector):
        """All brands must have emotion tags defined"""
        for brand in ["GiftMode", "Tinlance", "WebTemify"]:
            tags = clip_selector.get_emotion_tags(brand)
            assert isinstance(tags, list)
            assert len(tags) >= 3

    def test_giftmode_has_emotional_tags(self, clip_selector):
        """GiftMode emotion tags must reflect consumer emotional themes"""
        tags = clip_selector.get_emotion_tags("GiftMode")
        emotional = {"happy", "gift", "family", "celebration", "surprise", "joy"}
        assert any(t in emotional for t in tags)

    def test_tinlance_has_tech_tags(self, clip_selector):
        """Tinlance emotion tags must reflect tech/security themes"""
        tags = clip_selector.get_emotion_tags("Tinlance")
        tech = {"technology", "security", "cyber", "data", "professional"}
        assert any(t in tech for t in tags)

    def test_webtemify_has_dev_tags(self, clip_selector):
        """WebTemify emotion tags must reflect dev/startup themes"""
        tags = clip_selector.get_emotion_tags("WebTemify")
        dev = {"coding", "laptop", "startup", "website", "fast", "developer"}
        assert any(t in dev for t in tags)

    def test_unknown_brand_raises_value_error(self, clip_selector):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            clip_selector.get_emotion_tags("FakeBrand")
