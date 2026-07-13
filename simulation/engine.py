from __future__ import annotations

import random

from chains.comment_chain import CommentChain
from models.schemas import (
    AudiencePlan,
    Comment,
    CommentAction,
    ContentAnalysis,
    PublisherProfile,
    SimulationConfig,
    SimulationMetrics,
    SimulationResult,
    TraceEvent,
)
from simulation.heat import simulate_lurker_likes, update_reply_counts


class SimulationEngine:
    def __init__(self, comment_chain: CommentChain):
        self.comment_chain = comment_chain

    def run(
        self,
        config: SimulationConfig,
        profile: PublisherProfile,
        audience: AudiencePlan,
        analysis: ContentAnalysis | None = None,
    ) -> SimulationResult:
        audience = audience.normalized()
        comments: list[Comment] = []
        trace: list[TraceEvent] = []
        roster = self._select_personas(audience, 10, config.seed, 0)
        seen_personas: set[str] = set()
        for round_no in range(1, config.rounds + 1):
            count = config.activation_counts[round_no - 1]
            selected = self._select_round_personas(
                roster, seen_personas, count, config.seed, round_no
            )
            seen_personas.update(persona.persona_id for persona in selected)
            visible = sorted(comments, key=lambda item: item.hot_score, reverse=True)[:5]
            batch = self.comment_chain.run_round(
                post_text=config.post_text,
                profile=profile,
                personas=selected,
                visible_comments=visible,
                round_no=round_no,
                version=config.version,
                analysis=analysis,
            )
            created = self._apply_actions(
                batch.actions,
                comments,
                selected,
                round_no,
                config.version,
            )
            trace.append(
                TraceEvent(
                    round_no=round_no,
                    event_type="agent_actions",
                    detail=f"激活{len(selected)}个Persona，新增{created}条评论或回复。",
                )
            )
            simulate_lurker_likes(
                comments,
                audience.personas,
                config.lurker_count,
                config.seed,
                round_no,
            )
            trace.append(
                TraceEvent(
                    round_no=round_no,
                    event_type="heat_update",
                    detail=f"{config.lurker_count}个规则化潜水用户完成点赞，评论重新按热度排序。",
                )
            )

        comments.sort(key=lambda item: (-item.hot_score, item.comment_id))
        return SimulationResult(
            config=config,
            audience=audience,
            comments=comments,
            metrics=self._metrics(comments),
            trace=trace,
        )

    @staticmethod
    def _select_personas(
        audience: AudiencePlan, count: int, seed: int, round_no: int
    ) -> list:
        rng = random.Random(seed + round_no * 7919)
        pool = [persona for persona in audience.personas if persona.active and persona.weight > 0]
        selected = []
        target_count = min(count, len(pool))
        while pool and len(selected) < target_count:
            weights = [max(persona.weight, 1e-8) for persona in pool]
            chosen = rng.choices(pool, weights=weights, k=1)[0]
            selected.append(chosen)
            pool.remove(chosen)
        return selected

    @staticmethod
    def _select_round_personas(
        roster: list,
        seen: set[str],
        count: int,
        seed: int,
        round_no: int,
    ) -> list:
        rng = random.Random(seed + round_no * 104729)
        unseen = [persona for persona in roster if persona.persona_id not in seen]
        seen_pool = [persona for persona in roster if persona.persona_id in seen]
        rng.shuffle(unseen)
        rng.shuffle(seen_pool)
        selected = unseen[:count]
        if len(selected) < count:
            selected.extend(seen_pool[: count - len(selected)])
        return selected

    @staticmethod
    def _apply_actions(
        actions: list[CommentAction],
        comments: list[Comment],
        selected: list,
        round_no: int,
        version: str,
    ) -> int:
        valid_personas = {persona.persona_id: persona for persona in selected}
        existing = {comment.comment_id: comment for comment in comments}
        created = 0
        for index, action in enumerate(actions):
            persona = valid_personas.get(action.persona_id)
            if persona is None:
                continue
            if action.action == "like":
                target = existing.get(action.target_comment_id or "")
                if target is not None:
                    target.likes += 1
                continue
            if action.action == "ignore":
                continue
            parent_id = action.target_comment_id if action.action == "reply" else None
            if parent_id not in existing:
                parent_id = None
            if not action.text:
                continue
            comment_id = f"{version}-r{round_no}-c{index + 1:02d}"
            comment = Comment(
                comment_id=comment_id,
                persona_id=persona.persona_id,
                persona_label=persona.label,
                parent_id=parent_id,
                round_no=round_no,
                text=action.text,
                stance=action.stance,
                emotion=action.emotion,
                emotion_intensity=action.emotion_intensity,
                controversy=action.controversy,
                misunderstanding=action.misunderstanding,
                off_topic=action.off_topic,
                evidence_span=action.evidence_span,
                reaction_type=action.reaction_type,
            )
            comments.append(comment)
            existing[comment_id] = comment
            created += 1
        update_reply_counts(comments)
        return created

    @staticmethod
    def _metrics(comments: list[Comment]) -> SimulationMetrics:
        if not comments:
            return SimulationMetrics(
                misunderstanding_ratio=0,
                negative_ratio=0,
                conflict_reply_count=0,
                off_topic_ratio=0,
            )
        by_id = {comment.comment_id: comment for comment in comments}
        negative_emotions = {"愤怒", "失望", "焦虑", "不信任", "被忽视", "嘲讽", "警惕"}
        negative_count = sum(
            comment.stance == "oppose" or comment.emotion in negative_emotions
            for comment in comments
        )
        conflict = 0
        for comment in comments:
            parent = by_id.get(comment.parent_id or "")
            if parent and (
                comment.controversy >= 0.6
                or {comment.stance, parent.stance} == {"support", "oppose"}
            ):
                conflict += 1
        size = len(comments)
        return SimulationMetrics(
            misunderstanding_ratio=round(sum(c.misunderstanding for c in comments) / size, 3),
            negative_ratio=round(negative_count / size, 3),
            conflict_reply_count=conflict,
            off_topic_ratio=round(sum(c.off_topic for c in comments) / size, 3),
        )
