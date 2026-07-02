"""DEPLOY-1 Phase 2 — Instance Config model.

A single instance's full identity: who/what/where. Loaded from a per-instance
config.yaml. Defines account, broker, risk profile, isolated state paths, and
the behavioral-divergence knobs (Phase 11) that let clones learn separately.
Pure data + (de)serialization. Never executes, never connects.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import yaml

BROKERS = ("paper", "tradestation")
EXECUTION_MODES = ("paper", "shadow", "live")   # 'live' is reserved; DEPLOY-1 stays paper/shadow


@dataclass
class RiskProfile:
    max_daily_loss: float = 500.0
    max_trades_per_day: int = 2
    risk_per_trade: float = 500.0
    risk_label: str = "standard"


@dataclass
class DivergenceConfig:
    """Phase 11 — knobs that allow (never force) clones to diverge over time."""
    confidence_calibration: float = 1.0           # multiplier on Brain confidence
    tool_preference_weights: dict = field(default_factory=dict)
    playbook_preference_weights: dict = field(default_factory=dict)
    scan_cadence_seconds: int = 60
    session_preference: str = "rth"
    allowed_playbooks: Optional[list] = None       # None = all
    allowed_tools: Optional[list] = None           # None = all


@dataclass
class InstanceConfig:
    instance_id: str
    owner_name: str = ""
    broker: str = "paper"
    # DEPLOY-2A — explicit market-data provider. Empty = alpaca via
    # resolved_data_provider().
    data_provider: str = ""
    # DEPLOY-2C — execution runtime. Empty = alpaca_paper via
    # resolved_execution_provider().
    execution_provider: str = ""
    practice_only: bool = True          # refuse live/funded routing
    execution_enabled: bool = False     # safe default: observe, place no orders
    account_type: str = "paper"
    account_id: str = ""
    symbol: str = "QQQ"
    contract_size: int = 1
    session_windows: list = field(default_factory=lambda: ["09:30-16:00"])
    execution_mode: str = "paper"

    risk_profile: RiskProfile = field(default_factory=RiskProfile)
    divergence: DivergenceConfig = field(default_factory=DivergenceConfig)

    # Isolated state paths (relative to repo root unless absolute). Defaulted
    # from instance_id when omitted so a minimal config is still fully isolated.
    memory_path: str = ""
    vector_store_path: str = ""
    journal_path: str = ""
    log_path: str = ""
    state_path: str = ""
    news_memory_path: str = ""

    def __post_init__(self):
        base = os.path.join("data", "instances", self.instance_id)
        self.memory_path       = self.memory_path       or os.path.join(base, "memory")
        self.vector_store_path = self.vector_store_path or os.path.join(base, "vector_store")
        self.journal_path      = self.journal_path      or os.path.join(base, "journal")
        self.log_path          = self.log_path          or os.path.join(base, "logs")
        self.state_path        = self.state_path        or os.path.join(base, "state")
        self.news_memory_path  = self.news_memory_path  or os.path.join(base, "news_memory")

    # ── (de)serialization ────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: dict) -> "InstanceConfig":
        d = dict(d or {})
        rp = d.pop("risk_profile", {}) or {}
        dv = d.pop("divergence", {}) or {}
        # tolerate flat max_daily_loss / max_trades_per_day at top level
        for k in ("max_daily_loss", "max_trades_per_day"):
            if k in d and k not in rp:
                rp[k] = d.pop(k)
        known = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in known}
        d.setdefault("instance_id", "")   # templates omit it; the clone tool sets it
        cfg = cls(**d)
        cfg.risk_profile = RiskProfile(**{k: v for k, v in rp.items()
                                          if k in RiskProfile.__dataclass_fields__})
        cfg.divergence = DivergenceConfig(**{k: v for k, v in dv.items()
                                             if k in DivergenceConfig.__dataclass_fields__})
        cfg.__post_init__()
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str) -> "InstanceConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, sort_keys=False)

    def resolved_data_provider(self) -> str:
        """Explicit data_provider if set, else alpaca (the mainline feed)."""
        if self.data_provider:
            return self.data_provider.lower().strip()
        return "alpaca"

    def resolved_execution_provider(self) -> str:
        """Explicit execution_provider if set, else the Alpaca paper runtime."""
        if self.execution_provider:
            return self.execution_provider.lower().strip()
        return "alpaca_paper"

    def validate(self) -> list:
        """Return a list of problems (empty = valid). Never raises."""
        problems = []
        if not self.instance_id:
            problems.append("instance_id is required")
        if self.broker not in BROKERS:
            problems.append(f"broker must be one of {BROKERS}")
        if self.data_provider and self.data_provider.lower() != "alpaca":
            problems.append("data_provider must be one of ('', 'alpaca')")
        if self.execution_provider and self.execution_provider.lower() != "alpaca_paper":
            problems.append("execution_provider must be one of ('', 'alpaca_paper')")
        if self.execution_mode not in EXECUTION_MODES:
            problems.append(f"execution_mode must be one of {EXECUTION_MODES}")
        if self.execution_mode == "live":
            problems.append("execution_mode 'live' is not permitted in DEPLOY-1 (paper only)")
        return problems
