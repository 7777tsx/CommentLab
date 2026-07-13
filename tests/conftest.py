from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings
from models.schemas import PublisherProfile
from services.orchestrator import CommentLabOrchestrator


@pytest.fixture
def profile() -> PublisherProfile:
    return PublisherProfile(
        identity="知识类内容创作者",
        domain="人工智能与数码",
        follower_scale="中小体量",
        style="理性、直接、偶尔幽默",
        audience_relationship="长期关注者较多，粉丝信任度较高",
    )


@pytest.fixture
def orchestrator(tmp_path: Path) -> CommentLabOrchestrator:
    settings = Settings(demo_mode=True, database_path=tmp_path / "commentlab.db")
    return CommentLabOrchestrator(settings)

