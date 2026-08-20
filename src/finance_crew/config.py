"""Runtime configuration and the (fictional) company spend policy.

Everything here is driven by environment variables so the same image runs
in local/demo mode with zero secrets, or in real CrewAI mode when a key is
supplied. No credentials are ever hard-coded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpendPolicy:
    """Fictional demo spend policy. Tune per organization."""

    auto_approve_limit: float = 200.0        # <= this and compliant -> auto approve
    human_review_limit: float = 2000.0       # > this -> always a human decides
    receipt_required_above: float = 50.0     # receipt mandatory above this amount
    category_limits: dict[str, float] = field(
        default_factory=lambda: {
            "travel": 1500.0,
            "meals": 100.0,
            "software": 1000.0,
            "equipment": 3000.0,
            "other": 500.0,
        }
    )

    def limit_for(self, category: str) -> float:
        return self.category_limits.get(category, self.category_limits["other"])


@dataclass
class Settings:
    """Which engine to run and how to reach the LLM (real mode only)."""

    engine: str = "auto"                  # "auto" | "local" | "langgraph" | "crewai"
    use_crewai: bool = False
    llm_provider: str = "openai"          # "openai" | "gemini"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    policy: SpendPolicy = field(default_factory=SpendPolicy)

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        key_env = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        use_crewai = os.getenv("USE_CREWAI", "false").lower() in {"1", "true", "yes"}
        return cls(
            engine=os.getenv("ENGINE", "auto").lower(),
            use_crewai=use_crewai,
            llm_provider=provider,
            model=os.getenv("LLM_MODEL", "gemini-1.5-flash" if provider == "gemini" else "gpt-4o-mini"),
            api_key=os.getenv(key_env),
        )

    @property
    def can_run_crewai(self) -> bool:
        """Real crew needs both the opt-in flag and a key present."""
        return self.use_crewai and bool(self.api_key)

    @property
    def active_engine(self) -> str:
        """The engine that will actually run, for display/health purposes."""
        if self.engine in {"local", "langgraph", "crewai"}:
            return self.engine
        return "crewai" if self.can_run_crewai else "local"
