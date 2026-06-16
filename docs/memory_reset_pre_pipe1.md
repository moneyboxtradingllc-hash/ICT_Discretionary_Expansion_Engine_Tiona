# MEMORY-RESET — Archive Legacy Debug-Era Scars

**Date:** 2026-06-16
**Action:** archived the pre-PIPE-1 / pre-Vector-3 / pre-Adaptive-Friction memory
corpus and started a clean active memory era.

## What changed (filesystem only — no code logic touched)
- The active vector store `data/ai_retrieval/memory_store.jsonl` (667 records) was
  copied byte-for-byte (SHA256 verified) to
  `data/ai_retrieval/archive/memory_store_legacy_pre_pipe1_pre_vector3_debug_era.jsonl`.
- The active store was reset to **empty** (0 lines).
- A manifest was written to
  `data/ai_retrieval/archive/LEGACY_MEMORY_MANIFEST.md`.
- `.gitignore` now ignores `data/ai_retrieval/*` (runtime state) while keeping the
  folder via `.gitkeep`, matching the convention used for other `data/` dirs.

The archive `.jsonl` and the in-tree manifest are **not committed** (bulk runtime
data, git-ignored). This document is the tracked record of the reset.

## Why
The 667-record corpus was generated during the debugging era and is contaminated
for adaptive-learning purposes (pre-PIPE-1 evidence inversion; pre-Vector-3
scale-invariant displacement / PO3 flicker; structure-authority instability; AI
stop-sign era; 60-second thesis churn; replay/debug runs). Those embeddings encode
the exact bugs since fixed, so Adaptive Friction (2A) and Adaptive Interpretation
(2B) must not draw historical objections from them.

This also resolves the integration risk flagged in the ADAPTIVE-2A/2B forensic
audit: `retrieve_analogs()` reads the entire active store with no era/provenance
filter, so the only safe way to exclude the contaminated corpus was to remove it
from the active path.

## Post-reset state (verified)
- Active `memory_store.jsonl`: **0 lines**.
- Archive: **667 lines** (SHA256 `2bafb561…fce36`).
- `retrieve_analogs()` on the empty store returns `corpus_size=0, analogs=[]`, no error.
- Runtime scar collection remains wired: `scan_loop.py:1237 record_closed_trade_scar`.

## Going forward
The new active era is populated only by ADAPTIVE-1A.5 runtime scar collection from
real closed trades (`record_closed_trade_scar → write_outcome`). Tomorrow's first
closed trade becomes the **first clean, post-fix scar**.

To restore the legacy corpus if ever needed:
```
cp data/ai_retrieval/archive/memory_store_legacy_pre_pipe1_pre_vector3_debug_era.jsonl \
   data/ai_retrieval/memory_store.jsonl
```
