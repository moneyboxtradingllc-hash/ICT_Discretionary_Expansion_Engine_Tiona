"""DEPLOY-1 — Cloneable multi-instance architecture.

`src/` is the SHARED CORE (one codebase, one DNA). This package adds the
deployment layer that lets that single core run as many INDEPENDENT instances —
each with its own memory, vector store, journal, logs, state, account, broker,
and risk profile. Same code, separate state, separate learning.

Principle: shared code · separate state · separate memory · separate execution ·
separate learning. Bot A must never accidentally see Bot B's memory or trades.
"""
