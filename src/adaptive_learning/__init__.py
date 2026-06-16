"""Adaptive Learning — Phase 1A.

Scar-tissue recorder ONLY. Writes resolved closed-trade / resolved-intent
outcomes into the EXISTING ai_retrieval vector store so the Brain can later
recall "what have I seen that resembles this?". This package does NOT modify
confidence, execution, risk, or Brain prompting — recording only.
"""
