from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from config import settings
from models.schemas import AudiencePlan, ProjectResult, PublisherProfile
from services.orchestrator import CommentLabOrchestrator


ROOT = Path(__file__).resolve().parent


st.set_page_config(page_title="CommentLab", page_icon="CL", layout="wide")
st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 1.4rem;}
    h1, h2, h3 {letter-spacing: 0;}
    section[data-testid="stSidebar"] {
        background:linear-gradient(180deg, #082a52 0%, #061f3d 100%);
        border-right:1px solid rgba(255,255,255,.12);
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] h4,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        color:#f4f8ff !important;
    }
    section[data-testid="stSidebar"] hr {border-color:rgba(255,255,255,.22);}
    section[data-testid="stSidebar"] [data-testid="stAlert"] {
        background:rgba(83,155,232,.20); border:1px solid rgba(169,211,255,.24);
    }
    section[data-testid="stSidebar"] [data-testid="stAlert"] * {color:#f4f8ff !important;}
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
        background:#1d5f9e !important; border:1px solid #78afe2 !important;
        color:#ffffff !important; box-shadow:0 2px 8px rgba(0,0,0,.14);
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button * {
        color:#ffffff !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
        background:#2877ba !important; border-color:#b8dcff !important;
        color:#ffffff !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active {
        background:#154b7c !important; border-color:#d5eaff !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button:disabled {
        background:#496985 !important; border-color:#718ba3 !important;
        color:#dce8f3 !important; opacity:.72;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background:#ffffff; border-color:rgba(255,255,255,.48);
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] * {color:#14243a !important;}
    section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button,
    [data-testid="stSidebarCollapsedControl"] button {color:#f4f8ff !important;}
    section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg,
    [data-testid="stSidebarCollapsedControl"] svg {fill:#f4f8ff !important; stroke:#f4f8ff !important;}
    [data-testid="stSidebarCollapsedControl"] {
        background:#082a52; border-radius:0 0 0.55rem 0; padding:0.18rem;
    }
    div[data-testid="stMetric"] {border-left: 3px solid #e6543b; padding-left: 0.8rem;}
    .comment-meta {
        display:flex; align-items:center; justify-content:space-between; gap:0.65rem;
        color:#68717d; font-size:0.82rem; margin-bottom:0.32rem;
    }
    .comment-context {min-width:0;}
    .comment-stats {display:inline-flex; align-items:center; gap:0.85rem; flex:0 0 auto;}
    .comment-stat {display:inline-flex; align-items:center; gap:0.28rem; font-weight:700; line-height:1;}
    .comment-stat svg {width:1rem; height:1rem; fill:currentColor; flex:0 0 auto;}
    .comment-text {font-size:0.98rem; line-height:1.65;}
    .comment-tree {margin-top:0.6rem;}
    .comment-node {position:relative; margin:0 0 0.75rem 0;}
    .comment-card {
        border:1px solid rgba(128,128,128,.28); border-radius:0.65rem;
        padding:0.72rem 0.85rem; background:rgba(128,128,128,.045);
    }
    .comment-children {
        margin:0.65rem 0 0 1.25rem; padding-left:1rem;
        border-left:2px solid rgba(128,128,128,.28);
    }
    .comment-children > .comment-node::before {
        content:""; position:absolute; left:-1rem; top:1.3rem;
        width:0.75rem; border-top:2px solid rgba(128,128,128,.28);
    }
    .disclaimer {border-left:3px solid #d99b24; padding:0.55rem 0.8rem; background:#fff8e7; color:#514527;}
    .stage-stepper {
        display:grid; grid-template-columns:repeat(4, minmax(0, 1fr));
        margin:0.4rem 0 1.5rem; padding:0 0.25rem;
    }
    .stage-item {position:relative; text-align:center; min-width:0;}
    .stage-item:not(:last-child)::after {
        content:""; position:absolute; z-index:0; top:1rem;
        left:calc(50% + 1.25rem); right:calc(-50% + 1.25rem);
        height:3px; border-radius:3px; background:rgba(112,128,148,.28);
    }
    .stage-item.done:not(:last-child)::after {background:#3184c5;}
    .stage-dot {
        position:relative; z-index:1; display:flex; align-items:center; justify-content:center;
        width:2rem; height:2rem; margin:0 auto 0.42rem; border-radius:50%;
        border:2px solid rgba(112,128,148,.45); background:var(--background-color);
        color:inherit; font-size:0.82rem; font-weight:750;
    }
    .stage-item.done .stage-dot {background:#3184c5; border-color:#3184c5; color:#fff;}
    .stage-item.current .stage-dot {
        background:#e6543b; border-color:#e6543b; color:#fff;
        box-shadow:0 0 0 5px rgba(230,84,59,.16);
    }
    .stage-label {font-size:0.84rem; line-height:1.25; opacity:.62; white-space:nowrap;}
    .stage-item.done .stage-label {opacity:.82;}
    .stage-item.current .stage-label {opacity:1; font-weight:750;}
    .comparison-post {
        min-height:4.6rem; margin:0.35rem 0 0.6rem; padding:0.85rem 1rem;
        border-left:4px solid #3184c5; border-radius:0.35rem;
        background:#f5f7fa; color:#111827 !important;
        font-size:1rem; line-height:1.7; white-space:pre-wrap;
    }
    .risk-fragment {
        position:relative; display:inline; padding:0.04rem 0.12rem;
        border-bottom:2px solid #d97706; border-radius:0.18rem;
        background:#fff0b8; color:#111827 !important; font-weight:650;
        cursor:help; outline:none;
    }
    .risk-fragment:focus {box-shadow:0 0 0 3px rgba(49,132,197,.28);}
    .risk-tooltip {
        visibility:hidden; opacity:0; pointer-events:none;
        position:absolute; z-index:1000; left:50%; top:calc(100% + 0.65rem);
        width:min(30rem, 82vw); max-height:68vh; overflow-y:auto; padding:0.95rem 1rem;
        transform:translate(-50%, -0.35rem); transition:opacity .16s ease, transform .16s ease;
        border:1px solid #31516f; border-radius:0.65rem;
        background:#0b2038; color:#f5f8fc !important;
        box-shadow:0 10px 26px rgba(0,0,0,.28);
        font-size:1rem; font-weight:400; line-height:1.62; white-space:normal;
    }
    .risk-tooltip::after {
        content:""; position:absolute; left:50%; bottom:100%; transform:translateX(-50%);
        border:0.42rem solid transparent; border-bottom-color:#0b2038;
    }
    .risk-fragment:hover .risk-tooltip,
    .risk-fragment:focus .risk-tooltip {
        visibility:visible; opacity:1; transform:translate(-50%, 0);
    }
    .risk-tooltip-title {display:block; margin-bottom:0.42rem; color:#b9ddff !important; font-size:1.08rem; font-weight:750;}
    .risk-tooltip-reason {
        display:block;
        margin-bottom:0.48rem; padding-bottom:0.45rem;
        border-bottom:1px solid rgba(255,255,255,.18); color:#dbe8f5 !important;
    }
    .risk-tooltip-chain + .risk-tooltip-chain {
        margin-top:0.7rem; padding-top:0.7rem; border-top:1px solid rgba(255,255,255,.18);
    }
    .risk-tooltip-chain, .risk-tooltip-node {display:block; color:#ffffff !important;}
    .risk-tooltip-node {font-size:1rem; line-height:1.62;}
    .risk-tooltip-arrow {
        display:block; padding:0.14rem 0; color:#78baf0 !important;
        font-size:1.18rem; line-height:1.05; text-align:center; font-weight:850;
    }
    /* Streamlit temporarily disables form controls while a long task runs.
       Keep the retained input panel legible while the submit button shows progress. */
    div[data-testid="stForm"] [disabled],
    div[data-testid="stForm"] [aria-disabled="true"] {opacity:1 !important;}
    div[data-testid="stForm"] input:disabled,
    div[data-testid="stForm"] textarea:disabled {
        color:inherit !important; -webkit-text-fill-color:inherit !important;
    }
    @media (max-width: 900px) {
        .comment-children {margin-left:0.65rem; padding-left:0.75rem;}
        .comment-meta {align-items:flex-start; flex-direction:column; gap:0.35rem;}
        .stage-label {font-size:0.74rem; white-space:normal;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_orchestrator() -> CommentLabOrchestrator:
    return CommentLabOrchestrator(settings)


@st.cache_data
def load_demo_cases() -> list[dict]:
    return json.loads((ROOT / "data" / "demo_cases.json").read_text(encoding="utf-8"))


def apply_demo_case() -> None:
    selected = st.session_state.get("case_selector", "自定义")
    case = next((item for item in load_demo_cases() if item["name"] == selected), None)
    if case is None:
        return
    st.session_state.input_post = case["post_text"]
    st.session_state.input_identity = case["identity"]
    st.session_state.input_domain = case["domain"]
    st.session_state.input_follower_scale = case["follower_scale"]
    st.session_state.input_style = case["style"]
    st.session_state.input_audience_relationship = case["audience_relationship"]


def reset_flow() -> None:
    for key in ("prepared", "result", "stage", "edited_rewrite", "rewrite_project_id"):
        st.session_state.pop(key, None)
    st.session_state.stage = 1


def scroll_to_top_on_stage_change() -> None:
    current_stage = st.session_state.stage
    if st.session_state.get("rendered_stage") == current_stage:
        return
    st.session_state.rendered_stage = current_stage
    components.html(
        """
        <script>
        window.parent.scrollTo({top: 0, left: 0, behavior: "instant"});
        </script>
        """,
        height=0,
    )


def render_stage_stepper(current_stage: int) -> None:
    labels = ["输入内容", "确认受众", "原文结果", "改写对比"]
    items = []
    for index, label in enumerate(labels, 1):
        state = "done" if index < current_stage else "current" if index == current_stage else "upcoming"
        marker = "✓" if index < current_stage else str(index)
        items.append(
            f'<div class="stage-item {state}">'
            f'<div class="stage-dot">{marker}</div>'
            f'<div class="stage-label">{escape(label)}</div>'
            '</div>'
        )
    st.markdown(f'<div class="stage-stepper">{"".join(items)}</div>', unsafe_allow_html=True)


def risk_banner(level: str, title: str) -> None:
    message = f"{title}：{level}风险"
    if level == "高":
        st.error(message)
    elif level == "中":
        st.warning(message)
    else:
        st.success(message)


def render_comments(comments) -> None:
    if not comments:
        st.info("本轮没有生成可显示的评论。")
        return

    by_id = {comment.comment_id: comment for comment in comments}
    children: dict[str, list] = {}
    roots = []
    for comment in comments:
        if comment.parent_id and comment.parent_id in by_id:
            children.setdefault(comment.parent_id, []).append(comment)
        else:
            roots.append(comment)

    def render_node(comment, ancestry: set[str]) -> str:
        if comment.comment_id in ancestry:
            return ""
        ancestry = ancestry | {comment.comment_id}
        replies = children.get(comment.comment_id, [])
        reply_label = "回复" if comment.parent_id else "评论"
        nested = "".join(render_node(reply, ancestry) for reply in replies)
        nested_html = f'<div class="comment-children">{nested}</div>' if nested else ""
        return (
            '<div class="comment-node">'
            '<div class="comment-card">'
            '<div class="comment-meta">'
            f'<span class="comment-context">{reply_label} · {escape(comment.persona_label)} · '
            f'第{comment.round_no}轮</span>'
            '<span class="comment-stats">'
            f'<span class="comment-stat" aria-label="赞 {comment.likes}">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21.35 10.55 20.03C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09A6.02 6.02 0 0 1 16.5 3C19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54Z"/></svg>'
            f'<span>{comment.likes}</span></span>'
            f'<span class="comment-stat" aria-label="回复 {comment.reply_count}">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5.2 3.2c-.78.48-1.8-.08-1.8-1V6a2 2 0 0 1 2-2Z"/></svg>'
            f'<span>{comment.reply_count}</span></span>'
            '</span></div>'
            f'<div class="comment-text">{escape(comment.text)}</div>'
            '</div>'
            f'{nested_html}</div>'
        )

    tree_html = "".join(render_node(comment, set()) for comment in roots)
    st.markdown(f'<div class="comment-tree">{tree_html}</div>', unsafe_allow_html=True)


def render_modification_directions(report) -> None:
    st.subheader("修改方向")
    for index, direction in enumerate(clean_modification_directions(report.modification_directions), 1):
        st.write(f"{index}. {direction}")


def clean_modification_directions(directions) -> list[str]:
    """Rejoin model output that was split into incomplete list fragments."""
    cleaned = []
    for raw in directions:
        text = re.sub(r"^\s*(?:[-*•]+|\d+[.、)])\s*", "", str(raw)).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            cleaned.append(text)

    results: list[str] = []
    pending = ""
    for text in cleaned:
        if pending:
            if pending[-1:] in "，。！？；：、" or text[:1] in "，。！？；：、":
                pending += text
            elif re.search(r"[A-Za-z0-9]$", pending) and re.match(r"[A-Za-z0-9]", text):
                pending += " " + text
            else:
                pending += text
            if re.search(r"[。！？；]$", pending):
                results.append(pending)
                pending = ""
            continue

        is_fragment_start = bool(
            re.search(r"(?:将|把|改为|调整为|避免将|建议|例如|即|从而|以|：)$", text)
            or ("：" in text and not re.search(r"[。！？；]$", text))
        )
        if is_fragment_start:
            pending = text
        elif text in {"改为", "调整为", "建议", "例如"}:
            pending = text
        elif text[:1] in "，。！？；：、" and results:
            results[-1] += text
        else:
            results.append(text)

    if pending and pending not in {"改为", "调整为", "建议", "例如"}:
        results.append(pending)

    return [item for item in results if len(item.strip("，。！？；：、 ")) >= 4]


def render_background_research(research) -> None:
    if research is None:
        return
    st.subheader("联网核对结论")
    if research.status == "completed":
        if research.event_name:
            st.caption(f"可能指代：{research.event_name}")
        conclusion = research.conclusion or research.summary
        st.info(conclusion)
        for claim in research.claims[:3]:
            links = []
            for source_index in claim.source_indexes:
                if 0 <= source_index < len(research.sources):
                    source = research.sources[source_index]
                    links.append(f"[来源{source_index + 1}]({source.url})")
            reference_text = " ".join(links)
            st.markdown(f"- {claim.text} {reference_text}".rstrip())
        if research.uncertainties:
            st.caption("仍需注意：" + "；".join(research.uncertainties[:1]))
        if research.sources:
            with st.expander(f"查看参考来源（{len(research.sources)}）"):
                for index, source in enumerate(research.sources, 1):
                    source_name = source.title or source.domain or source.url
                    st.markdown(f"**{index}. [{source_name}]({source.url})**")
                    shown_keys = {
                        source_display_key(source_name),
                        source_display_key(source.url),
                    }
                    details = []
                    if source.domain and source_display_key(source.domain) not in shown_keys:
                        details.append(source.domain)
                        shown_keys.add(source_display_key(source.domain))
                    if source.published_at:
                        details.append(source.published_at)
                    if details:
                        st.caption(" · ".join(details))
                    if source.excerpt and source_display_key(source.excerpt) not in shown_keys:
                        st.write(source.excerpt)
        else:
            st.caption("当前接口没有返回可展示的来源链接。")
    elif research.status == "failed":
        st.warning(research.summary)
    else:
        st.caption(research.summary)
    if research.status == "completed":
        st.caption("该精简背景会统一提供给所有评论 Agent，并通过模拟评论间接影响风险判断。")
    else:
        st.caption("未获得可靠联网背景，本次评论模拟不会注入未经核实的信息。")


def source_display_key(value: str | None) -> str:
    """Normalize source fields so a URL/domain returned in several fields is shown once."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = re.sub(r"^https?://", "", text)
    return text.rstrip("/")


def association_key(value: str) -> str:
    return re.sub(r"[\s“”\"'《》]", "", str(value or ""))


def complete_chain_steps(steps) -> list[str]:
    """Merge connector-only legacy/model fragments into complete display nodes."""
    connector_end = re.compile(
        r"(?:将|把|被|为|成为|改为|视为|认为|接受|导致|引发|使|让|令|由于|因为|意味着)$"
    )
    transition_start = re.compile(r"^(?:进而|从而|最终|随后|继而|因此|于是)")
    continuation_start = re.compile(r"^[，。、；：的地得而与及并或]")
    merged = []
    pending = ""
    for raw in steps:
        step = re.sub(r"\s+", " ", str(raw)).strip()
        if not step:
            continue
        if pending:
            if transition_start.match(step) and len(pending) >= 10:
                merged.append(pending)
                pending = step if connector_end.search(step) else ""
                if not pending:
                    merged.append(step)
            else:
                pending += step
                if re.search(r"[。！？；]$", pending):
                    merged.append(pending)
                    pending = ""
            continue
        if connector_end.search(step):
            pending = step
        elif continuation_start.match(step) and merged:
            merged[-1] += step
        else:
            merged.append(step)
    if pending:
        merged.append(pending)
    return merged


def render_annotated_post(post_text: str, report) -> None:
    """Highlight all literal risk spans and reveal reasons plus anchored chains."""
    reasons = {
        association_key(span.text): span.reason
        for span in report.risky_spans
        if span.text.strip()
    }
    grouped_chains = {}
    for chain in report.misunderstanding_chains:
        if not chain.source_span or chain.source_span not in post_text:
            continue
        grouped_chains.setdefault(chain.source_span, []).append(chain)

    candidates = []
    highlight_spans = dict(grouped_chains)
    for span in report.risky_spans:
        if span.text and span.text in post_text:
            highlight_spans.setdefault(span.text, [])
    for source_span, related_chains in highlight_spans.items():
        reason = reasons.get(association_key(source_span), "该片段是下列误解链的原文起点")
        for match in re.finditer(re.escape(source_span), post_text):
            candidates.append((match.start(), match.end(), reason, related_chains))

    selected = []
    for item in sorted(candidates, key=lambda value: (value[0], -(value[1] - value[0]))):
        if selected and item[0] < selected[-1][1]:
            previous = selected[-1]
            merged_chains = list(previous[3])
            for chain in item[3]:
                if chain not in merged_chains:
                    merged_chains.append(chain)
            merged_reason = previous[2]
            if item[2] != previous[2]:
                merged_reason = f"{previous[2]}；{item[2]}"
            selected[-1] = (
                previous[0],
                max(previous[1], item[1]),
                merged_reason,
                merged_chains,
            )
            continue
        selected.append(item)

    if not selected:
        st.markdown(
            f'<div class="comparison-post">{escape(post_text)}</div>',
            unsafe_allow_html=True,
        )
        return

    parts = []
    cursor = 0
    for start, end, reason, related_chains in selected:
        parts.append(escape(post_text[cursor:start]))
        chain_items = []
        for chain in related_chains:
            nodes = [chain.source_span, *complete_chain_steps(chain.steps)]
            node_items = [
                f'<span class="risk-tooltip-node">{escape(node.strip())}</span>'
                for node in nodes
                if node.strip()
            ]
            chain_items.append(
                '<span class="risk-tooltip-chain">'
                + '<span class="risk-tooltip-arrow">↓</span>'.join(node_items)
                + '</span>'
            )
        tooltip_title = "相关误解链" if chain_items else "风险提示"
        tooltip = (
            '<span class="risk-tooltip">'
            f'<span class="risk-tooltip-title">{tooltip_title}</span>'
            f'<span class="risk-tooltip-reason">{escape(reason)}</span>'
            f'{"".join(chain_items)}'
            '</span>'
        )
        parts.append(
            '<span class="risk-fragment" tabindex="0" aria-label="查看风险说明">'
            f'{escape(post_text[start:end])}{tooltip}'
            '</span>'
        )
        cursor = end
    parts.append(escape(post_text[cursor:]))
    st.markdown(
        f'<div class="comparison-post">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


def render_analysis_column(
    title: str,
    post_text: str,
    report,
    comments,
    comment_title: str,
    explanation: str | None = None,
    include_comments: bool = True,
) -> None:
    st.subheader(title)
    render_annotated_post(post_text, report)
    if explanation:
        st.caption(explanation)
    risk_banner(report.overall_level, "综合判断")
    st.write(report.summary)
    render_modification_directions(report)
    if include_comments:
        st.markdown(f"#### {comment_title}")
        render_comments(comments)


def render_comparison(result: ProjectResult) -> None:
    before, after = result.risk_before, result.risk_after
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("修改前", f"{before.overall_level}风险")
    c2.metric("修改后", f"{after.overall_level}风险")
    c3.markdown(f"**结论**  \n{result.comparison.conclusion}")
    metrics = result.comparison
    cols = st.columns(4)
    cols[0].metric("误解评论变化", f"{metrics.misunderstanding_change:+.1%}")
    cols[1].metric("负面评论变化", f"{metrics.negative_change:+.1%}")
    cols[2].metric("对立回复变化", f"{metrics.conflict_change:+d}")
    cols[3].metric("跑题评论变化", f"{metrics.off_topic_change:+.1%}")
    st.caption("以上是同一批模拟受众下的压力测试差值，不代表真实平台概率。")


orchestrator = get_orchestrator()
st.session_state.setdefault("stage", 1)

with st.sidebar:
    st.markdown("### CommentLab")
    st.caption("发布前沟通风险模拟")
    mode_label = "DEMO_MODE（无密钥可运行）" if orchestrator.demo_mode else f"实时模型：{settings.model}"
    st.info(mode_label)
    if orchestrator.gateway.last_error:
        st.warning("最近一次模型调用失败，系统已使用本地降级结果完成流程。")
    if st.button("新建测试", use_container_width=True):
        reset_flow()
        st.rerun()
    st.divider()
    st.markdown("#### 历史结果")
    history = orchestrator.database.list_projects()
    if history:
        selected_id = st.selectbox(
            "选择历史项目",
            options=[item.project_id for item in history],
            format_func=lambda project_id: next(
                f"{item.created_at[:16]} · {item.post_text[:18]}"
                for item in history
                if item.project_id == project_id
            ),
            label_visibility="collapsed",
        )
        if st.button("打开历史结果", use_container_width=True):
            loaded = orchestrator.database.load_project(selected_id)
            if loaded:
                st.session_state.result = loaded
                st.session_state.stage = 4
                st.rerun()
    else:
        st.caption("还没有保存的测试。")

st.title("CommentLab")
st.markdown("#### 面向个人创作者的发布前沟通测试 Agent")
st.markdown(
    '<div class="disclaimer">本系统用于发布前沟通风险压力测试，模拟结果不代表真实舆情预测。</div>',
    unsafe_allow_html=True,
)
st.write("")

render_stage_stepper(st.session_state.stage)
scroll_to_top_on_stage_change()

if st.session_state.stage == 1:
    cases = load_demo_cases()
    case_names = ["自定义"] + [case["name"] for case in cases]
    st.session_state.setdefault("input_post", "")
    st.session_state.setdefault("input_identity", "个人内容创作者")
    st.session_state.setdefault("input_domain", "日常分享")
    st.session_state.setdefault("input_follower_scale", "中小体量")
    st.session_state.setdefault("input_style", "理性、直接")
    st.session_state.setdefault("input_audience_relationship", "普通关注关系")
    st.selectbox(
        "课堂演示案例",
        case_names,
        key="case_selector",
        on_change=apply_demo_case,
    )
    input_panel = st.empty()
    with input_panel.container():
        with st.container(border=True, key="input_online_card"):
            st.markdown("#### 联网设置")
            online_toggle, online_note = st.columns([1, 2], vertical_alignment="center")
            with online_toggle:
                search_background = st.checkbox(
                    "联网核对公开事件背景",
                    value=True,
                    key="search_background_enabled",
                    help="开启后，系统会搜索帖子可能指代的公开事件，并向所有评论 Agent 提供相同的精简背景。",
                )
            with online_note:
                st.caption("开启后将自动联网核对，并让所有评论 Agent 共享同一份精简背景。")
            if search_background:
                event_hint = st.text_input(
                    "事件线索（可选）",
                    placeholder="例如：事件名称、人物、机构或大致时间",
                    help="帖子指代不明确时，补充线索可以减少搜索歧义。",
                )
            else:
                event_hint = ""
        with st.form("input_form", border=False):
            with st.container(border=True, key="input_post_card"):
                st.markdown("#### 帖子内容")
                post_text = st.text_area(
                    "准备发布的帖子",
                    key="input_post",
                    max_chars=500,
                    height=150,
                    help="仅支持500字以内中文短文本；暂不支持读取链接、图片、视频或历史内容。",
                )
                st.caption(f"当前 {len(post_text)} / 500 字")
            with st.container(border=True, key="input_profile_card"):
                st.markdown("#### 发布者画像")
                col1, col2, col3 = st.columns(3)
                identity = col1.text_input("身份", key="input_identity")
                domain = col2.text_input("内容领域", key="input_domain")
                follower_scale = col3.selectbox(
                    "粉丝规模",
                    ["小体量", "中小体量", "中等体量", "较大体量"],
                    key="input_follower_scale",
                )
                style = st.text_input("表达风格", key="input_style")
                audience_relationship = st.text_input("与受众关系", key="input_audience_relationship")
            submit_slot = st.empty()
            submitted = submit_slot.form_submit_button("分析内容并生成受众", type="primary")
    if submitted:
        try:
            profile = PublisherProfile(
                identity=identity,
                domain=domain,
                follower_scale=follower_scale,
                style=style,
                audience_relationship=audience_relationship,
            )
            work_message = (
                "内容分析、受众规划与事件背景研究正在工作..."
                if search_background
                else "内容分析与受众规划正在工作..."
            )
            submit_slot.empty()
            with submit_slot.container():
                with st.spinner(work_message):
                    st.session_state.prepared = orchestrator.prepare(
                        post_text,
                        profile,
                        search_background=search_background,
                        event_hint=event_hint,
                    )
            st.session_state.stage = 2
            st.rerun()
        except Exception as exc:
            st.error(f"无法开始分析：{exc}")

elif st.session_state.stage == 2:
    prepared = st.session_state.get("prepared")
    if prepared is None:
        reset_flow()
        st.rerun()
    if st.button("← 返回输入页", key="back_to_stage_1"):
        st.session_state.stage = 1
        st.rerun()
    st.subheader("内容初步分析")
    st.write(f"**核心表达：** {prepared.analysis.main_message}")
    if prepared.analysis.ambiguous_phrases:
        st.write("**可能模糊的表达：**")
        for issue in prepared.analysis.ambiguous_phrases:
            st.write(f"- “{issue.text}”：{issue.reason}")
    if prepared.analysis.missing_information:
        st.write("**可能缺失的信息：** " + "、".join(prepared.analysis.missing_information))
    if prepared.background_research is not None:
        st.divider()
        render_background_research(prepared.background_research)
    st.divider()
    st.subheader("确认模拟受众")
    st.caption("先调大类比例；需要时再展开修改具体Persona权重。系统会自动归一化。")
    with st.form("audience_form"):
        group_values = {}
        group_columns = st.columns(3)
        for index, (group, ratio) in enumerate(prepared.audience.group_ratios.items()):
            group_values[group] = group_columns[index % 3].slider(
                group, 0, 100, int(round(ratio * 100)), 5
            )
        persona_weights = {}
        with st.expander("高级：具体 Persona 权重"):
            for persona in prepared.audience.personas:
                if not persona.active:
                    st.caption(f"{persona.label}：由Python规则模拟，不参与发言权重")
                    continue
                persona_weights[persona.persona_id] = st.slider(
                    f"{persona.label} · {persona.description}",
                    0.0,
                    3.0,
                    float(min(3.0, persona.weight * 10)),
                    0.1,
                )
        start = st.form_submit_button("开始三轮模拟", type="primary")
    if start:
        try:
            personas = [persona.model_copy(deep=True) for persona in prepared.audience.personas]
            for persona in personas:
                if persona.persona_id in persona_weights:
                    persona.weight = persona_weights[persona.persona_id]
            audience = AudiencePlan(
                personas=[persona.model_dump(mode="python") for persona in personas],
                group_ratios={key: value / 100 for key, value in group_values.items()},
                rationale=prepared.audience.rationale,
            ).normalized()
            with st.spinner("全部背景知情的受众 Agent 正在进行原文与改写后三轮模拟..."):
                st.session_state.result = orchestrator.complete(prepared, audience=audience, seed=42)
            st.session_state.stage = 3
            st.rerun()
        except Exception as exc:
            st.error(f"模拟未完成：{exc}")

elif st.session_state.stage == 3:
    result: ProjectResult | None = st.session_state.get("result")
    if result is None:
        reset_flow()
        st.rerun()
    if st.button("← 返回受众确认", key="back_to_stage_2"):
        st.session_state.stage = 2
        st.rerun()
    st.header("原文结果与改写确认")
    if result.background_research is not None:
        render_background_research(result.background_research)
        st.divider()
    if st.session_state.get("rewrite_project_id") != result.project_id:
        st.session_state.edited_rewrite = result.rewrite.rewritten_post
        st.session_state.rewrite_project_id = result.project_id
    original_col, rewrite_col = st.columns([45, 55], gap="large")
    with original_col:
        render_analysis_column(
            "原文分析",
            result.post_text,
            result.risk_before,
            result.simulation_before.comments,
            "原文背景知情评论区",
            include_comments=False,
        )
    with rewrite_col:
        st.subheader("确认改写文案")
        st.caption(result.rewrite.explanation)
        edited_rewrite = st.text_area(
            "改写后的帖子",
            key="edited_rewrite",
            max_chars=500,
            height=220,
            help="可直接修改系统建议稿；确认后将按此版本重新计算改写侧结果。",
        )
        st.caption(f"当前 {len(edited_rewrite)} / 500 字")
        compare_slot = st.empty()
        compare_clicked = compare_slot.button(
            "查看改写与反事实对比",
            type="primary",
            use_container_width=True,
        )
        if compare_clicked:
            try:
                compare_slot.empty()
                with compare_slot.container():
                    with st.spinner("正在按确认后的改写文案重新计算分析、评论与对比..."):
                        st.session_state.result = orchestrator.recompare_with_rewrite(
                            result,
                            edited_rewrite,
                            seed=42,
                        )
                st.session_state.stage = 4
                st.rerun()
            except Exception as exc:
                st.error(f"改写稿对比未完成：{exc}")
    st.divider()
    st.subheader("原文背景知情评论区")
    render_comments(result.simulation_before.comments)

else:
    result: ProjectResult | None = st.session_state.get("result")
    if result is None:
        reset_flow()
        st.rerun()
    if st.button("← 返回原文结果", key="back_to_stage_3"):
        st.session_state.stage = 3
        st.rerun()
    st.header("改写与反事实对比")
    if result.background_research is not None:
        render_background_research(result.background_research)
        st.divider()
    before_col, after_col = st.columns([45, 55], gap="large")
    with before_col:
        render_analysis_column(
            "原文分析与评论",
            result.post_text,
            result.risk_before,
            result.simulation_before.comments,
            "原文背景知情评论区",
        )
    with after_col:
        render_analysis_column(
            "改写后分析与评论",
            result.rewrite.rewritten_post,
            result.risk_after,
            result.simulation_after.comments,
            "改写后背景知情评论区",
            explanation=result.rewrite.explanation,
        )
    st.divider()
    render_comparison(result)
    st.divider()
    st.subheader("仍需注意")
    for item in result.comparison.remaining_questions:
        st.write(f"- {item}")
    st.caption(f"同一受众配置验证：{'通过' if result.comparison.persona_consistency else '未通过'}")
