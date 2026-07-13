from __future__ import annotations

from config import Settings, settings as default_settings
from chains import (
    AudienceChain,
    CommentChain,
    ComparisonChain,
    ContentAnalysisChain,
    RewriteChain,
    RiskChain,
)
from models.schemas import (
    AudiencePlan,
    PreparedProject,
    ProjectResult,
    PublisherProfile,
    SimulationConfig,
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
        analysis = self.content_chain.run(post_text, profile)
        audience = self.audience_chain.run(post_text, profile, analysis)
        background_research = (
            self.web_research.run(post_text, event_hint)
            if search_background
            else None
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
        before_config = SimulationConfig(
            post_text=prepared.post_text,
            version="before",
            seed=seed,
            lurker_count=50,
            rounds=3,
            activation_counts=[7, 4, 3],
        )
        simulation_before = self.simulation_engine.run(
            before_config, prepared.publisher_profile, final_audience, prepared.analysis
        )
        risk_before = self.risk_chain.run(
            prepared.post_text, prepared.analysis, simulation_before
        )
        rewrite = self.rewrite_chain.run(
            prepared.post_text, prepared.publisher_profile, risk_before
        )
        analysis_after = self.content_chain.run(
            rewrite.rewritten_post, prepared.publisher_profile
        )
        after_config = before_config.model_copy(
            update={"post_text": rewrite.rewritten_post, "version": "after"}
        )
        simulation_after = self.simulation_engine.run(
            after_config, prepared.publisher_profile, final_audience, analysis_after
        )
        risk_after = self.risk_chain.run(
            rewrite.rewritten_post, analysis_after, simulation_after
        )
        comparison = self.comparison_chain.run(
            simulation_before, simulation_after, risk_before, risk_after
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
