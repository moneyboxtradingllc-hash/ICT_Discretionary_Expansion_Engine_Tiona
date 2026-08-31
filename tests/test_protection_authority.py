"""PROTECTION-AUTHORITY-1 — one position, one protection author.

The guard this replaces could not fail. `topstepx_production_doctrine.resolve()`
returned the literal `"topstep_position_brackets": "disabled"` and
`assert_no_conflict()` compared that constant against itself; both production
callers pass no argument. It was already false in practice -- account 33333333
rejected order-attached brackets with errorCode=2 "Brackets cannot be used with
Position Brackets" while startup passed.

The account state is NOT measurable: `/api/Account/search` publishes six fields
and none is a bracket setting. So it is attested by a named human, bound to one
account and one date, and refused when absent. Every branch fails closed --
"nobody looked" is refused exactly like "brackets are enabled", because as
evidence they are worth the same.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_protection_authority as PA          # noqa: E402

PRAC_ID = 11111111
PRAC_FP = "acct:aaaaaaaaaaaa"
COMBINE_ID = 22222222
COMBINE_FP = "acct:bbbbbbbbbbbb"
RETIRED_FP = "acct:cccccccccccc"
DATE = "2026-08-19"


def _att(**over):
    att = PA.build(account_id=PRAC_ID, account_fingerprint=PRAC_FP,
                   session_date=DATE, confirmed_by="Maurice Phillips")
    att.update(over)
    return att


def _ok(att):
    return PA.verify(att, account_id=PRAC_ID, account_fingerprint=PRAC_FP,
                     session_date=DATE)


class TestAValidAttestation:
    def test_it_verifies(self):
        assert _ok(_att()) == []

    def test_it_records_that_it_was_not_measured(self):
        att = _att()
        assert att["measurable_by_api"] is False
        assert att["source"] == "operator_visual_confirmation_of_venue_ui"
        assert att["confirmed_by"] == "operator"

    def test_it_records_BOTH_axes_separately(self):
        """Mechanism and price author are different propositions."""
        att = _att()
        assert att["account_position_brackets"] == PA.CONFIRMED_DISABLED     # axis A
        assert att["account_bracket_mode"] == PA.AUTO_OCO_ORDER_BASED        # axis A
        assert att["protection_owner"] == PA.BOT_ATTACHED_BRACKETS           # axis B
        assert att["schema_version"] == "protection_authority.v2"

    def test_it_carries_a_stable_fingerprint(self):
        assert PA.attestation_fingerprint(_att()) == PA.attestation_fingerprint(_att())

    def test_the_fingerprint_ignores_when_it_was_recorded(self):
        """Re-recording the same facts may not invalidate an authorization."""
        a = _att(confirmed_at_utc="2026-08-19T10:00:00+00:00")
        b = _att(confirmed_at_utc="2026-08-19T13:37:00+00:00")
        assert PA.attestation_fingerprint(a) == PA.attestation_fingerprint(b)

    def test_the_fingerprint_changes_when_a_CLAIM_changes(self):
        a = _att()
        b = _att(account_bracket_mode="position_based")
        assert PA.attestation_fingerprint(a) != PA.attestation_fingerprint(b)


class TestItFailsClosed:
    def test_absent_is_refused(self):
        reasons = PA.verify(None, account_id=PRAC_ID, account_fingerprint=PRAC_FP,
                            session_date=DATE)
        assert any(PA.MISSING in r for r in reasons)

    def test_corrupt_is_refused(self):
        reasons = PA.verify({"__corrupt__": True}, account_id=PRAC_ID,
                            account_fingerprint=PRAC_FP, session_date=DATE)
        assert any(PA.CORRUPT in r for r in reasons)

    def test_a_yesterday_attestation_is_refused(self):
        assert any(PA.EXPIRED in r for r in _ok(_att(valid_for_session_date="2026-08-18")))

    def test_the_combine_account_cannot_borrow_the_prac_attestation(self):
        reasons = PA.verify(_att(), account_id=COMBINE_ID,
                            account_fingerprint=COMBINE_FP, session_date=DATE)
        assert any(PA.ACCOUNT_MISMATCH in r for r in reasons)
        assert any(PA.FINGERPRINT_MISMATCH in r for r in reasons)

    def test_the_retired_fingerprint_is_refused(self):
        reasons = PA.verify(_att(account_fingerprint=RETIRED_FP), account_id=PRAC_ID,
                            account_fingerprint=PRAC_FP, session_date=DATE)
        assert any(PA.FINGERPRINT_MISMATCH in r for r in reasons)

    def test_position_brackets_enabled_is_refused(self):
        assert any(PA.POSITION_BRACKETS_ENABLED in r
                   for r in _ok(_att(account_position_brackets="enabled")))

    def test_a_position_based_bracket_mode_is_refused(self):
        """Auto-OCO is the MECHANISM our attached bracket rides on, not a rival.

        v1 demanded Auto-OCO be DISABLED. The only evidence for that was the
        venue text `errorCode=2 "Brackets cannot be used with Position
        Brackets"`, which names POSITION brackets alone. Under the widened
        requirement the first attached-bracket canary was rejected instantly
        (order 3420877831, status 5, 0 fills). What must be refused is the
        account sitting in a POSITION-based mode.
        """
        assert any(PA.BRACKET_MODE_WRONG in r
                   for r in _ok(_att(account_bracket_mode="position_based")))

    def test_an_unknown_bracket_mode_is_refused(self):
        assert any(PA.BRACKET_MODE_WRONG in r
                   for r in _ok(_att(account_bracket_mode="unknown")))

    def test_order_based_auto_oco_is_ACCEPTED(self):
        assert _ok(_att(account_bracket_mode=PA.AUTO_OCO_ORDER_BASED)) == []

    def test_a_v1_attestation_is_superseded_not_reinterpreted(self):
        """It asserted a materially different proposition about the venue."""
        legacy = _att(schema_version=PA.LEGACY_SCHEMA_V1)
        legacy.pop("account_bracket_mode", None)
        legacy["account_auto_oco"] = "confirmed_disabled"
        reasons = _ok(legacy)
        assert any(PA.SCHEMA_MISMATCH in r for r in reasons)
        assert any("conflated" in r for r in reasons)

    def test_a_venue_owned_protection_owner_is_refused(self):
        assert any(PA.OWNER_CONFLICT in r
                   for r in _ok(_att(protection_owner="account_auto_oco")))

    def test_an_unsigned_attestation_is_refused(self):
        assert any(PA.NOT_OPERATOR_CONFIRMED in r for r in _ok(_att(confirmed_by_name="")))

    def test_a_wrong_schema_is_refused(self):
        assert any(PA.SCHEMA_MISMATCH in r for r in _ok(_att(schema_version="v0")))


class TestResolveFromDisk:
    def test_a_missing_file_is_unauthorized(self, tmp_path):
        out = PA.resolve(str(tmp_path), account_id=PRAC_ID,
                         account_fingerprint=PRAC_FP, session_date=DATE)
        assert out["authorized"] is False
        assert out["attestation_fingerprint"] is None
        assert out["measured_by_api"] is False

    def test_a_valid_file_authorizes(self, tmp_path):
        with open(PA.store_path(str(tmp_path)), "w", encoding="utf-8") as fh:
            json.dump(_att(), fh)
        out = PA.resolve(str(tmp_path), account_id=PRAC_ID,
                         account_fingerprint=PRAC_FP, session_date=DATE)
        assert out["authorized"] is True
        assert out["attestation_fingerprint"].startswith("prot:")

    def test_unparsable_json_is_unauthorized_not_a_crash(self, tmp_path):
        with open(PA.store_path(str(tmp_path)), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        out = PA.resolve(str(tmp_path), account_id=PRAC_ID,
                         account_fingerprint=PRAC_FP, session_date=DATE)
        assert out["authorized"] is False
        assert any(PA.CORRUPT in r for r in out["reasons"])


class TestTheDoctrineNoLongerSelfCertifies:
    def test_the_declaration_is_labelled_as_a_declaration(self):
        from broker.topstepx_production_doctrine import resolve
        d = resolve()
        assert d["topstep_position_brackets_source"] == "doctrine_declaration_not_measured"
        assert d["account_protection_state_authority"] == "operator_attestation_required"

    def test_the_account_state_owner_is_a_different_module(self):
        """The guard may state doctrine; it may not imply the venue was read."""
        import inspect
        from broker import topstepx_production_doctrine as D
        src = inspect.getsource(D.assert_no_conflict)
        assert "topstepx_protection_authority" in src


class TestTheRecordingToolCannotAutoAttest:
    def test_it_refuses_without_the_visual_confirmation_flag(self, tmp_path, monkeypatch):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import record_protection_attestation as REC
        monkeypatch.setattr(REC, "STORE_DIR", str(tmp_path))
        rc = REC.main(["--confirmed-by", "Maurice Phillips",
                       "--session-date", DATE,
                       "--account-id", str(PRAC_ID),
                       "--account-fingerprint", PRAC_FP])
        assert rc == 2
        assert not os.path.exists(PA.store_path(str(tmp_path)))

    def test_it_writes_only_with_explicit_operator_confirmation(self, tmp_path, monkeypatch):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import record_protection_attestation as REC
        monkeypatch.setattr(REC, "STORE_DIR", str(tmp_path))
        rc = REC.main(["--confirmed-by", "Maurice Phillips",
                       "--session-date", DATE,
                       "--account-id", str(PRAC_ID),
                       "--account-fingerprint", PRAC_FP,
                       "--i-have-visually-confirmed"])
        assert rc == 0
        att = json.load(open(PA.store_path(str(tmp_path)), encoding="utf-8"))
        assert att["confirmed_by_name"] == "Maurice Phillips"
        assert PA.verify(att, account_id=PRAC_ID, account_fingerprint=PRAC_FP,
                         session_date=DATE) == []

    def test_no_production_module_creates_an_attestation(self):
        """Only the operator tool may author this. Nothing may self-attest."""
        import pathlib
        root = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        offenders = []
        for path in (root / "src").rglob("*.py"):
            if "PA.build(" in path.read_text(encoding="utf-8") or \
                    "protection_authority.build(" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))
        assert offenders == [], offenders
