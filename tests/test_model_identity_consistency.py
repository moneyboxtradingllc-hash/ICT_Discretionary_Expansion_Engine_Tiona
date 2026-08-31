"""MODEL-IDENTITY-CONSISTENCY-1 — one production model, one owner.

2026-08-20. Two modules declared `PRODUCTION_MODEL`, with OPPOSITE values:

    ai_brain/production_model.py    PRODUCTION_MODEL = "gpt-5.6-luna"
    ai_brain/model_pricing.py       PRODUCTION_MODEL = "gpt-5.6-terra"

The 2026-08-06 Terra migration set the second one. The operator's 2026-08-19
ruling moved production to Luna and updated the first. Nothing updated the copy,
and nothing could notice, because no invariant bound them.

The damage was not to live authorship -- the execution lane reads the canonical
owner, so Luna really did author and the runner's real gate really did pass.
The damage was to everything that trusted the stale copy:

  * `cost_from_usage` defaulted to Terra's rate. Terra is 12.5x Luna on both
    input and output, so every default-model cost estimate was 12.5x high.
  * `test_topstepx_execution_runner` imports both names. The second import
    shadowed the first, so its fixtures built theses "authored by" Terra, the
    runner correctly refused them as foreign, and 44 tests of the execution
    path -- protection, OCO, flatten, final invariant -- went silently dark.

Forty-four red tests are loud. Forty-four tests that fail for a reason nobody
attributes are not. They sat inside a baseline everyone had stopped reading.

    A SECOND COPY OF AN IDENTITY IS NOT A CONVENIENCE. IT IS A FUTURE LIE.

`model_pricing` no longer owns a model identity. It imports the canonical one,
and these tests exist so it can never quietly own one again.
"""
from __future__ import annotations

import ast
import inspect
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain import model_pricing as MP          # noqa: E402
from ai_brain import production_model as PM       # noqa: E402


class TestThereIsOneIdentity:
    def test_pricing_uses_the_canonical_production_model(self):
        assert MP.PRODUCTION_MODEL == PM.PRODUCTION_MODEL

    def test_it_is_the_same_object_not_a_matching_literal(self):
        """Equality would pass again the moment someone re-typed the string."""
        assert MP.PRODUCTION_MODEL is PM.PRODUCTION_MODEL

    def test_production_is_luna(self):
        assert PM.PRODUCTION_MODEL == "gpt-5.6-luna"


class TestPricingOwnsNoModelIdentity:
    """AST, not text: the module must not ASSIGN either name."""

    @staticmethod
    def _tree():
        path = os.path.join(ROOT, "src", "ai_brain", "model_pricing.py")
        return ast.parse(io.open(path, encoding="utf-8").read())

    @staticmethod
    def _assigned(tree):
        return {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}

    def test_it_assigns_no_production_model_of_its_own(self):
        assert "PRODUCTION_MODEL" not in self._assigned(self._tree())

    def test_the_dead_previous_symbol_is_gone(self):
        assert "PREVIOUS_PRODUCTION_MODEL" not in self._assigned(self._tree())
        assert not hasattr(MP, "PREVIOUS_PRODUCTION_MODEL")

    def test_it_imports_the_name_from_the_canonical_owner(self):
        mods = {n.module for n in ast.walk(self._tree())
                if isinstance(n, ast.ImportFrom)
                and any(a.name == "PRODUCTION_MODEL" for a in n.names)}
        assert mods == {"ai_brain.production_model"}, mods

    def test_no_terra_literal_survives_outside_the_pricing_table(self):
        """Terra must still be PRICEABLE; it must not be an identity here."""
        tree = self._tree()
        table = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "PRICING" for t in n.targets)]
        assert table, "the pricing table vanished"
        in_table = {c.value for c in ast.walk(table[0])
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        everywhere = {c.value for c in ast.walk(tree)
                      if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        assert "gpt-5.6-terra" in in_table          # still priceable
        stray = {s for s in everywhere - in_table if s.startswith("gpt-")}
        assert not stray, f"model literal outside the pricing table: {stray}"


class TestCostTelemetryFollowsTheRuling:
    USAGE = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}

    def test_the_default_model_is_priced_as_luna(self):
        cost = MP.cost_from_usage(self.USAGE)
        assert cost["model"] == "gpt-5.6-luna"
        assert cost["cost_usd"] == 1.40           # 0.20 in + 1.20 out

    def test_the_stale_default_was_12_5x_this(self):
        """The exact overstatement that shipped, kept as the regression."""
        terra = MP.cost_from_usage(self.USAGE, model="gpt-5.6-terra")["cost_usd"]
        luna = MP.cost_from_usage(self.USAGE)["cost_usd"]
        assert terra == 17.50
        assert round(terra / luna, 3) == 12.5

    def test_terra_is_still_priceable_when_named_explicitly(self):
        """Reserved for the Combine phase, not deleted."""
        assert MP.pricing_for("gpt-5.6-terra")["input"] == 2.50

    def test_the_production_model_always_has_pricing_on_file(self):
        assert PM.PRODUCTION_MODEL in MP.PRICING


class TestTheOwnershipDirectionCannotInvert:
    def test_the_canonical_owner_does_not_import_pricing(self):
        """`production_model` must stay free of this module, or the import
        becomes a cycle and someone 'fixes' it by re-duplicating the constant."""
        src = inspect.getsource(PM)
        assert "model_pricing" not in src

    def test_either_import_order_resolves_identically(self):
        """Shadowing is what hid the divergence; prove order cannot matter."""
        prog = ("import sys; sys.path.insert(0, %r);"
                "from ai_brain.%s import PRODUCTION_MODEL as A;"
                "from ai_brain.%s import PRODUCTION_MODEL as B;"
                "print(A, B)")
        pairs = [("model_pricing", "production_model"),
                 ("production_model", "model_pricing")]
        seen = set()
        for first, second in pairs:
            out = subprocess.run(
                [sys.executable, "-c",
                 prog % (os.path.join(ROOT, "src"), first, second)],
                capture_output=True, text=True, timeout=60)
            assert out.returncode == 0, out.stderr
            seen.add(out.stdout.strip())
        assert seen == {"gpt-5.6-luna gpt-5.6-luna"}, seen


class TestThisUnitChangedNothingElse:
    def test_the_brain_fingerprint_closure_excludes_pricing(self):
        """Pricing is telemetry. It is not part of the decision contract, so
        this repair does not move the fingerprint tomorrow binds."""
        sources = {rel for _, rel in PM._CONTRACT_SOURCES + PM._CONTRACT_SOURCES_REPO}
        assert "ai_brain/model_pricing.py" not in sources

    def test_the_forbidden_model_ruling_is_untouched(self):
        assert PM.PREVIOUS_PRODUCTION_MODEL == "gpt-5.6-terra"
        assert PM.PREVIOUS_PRODUCTION_MODEL in PM.FORBIDDEN_MODELS
