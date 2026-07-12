"""DEPLOY-1 Phase 3 — Instance Runtime Context.

`InstanceContext` is the single object that tells the whole runtime WHICH
instance is live and WHERE it may write. `activate()` exports the instance's
isolated paths into the per-subsystem environment variables that every stateful
module already resolves through (see data_paths.SUBSYSTEM_ENV). Because every
state dir is env-driven, activating an instance redirects ALL of its memory,
vector store, journal, logs, state, and news memory into its own folder — no
module may then write to shared paths.

Use as a context manager for clean activate/restore, or call activate()/
deactivate() explicitly. `current()` returns the active context (or None).
"""
from __future__ import annotations

import os
from typing import Optional

from deployment.instance_config import InstanceConfig

_ACTIVE: "Optional[InstanceContext]" = None

# Global memory lives OUTSIDE any instance (broad market lessons only, Phase 4).
GLOBAL_MEMORY_DIR = os.path.join("data", "global_memory")


class InstanceContext:
    def __init__(self, config: InstanceConfig):
        self.config = config
        self.instance_id = config.instance_id
        # resolved isolated directories for this instance
        self.paths = {
            "brain":              os.path.join(config.memory_path, "ai_brain"),
            "vector_store":       config.vector_store_path,
            "journal":            config.journal_path,
            "snapshots":          os.path.join(config.log_path, "live_snapshots"),
            "intent_archive":     os.path.join(config.memory_path, "intent_archive"),
            "activation_reports": os.path.join(config.log_path, "activation_reports"),
            "rule_governance":    os.path.join(config.memory_path, "rule_governance"),
            # "shadow" removed — shadow AI evaluator retired (TIER-2A 2026-07-10)
            "news_memory":        config.news_memory_path,
            "ops":                config.state_path,
        }
        self._saved_env: dict = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def ensure_dirs(self) -> None:
        for p in self.paths.values():
            os.makedirs(p, exist_ok=True)
        os.makedirs(GLOBAL_MEMORY_DIR, exist_ok=True)

    def env_map(self) -> dict:
        from deployment.data_paths import SUBSYSTEM_ENV
        return {SUBSYSTEM_ENV[k]: v for k, v in self.paths.items()
                if k in SUBSYSTEM_ENV}

    def activate(self, ensure_dirs: bool = True) -> "InstanceContext":
        """Export instance paths to env so all subsystems write in isolation."""
        global _ACTIVE
        if ensure_dirs:
            self.ensure_dirs()
        for var, val in self.env_map().items():
            self._saved_env[var] = os.environ.get(var)
            os.environ[var] = val
        # account/broker identity for adapters + risk knobs
        self._saved_env["BOT_INSTANCE_ID"] = os.environ.get("BOT_INSTANCE_ID")
        os.environ["BOT_INSTANCE_ID"] = self.instance_id
        _ACTIVE = self
        return self

    def deactivate(self) -> None:
        global _ACTIVE
        for var, prev in self._saved_env.items():
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev
        self._saved_env.clear()
        if _ACTIVE is self:
            _ACTIVE = None

    def __enter__(self):
        return self.activate()

    def __exit__(self, *exc):
        self.deactivate()
        return False

    # ── factories / accessors ──────────────────────────────────────────────────
    @classmethod
    def from_config_file(cls, path: str) -> "InstanceContext":
        return cls(InstanceConfig.load(path))

    @classmethod
    def for_instance(cls, instance_id: str,
                     instances_root: str = os.path.join("data", "instances")) -> "InstanceContext":
        return cls.from_config_file(
            os.path.join(instances_root, instance_id, "config.yaml"))


def current() -> "Optional[InstanceContext]":
    """The active instance context, or None when running single-instance/global."""
    return _ACTIVE
