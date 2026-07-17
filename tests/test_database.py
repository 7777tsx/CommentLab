from __future__ import annotations


def test_cache_round_trip(orchestrator) -> None:
    database = orchestrator.database
    assert database.cache_get("missing") is None
    database.cache_set("key", "stage", '{"ok":true}')
    assert database.cache_get("key") == '{"ok":true}'


def test_project_crud_and_history(orchestrator, profile) -> None:
    prepared = orchestrator.prepare("最近会适当减少更新，大家不用多想。", profile)
    result = orchestrator.complete(prepared)
    loaded = orchestrator.database.load_project(result.project_id)
    assert loaded is not None
    assert loaded.model_dump() == result.model_dump()
    history = orchestrator.database.list_projects()
    assert history[0].project_id == result.project_id
    assert history[0].overall_risk_before == result.risk_before.overall_level


def test_publisher_memory_updates_independent_profiles(orchestrator, profile) -> None:
    database = orchestrator.database
    first = database.remember_publisher(
        publisher_id=None,
        name="账号A",
        profile=profile,
        post_text="最近会适当减少更新，大家不用多想。",
    )
    updated = database.remember_publisher(
        publisher_id=first.publisher_id,
        name="账号A",
        profile=profile,
        post_text="第二条内容。",
    )
    other = database.remember_publisher(
        publisher_id=None,
        name="账号B",
        profile=profile,
        post_text="另一位发布者的内容。",
    )

    assert updated.publisher_id == first.publisher_id
    assert updated.post_count == 2
    assert updated.recent_posts[0] == "第二条内容。"
    assert other.publisher_id != updated.publisher_id
    assert {memory.name for memory in database.list_publishers()} == {"账号A", "账号B"}
