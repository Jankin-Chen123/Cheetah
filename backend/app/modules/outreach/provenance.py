"""Keep input origins separate from the model execution origin."""


def inherited_provenance(case, *upstream):
    modes = set()

    def include(mode):
        modes.add(
            {"real": "live"}.get(mode, mode)
            if mode in {"real", "live", "mock", "manual"}
            else "unknown"
        )

    fixture = bool(case.snapshot.get("fixture_only"))
    for mode in case.snapshot.get("source_modes", {}).values():
        include(mode)
    if fixture:
        modes.add("mock")
    for answer in case.session_data.get("answers", []):
        include(answer.get("source_mode"))
    for artifact in upstream:
        provenance = artifact.provenance
        fixture = fixture or bool(provenance.get("fixture_only"))
        include(provenance.get("source_mode"))
        for mode in provenance.get("inherited_source_modes", []):
            include(mode)
    if fixture:
        modes.add("mock")
    return {
        "inherited_source_modes": sorted(modes or {"unknown"}),
        "fixture_only": fixture,
    }
