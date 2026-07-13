from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from models.schemas import HistoryItem, ProjectResult


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
