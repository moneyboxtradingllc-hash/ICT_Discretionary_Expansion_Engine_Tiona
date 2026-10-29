"""A fixture clock must not relax the actual historical retention law."""
import json
import test_retrieval_telemetry as T
from ai_retrieval import retrieval as R,vector_store


def test_healthy_fixture_and_explicit_expiry_keep_the_same_records(tmp_path,monkeypatch):
    T.live.__wrapped__(tmp_path,monkeypatch)
    before=json.dumps(vector_store.load_records(),sort_keys=True)
    healthy=R.retrieve_for_snapshot(T.snap(),'MNQ')
    assert healthy['returned']>0
    expired=R.retrieve_analogs(T.snap(),today='2026-10-29',persist_log=False)
    assert expired['returned']==0
    assert expired['rejected_reasons'].get('expired',0)>0
    assert json.dumps(vector_store.load_records(),sort_keys=True)==before
