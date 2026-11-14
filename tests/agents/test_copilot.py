from muletrace.policy.loader import load_policies, lookup, policy_ids


def test_policy_library_entries_have_sources() -> None:
    entries = load_policies()
    assert len(entries) >= 8
    assert all(entry.source and entry.summary for entry in entries)
    assert "br-med-2" in policy_ids()
    assert lookup("dispute return med")[0].id.startswith("br-med")
    assert lookup("nothing matches zzz") == []
