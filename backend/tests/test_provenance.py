from types import SimpleNamespace

from app.modules.outreach.provenance import inherited_provenance


def test_input_origins_are_inherited_without_fabricating_manual_or_mock():
    case = SimpleNamespace(
        snapshot={"fixture_only": False, "source_modes": {"screening": "real"}},
        session_data={"answers": [{"source_mode": "live"}]},
    )
    result = inherited_provenance(case)
    assert result == {"fixture_only": False, "inherited_source_modes": ["live"]}
    upstream = SimpleNamespace(
        provenance={
            "source_mode": "live",
            "inherited_source_modes": ["mock", "manual"],
            "fixture_only": True,
        }
    )
    assert inherited_provenance(case, upstream) == {
        "fixture_only": True,
        "inherited_source_modes": ["live", "manual", "mock"],
    }


def test_missing_origin_stays_unknown_even_when_model_is_live():
    case = SimpleNamespace(snapshot={}, session_data={"answers": [{"text": "历史回答"}]})
    upstream = SimpleNamespace(provenance={"source_mode": "live"})
    assert inherited_provenance(case, upstream)["inherited_source_modes"] == ["live", "unknown"]
