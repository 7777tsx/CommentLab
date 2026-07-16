from __future__ import annotations

from config import Settings, settings as default_settings
from chains import (
    AudienceChain,
    CommentChain,
    ComparisonChain,
    ContentAnalysisChain,
    PreparationChain,
    RewriteChain,
    RiskChain,
)
from models.schemas import (
    AudiencePlan,
    PreparedProject,
    ProjectResult,
    PublisherProfile,
    SimulationConfig,
    WebResearchResult,
)
from services.database import Database
from services.llm_client import ModelGateway
from services.web_research import WebResearchService
from simulation.engine import SimulationEngine


class CommentLabOrchestrator:
    def __init__(self, app_settings: Settings | None = None):
        self.settings = app_settings or default_settings
        self.database = Database(self.settings.database_path)
        self.gateway = ModelGateway(self.settings, self.database)
        self.content_chain = ContentAnalysisChain(self.gateway)
        self.audience_chain = AudienceChain(self.gateway)
        self.preparation_chain = PreparationChain(
            self.gateway, self.content_chain, self.audience_chain
        )
        self.comment_chain = CommentChain(self.gateway)
        self.risk_chain = RiskChain(self.gateway)
        self.rewrite_chain = RewriteChain(self.gateway)
        self.comparison_chain = ComparisonChain(self.gateway)
        self.simulation_engine = SimulationEngine(self.comment_chain)
        self.web_research = WebResearchService(self.settings)

    @property
    def demo_mode(self) -> bool:
        return self.gateway.demo_mode

    def prepare(
        self,
        post_text: str,
        profile: PublisherProfile,
        *,
        search_background: bool = False,
        event_hint: str = "",
    ) -> PreparedProject:
        post_text = SimulationConfig(post_text=post_text).post_text
        background_research = (
            self.web_research.run(post_text, event_hint)
            if search_background
            else None
        )
        background_context = self._shared_background(background_research)
        analysis, audience = self.preparation_chain.run(
            post_text,
            profile,
            background_context=background_context,
        )
        return PreparedProject(
            post_text=post_text,
            publisher_profile=profile,
            analysis=analysis,
            audience=audience,
            background_research=background_research,
        )

    def complete(
        self,
        prepared: PreparedProject,
        audience: AudiencePlan | None = None,
        seed: int = 42,
    ) -> ProjectResult:
        final_audience = (audience or prepared.audience).normalized()
        background_context = self._shared_background(prepared.background_research)
        before_config = SimulationConfig(
            post_text=prepared.post_text,
            version="before",
            seed=seed,
            lurker_count=50,
            rounds=3,
            activation_counts=[7, 4, 3],
        )
        simulation_before = self.simulation_engine.run(
            before_config,
            prepared.publisher_profile,
            final_audience,
            prepared.analysis,
            background_context=background_context,
        )
        risk_before = self.risk_chain.run(
            prepared.post_text,
            prepared.analysis,
            simulation_before,
            background_context=background_context,
        )
        if self._should_skip_rewrite(risk_before):
            rewrite = self.rewrite_chain.keep_original(
                prepared.post_text,
                "原文已经是低风险，本轮不强制改写，避免引入新的误解空间。",
            )
            analysis_after = prepared.analysis
            simulation_after = simulation_before
            risk_after = risk_before
        else:
            rewrite = self.rewrite_chain.run(
                prepared.post_text,
                prepared.publisher_profile,
                risk_before,
                background_context=background_context,
            )
            analysis_after = self.content_chain.run(
                rewrite.rewritten_post,
                prepared.publisher_profile,
                background_context=background_context,
            )
            after_config = before_config.model_copy(
                update={"post_text": rewrite.rewritten_post, "version": "after"}
            )
            simulation_after = self.simulation_engine.run(
                after_config,
                prepared.publisher_profile,
                final_audience,
                analysis_after,
                background_context=background_context,
            )
            risk_after = self.risk_chain.run(
                rewrite.rewritten_post,
                analysis_after,
                simulation_after,
                background_context=background_context,
            )
            if not self._rewrite_improved(risk_before, risk_after):
                rewrite = self.rewrite_chain.keep_original(
                    prepared.post_text,
                    "候选改写未能降低风险，本轮保留原文，建议人工继续微调高风险片段。",
                )
                analysis_after = prepared.analysis
                simulation_after = simulation_before
                risk_after = risk_before
        comparison = self.comparison_chain.run(
            simulation_before,
            simulation_after,
            risk_before,
            risk_after,
            background_context=background_context,
        )
        result = ProjectResult(
            project_id=prepared.project_id,
            post_text=prepared.post_text,
            publisher_profile=prepared.publisher_profile,
            analysis_before=prepared.analysis,
            audience=final_audience,
            simulation_before=simulation_before,
            risk_before=risk_before,
            rewrite=rewrite,
            analysis_after=analysis_after,
            simulation_after=simulation_after,
            risk_after=risk_after,
            comparison=comparison,
            background_research=prepared.background_research,
        )
        self.database.save_project(result)
        return result

    def recompare_with_rewrite(
        self,
        result: ProjectResult,
        rewritten_post: str,
        seed: int = 42,
    ) -> ProjectResult:
        """Recompute only the edited rewrite side while preserving original results."""
        rewritten_post = SimulationConfig(post_text=rewritten_post).post_text
        if rewritten_post == result.rewrite.rewritten_post:
            return result

        background_context = self._shared_background(result.background_research)
        rewrite = result.rewrite.model_copy(
            update={
                "rewritten_post": rewritten_post,
                "preserved_elements": [],
                "repaired_risks": [],
                "repair_checks": [],
                "explanation": "用户已在系统建议稿基础上完成编辑，本页结果按确认后的文案重新计算。",
            }
        )
        if rewritten_post == result.post_text:
            analysis_after = result.analysis_before
            simulation_after = result.simulation_before
            risk_after = result.risk_before
        else:
            analysis_after = self.content_chain.run(
                rewritten_post,
                result.publisher_profile,
                background_context=background_context,
            )
            after_config = result.simulation_before.config.model_copy(
                update={
                    "post_text": rewritten_post,
                    "version": "after",
                    "seed": seed,
                }
            )
            simulation_after = self.simulation_engine.run(
                after_config,
                result.publisher_profile,
                result.audience,
                analysis_after,
                background_context=background_context,
            )
            risk_after = self.risk_chain.run(
                rewritten_post,
                analysis_after,
                simulation_after,
                background_context=background_context,
            )
        comparison = self.comparison_chain.run(
            result.simulation_before,
            simulation_after,
            result.risk_before,
            risk_after,
            background_context=background_context,
        )
        updated = result.model_copy(
            update={
                "rewrite": rewrite,
                "analysis_after": analysis_after,
                "simulation_after": simulation_after,
                "risk_after": risk_after,
                "comparison": comparison,
            }
        )
        self.database.save_project(updated)
        return updated

    @staticmethod
    def _should_skip_rewrite(risk_before) -> bool:
        # The display band is intentionally sensitive; only truly minimal risk
        # skips rewriting so borderline-low posts can still receive suggestions.
        return risk_before.final_score < 2.0

    @staticmethod
    def _rewrite_improved(risk_before, risk_after) -> bool:
        return risk_after.final_score < risk_before.final_score

    @staticmethod
    def _shared_background(
        research: WebResearchResult | None,
    ) -> dict | None:
        """Build one validated fact card shared by every downstream agent."""
        if research is None or not research.succeeded:
            return None
        context = {
            "event_name": research.event_name,
            "conclusion": research.conclusion or research.summary,
            "claims": [
                {"text": claim.text, "status": claim.status}
                for claim in research.claims[:3]
            ],
            "uncertainties": research.uncertainties[:1],
        }
        if not context["conclusion"] and not context["claims"]:
            return None
        return context
