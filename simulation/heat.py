from __future__ import annotations

import random

from models.schemas import Comment, PersonaSpec


def calculate_hot_score(
    likes: int,
    reply_count: int,
    emotion_intensity: float,
    controversy: float,
    age_factor: float,
) -> float:
    if age_factor <= 0:
        raise ValueError("age_factor必须大于0")
    return round(
        (
            likes
            + 1.5 * reply_count
            + 2.0 * emotion_intensity
            + 1.5 * controversy
        )
        / age_factor,
        4,
    )


def update_reply_counts(comments: list[Comment]) -> None:
    by_id = {comment.comment_id: comment for comment in comments}
    for comment in comments:
        comment.reply_count = 0
    for comment in comments:
        if comment.parent_id in by_id:
            by_id[comment.parent_id].reply_count += 1


def simulate_lurker_likes(
    comments: list[Comment],
    personas: list[PersonaSpec],
    lurker_count: int,
    seed: int,
    current_round: int,
) -> None:
    if not comments or lurker_count <= 0:
        return
    rng = random.Random(seed + current_round * 1009)
    active = [persona for persona in personas if persona.active]
    stances = ["support", "oppose", "question", "neutral"]
    influence = {
        persona.persona_id: persona.influence for persona in active
    }
    for _ in range(lurker_count):
        preferred = rng.choice(stances)
        candidates: list[tuple[Comment, float]] = []
        for comment in comments:
            stance_fit = 1.0 if comment.stance == preferred else 0.35
            existing_heat = min(1.0, comment.likes / 15.0)
            emotion = comment.emotion_intensity
            brevity = max(0.0, 1.0 - abs(len(comment.text) - 24) / 40.0)
            propagation = 0.55 * emotion + 0.45 * comment.controversy
            persona_influence = influence.get(comment.persona_id, 0.5)
            probability = (
                0.22 * stance_fit
                + 0.18 * existing_heat
                + 0.17 * emotion
                + 0.14 * brevity
                + 0.17 * propagation
                + 0.12 * persona_influence
            )
            candidates.append((comment, probability))
        candidates.sort(key=lambda item: item[1], reverse=True)
        pool = candidates[: min(5, len(candidates))]
        chosen, probability = rng.choice(pool)
        if rng.random() < min(0.92, probability):
            chosen.likes += 1

    update_reply_counts(comments)
    for comment in comments:
        age_factor = 1.0 + 0.15 * max(0, current_round - comment.round_no)
        comment.hot_score = calculate_hot_score(
            comment.likes,
            comment.reply_count,
            comment.emotion_intensity,
            comment.controversy,
            age_factor,
        )

