from app.api.schemas import CreatorResearchControls, CreatorResearchStart


def test_research_start_uses_bounded_defaults():
    payload = CreatorResearchStart()

    assert payload.batch_size == 3
    assert payload.target_video_limit == 10
    assert payload.failure_threshold_percent == 20
    assert payload.auto_continue is False


def test_research_controls_accept_clearable_optional_limits():
    controls = CreatorResearchControls(
        auto_continue=True,
        target_video_limit=None,
        failure_threshold_percent=None,
    )

    assert controls.auto_continue is True
    assert controls.target_video_limit is None
    assert controls.failure_threshold_percent is None
    assert {"target_video_limit", "failure_threshold_percent"}.issubset(controls.model_fields_set)
