"""HezCast Engine — Brands Route"""

import json
from pathlib import Path
from fastapi import APIRouter
from api.schemas import BrandResponse

router = APIRouter(tags=["Brands"])

def _load_brands():
    config_path = Path(__file__).parent.parent.parent / "config" / "brands.json"
    with open(config_path) as f:
        return json.load(f)

@router.get("/brands", response_model=list[BrandResponse])
def list_brands():
    """List all configured brands with their profiles"""
    brands = _load_brands()
    return [
        BrandResponse(
            name=name,
            tone=cfg["tone"],
            style=cfg["style"],
            audience=cfg["audience"],
            persona_name=cfg["persona_name"],
            hook_variants=cfg["hook_variants"],
            video_duration_target=cfg["video_duration_target"],
            subtitle_color=cfg["subtitle_color"],
        )
        for name, cfg in brands.items()
    ]
