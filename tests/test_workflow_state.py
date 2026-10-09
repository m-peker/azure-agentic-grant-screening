from grant_screening.workflow.graph import to_case


def test_to_case_does_not_share_mutable_state(monkeypatch):
    import grant_screening.workflow.graph as g

    monkeypatch.setattr(g.engine, "load_rulebook", lambda *a, **k: {"version": 3})
    state = {"application_id": "MGA-X", "deadline": "2026-09-30", "rulebook_version": 3,
             "ledger": [], "trace": [{"stage": "C+D1"}], "claims": [{"kind": "other"}]}
    a, b = to_case(state), to_case(state)
    a["trace"].append({"stage": "D2"})
    b["trace"].append({"stage": "E"})
    a["claims"][0]["agent"] = {}
    assert state["trace"] == [{"stage": "C+D1"}]        # parallel branches must not leak into each other
    assert "agent" not in state["claims"][0]
