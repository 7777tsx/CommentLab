from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.schemas import HistoryItem, ProjectResult, PublisherMemory, PublisherProfile


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    post_text TEXT NOT NULL,
    rewritten_post TEXT,
    publisher_profile_json TEXT NOT NULL,
    overall_risk_before TEXT,
    overall_risk_after TEXT,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publishers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    post_count INTEGER NOT NULL DEFAULT 0,
    profile_json TEXT NOT NULL,
    profile_summary TEXT NOT NULL,
    recent_posts_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS personas (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    persona_type TEXT NOT NULL,
    group_name TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    PRIMARY KEY (id, project_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    version TEXT NOT NULL,
    persona_id TEXT NOT NULL,
    parent_id TEXT,
    round_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    likes INTEGER NOT NULL,
    reply_count INTEGER NOT NULL,
    hot_score REAL NOT NULL,
    internal_labels_json TEXT NOT NULL,
    PRIMARY KEY (id, project_id, version)
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def cache_get(self, cache_key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM llm_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return None if row is None else str(row["response_json"])

    def cache_set(self, cache_key: str, stage: str, response_json: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO llm_cache(cache_key, stage, response_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                     stage=excluded.stage, response_json=excluded.response_json""",
                (cache_key, stage, response_json),
            )

    def list_publishers(self) -> list[PublisherMemory]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, name, created_at, updated_at, post_count, profile_json,
                          profile_summary, recent_posts_json
                   FROM publishers ORDER BY updated_at DESC, name ASC"""
            ).fetchall()
        return [self._with_project_posts(self._publisher_from_row(row)) for row in rows]

    def load_publisher(self, publisher_id: str) -> PublisherMemory | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, name, created_at, updated_at, post_count, profile_json,
                          profile_summary, recent_posts_json
                   FROM publishers WHERE id = ?""",
                (publisher_id,),
            ).fetchone()
        return None if row is None else self._with_project_posts(self._publisher_from_row(row))

    def remember_publisher(
        self,
        *,
        publisher_id: str | None,
        name: str,
        profile: PublisherProfile,
        post_text: str,
    ) -> PublisherMemory:
        normalized_name = " ".join(name.strip().split()) or profile.identity
        post_record = post_text.strip().replace("\n", " ")
        with self.connect() as connection:
            row = None
            if publisher_id:
                row = connection.execute(
                    """SELECT id, name, created_at, updated_at, post_count, profile_json,
                              profile_summary, recent_posts_json
                       FROM publishers WHERE id = ?""",
                    (publisher_id,),
                ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT id, name, created_at, updated_at, post_count, profile_json,
                              profile_summary, recent_posts_json
                       FROM publishers WHERE name = ?""",
                    (normalized_name,),
                ).fetchone()

            if row is None:
                memory_id = uuid4().hex
                recent_posts = [post_record] if post_record else []
                summary = self._profile_summary(profile, len(recent_posts), recent_posts)
                connection.execute(
                    """INSERT INTO publishers
                       (id, name, profile_json, profile_summary, recent_posts_json, post_count)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        memory_id,
                        normalized_name,
                        profile.model_dump_json(),
                        summary,
                        json.dumps(recent_posts, ensure_ascii=False),
                        len(recent_posts),
                    ),
                )
            else:
                memory_id = row["id"]
                recent_posts = json.loads(row["recent_posts_json"] or "[]")
                if post_record:
                    recent_posts = [post_record, *[p for p in recent_posts if p != post_record]][:5]
                post_count = int(row["post_count"]) + (1 if post_record else 0)
                summary = self._profile_summary(profile, post_count, recent_posts)
                connection.execute(
                    """UPDATE publishers
                       SET name = ?, updated_at = CURRENT_TIMESTAMP, post_count = ?,
                           profile_json = ?, profile_summary = ?, recent_posts_json = ?
                       WHERE id = ?""",
                    (
                        normalized_name,
                        post_count,
                        profile.model_dump_json(),
                        summary,
                        json.dumps(recent_posts, ensure_ascii=False),
                        memory_id,
                    ),
                )
        loaded = self.load_publisher(memory_id)
        if loaded is None:
            raise RuntimeError("发布者记忆保存失败")
        return loaded

    def save_project(self, result: ProjectResult) -> None:
        payload = result.model_dump_json()
        profile_json = result.publisher_profile.model_dump_json()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO projects
                   (id, created_at, post_text, rewritten_post, publisher_profile_json,
                    overall_risk_before, overall_risk_after, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.project_id,
                    result.created_at,
                    result.post_text,
                    result.rewrite.rewritten_post,
                    profile_json,
                    result.risk_before.overall_level,
                    result.risk_after.overall_level,
                    payload,
                ),
            )
            connection.execute("DELETE FROM personas WHERE project_id = ?", (result.project_id,))
            for persona in result.audience.personas:
                connection.execute(
                    "INSERT INTO personas VALUES (?, ?, ?, ?, ?)",
                    (
                        persona.persona_id,
                        result.project_id,
                        persona.label,
                        persona.group_name,
                        persona.model_dump_json(),
                    ),
                )
            connection.execute("DELETE FROM comments WHERE project_id = ?", (result.project_id,))
            for version, simulation in (
                ("before", result.simulation_before),
                ("after", result.simulation_after),
            ):
                for comment in simulation.comments:
                    labels = json.dumps(
                        {
                            "stance": comment.stance,
                            "emotion": comment.emotion,
                            "emotion_intensity": comment.emotion_intensity,
                            "controversy": comment.controversy,
                            "misunderstanding": comment.misunderstanding,
                            "off_topic": comment.off_topic,
                            "evidence_span": comment.evidence_span,
                            "reaction_type": comment.reaction_type,
                        },
                        ensure_ascii=False,
                    )
                    connection.execute(
                        """INSERT INTO comments VALUES
                           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            comment.comment_id,
                            result.project_id,
                            version,
                            comment.persona_id,
                            comment.parent_id,
                            comment.round_no,
                            comment.text,
                            comment.likes,
                            comment.reply_count,
                            comment.hot_score,
                            labels,
                        ),
                    )
            connection.execute("DELETE FROM reports WHERE project_id = ?", (result.project_id,))
            reports: list[tuple[str, str, Any]] = [
                (f"{result.project_id}-before", "before", result.risk_before),
                (f"{result.project_id}-after", "after", result.risk_after),
                (f"{result.project_id}-comparison", "comparison", result.comparison),
            ]
            for report_id, version, report in reports:
                connection.execute(
                    "INSERT INTO reports VALUES (?, ?, ?, ?)",
                    (report_id, result.project_id, version, report.model_dump_json()),
                )

    def load_project(self, project_id: str) -> ProjectResult | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            return None
        return ProjectResult.model_validate_json(row["result_json"])

    def list_projects(self, limit: int = 30) -> list[HistoryItem]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, created_at, post_text, overall_risk_before, overall_risk_after
                   FROM projects ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            HistoryItem(
                project_id=row["id"],
                created_at=row["created_at"],
                post_text=row["post_text"],
                overall_risk_before=row["overall_risk_before"],
                overall_risk_after=row["overall_risk_after"],
            )
            for row in rows
        ]

    @staticmethod
    def _profile_summary(
        profile: PublisherProfile, post_count: int, recent_posts: list[str]
    ) -> str:
        summary = (
            f"{profile.identity}，主要发布{profile.domain}内容，粉丝规模为{profile.follower_scale}，"
            f"常用表达风格是{profile.style}，与受众关系为{profile.audience_relationship}。"
            f"已累计记录 {post_count} 条发布内容。"
        )
        if recent_posts:
            summary += f" 最近内容：{recent_posts[0]}"
        return summary

    @staticmethod
    def _publisher_from_row(row: sqlite3.Row) -> PublisherMemory:
        return PublisherMemory(
            publisher_id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            post_count=row["post_count"],
            profile=PublisherProfile.model_validate_json(row["profile_json"]),
            profile_summary=row["profile_summary"],
            recent_posts=json.loads(row["recent_posts_json"] or "[]"),
        )

    def _with_project_posts(self, memory: PublisherMemory) -> PublisherMemory:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT result_json FROM projects ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        project_posts: list[str] = []
        for row in rows:
            try:
                payload = json.loads(row["result_json"])
            except json.JSONDecodeError:
                continue
            if payload.get("publisher_id") != memory.publisher_id:
                continue
            post_text = str(payload.get("post_text") or "").strip().replace("\n", " ")
            if post_text:
                project_posts.append(post_text)

        merged: list[str] = []
        for post in [*project_posts, *memory.recent_posts]:
            if any(existing == post or existing.startswith(post) or post.startswith(existing) for existing in merged):
                continue
            merged.append(post)
            if len(merged) >= 5:
                break
        return memory.model_copy(update={"recent_posts": merged})
