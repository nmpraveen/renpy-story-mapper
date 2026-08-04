from __future__ import annotations

from types import MappingProxyType

from renpy_story_mapper.storyboard import render_storyboard, render_storyboard_html


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    evidence = {
        "evidence": [
            {
                "id": "line-two",
                "source_text": "<script>alert('line')</script> & second",
                "source": {
                    "path": "game/<route>.rpy",
                    "start": {"line": 14},
                    "end": {"line": 14},
                },
            },
            {
                "id": "line-one",
                "source_text": "First exact line",
                "source": {
                    "path": "game/<route>.rpy",
                    "start": {"line": 10},
                    "end": {"line": 10},
                },
            },
            {
                "id": "menu",
                "source_text": "menu:",
                "source": {"path": "game/<route>.rpy", "start_line": 11},
            },
            {
                "id": "arm-second",
                "source_text": '"Second" if flag',
                "source": {"path": "game/<route>.rpy", "start_line": 13},
            },
            {
                "id": "arm-first",
                "source_text": '"First"',
                "source": {"path": "game/<route>.rpy", "start_line": 12},
            },
        ]
    }
    profile = {"title": 'Profile & <unsafe> "name"'}
    analysis = {
        "summary": "AI overview & <summary>",
        "scenes": [
            {
                "title": "Scene <one>",
                "summary": "AI scene summary",
                "confidence": "medium",
                "line_evidence_ids": ["line-two", "line-one"],
                "line_text": "This must never be treated as an exact line",
                "branches": [
                    {
                        "title": "Conditional branch",
                        "condition": "flag & <value>",
                        "consequence": "A delayed consequence",
                        "destination": "later scene",
                        "rejoin": "shared continuation",
                        "evidence_id": "line-one",
                    }
                ],
                "menus": [
                    {
                        "title": "Choice <point>",
                        "evidence_id": "menu",
                        "arms": [
                            {
                                "caption": "Second arm",
                                "condition": "flag",
                                "consequence": "Second consequence",
                                "destination": "Second destination",
                                "rejoin": "Common rejoin",
                                "evidence_id": "arm-second",
                            },
                            {
                                "caption": "First arm",
                                "condition": "always",
                                "consequence": "First consequence",
                                "destination": "First destination",
                                "terminal": {"description": "Ending <description>"},
                                "evidence_id": "arm-first",
                            },
                        ],
                    }
                ],
                "unresolved": [{"message": "Dynamic target <unknown>"}],
            }
        ],
    }
    report = {
        "status": "warning",
        "issues": [{"message": "One source item remains unaccounted"}],
        "disagreements": [
            {
                "parser": "Parser view <A>",
                "ai": "AI view & B",
                "evidence_ids": ["line-one"],
            }
        ],
    }
    return evidence, profile, analysis, report


def test_render_storyboard_contains_ai_content_exact_evidence_and_all_ordered_arms() -> None:
    evidence, profile, analysis, report = _inputs()

    html = render_storyboard_html(evidence, profile, analysis, report)

    assert "<!doctype html>" in html
    assert "Scene &lt;one&gt;" in html
    assert "AI overview &amp; &lt;summary&gt;" in html
    assert "First exact line" in html
    assert "&lt;script&gt;alert(&#x27;line&#x27;)&lt;/script&gt; &amp; second" in html
    assert "This must never be treated as an exact line" not in html
    assert "game/&lt;route&gt;.rpy:10" in html
    assert "game/&lt;route&gt;.rpy:14" in html

    first_arm = html.index("First arm")
    second_arm = html.index("Second arm")
    assert first_arm < second_arm
    for expected in (
        "flag",
        "Second consequence",
        "Second destination",
        "Common rejoin",
        "Ending &lt;description&gt;",
        "Dynamic target &lt;unknown&gt;",
        "One source item remains unaccounted",
        "Parser view &lt;A&gt;",
        "AI view &amp; B",
    ):
        assert expected in html

    assert "<script" not in html.lower()
    assert "src=" not in html.lower()
    assert "https://" not in html.lower()


def test_exact_lines_use_only_resolved_evidence_ids_and_show_missing_references() -> None:
    evidence, profile, _analysis, report = _inputs()
    analysis = {
        "scenes": [
            {
                "title": "Evidence boundary",
                "line_evidence_ids": ["line-one", "invented-id"],
                "line_text": "Not an evidence record",
            }
        ]
    }

    html = render_storyboard_html(evidence, profile, analysis, report)

    assert "First exact line" in html
    assert "Not an evidence record" not in html
    assert "Evidence invented-id is unavailable." in html
    assert "Missing evidence reference: invented-id" in html


def test_mapping_compatible_inputs_are_accepted() -> None:
    evidence, profile, analysis, report = _inputs()

    def freeze(value: object) -> object:
        if isinstance(value, dict):
            return MappingProxyType({key: freeze(item) for key, item in value.items()})
        if isinstance(value, list):
            return tuple(freeze(item) for item in value)
        return value

    html = render_storyboard_html(
        freeze(evidence),  # type: ignore[arg-type]
        freeze(profile),  # type: ignore[arg-type]
        freeze(analysis),  # type: ignore[arg-type]
        freeze(report),  # type: ignore[arg-type]
    )

    assert "Profile &amp; &lt;unsafe&gt; &quot;name&quot;" in html
    assert "Choice &lt;point&gt;" in html


def test_scene_evidence_is_cited_without_being_presented_as_an_exact_line() -> None:
    evidence, profile, analysis, report = _inputs()
    scene = analysis["scenes"][0]
    assert isinstance(scene, dict)
    scene["evidence_ids"] = ["menu"]
    scene["line_evidence_ids"] = ["line-one"]

    html = render_storyboard(evidence, profile, analysis, report)

    assert "First exact line" in html
    assert "Scene evidence" in html
    assert '<span class="exact-line-text">menu:</span>' not in html


def test_validation_errors_are_visible_and_scene_uncertainty_is_nested() -> None:
    evidence, profile, analysis, _report = _inputs()
    report = {
        "status": "rejected",
        "errors": [
            {
                "code": "missing_menu_arm",
                "message": "The second arm is missing.",
                "evidence_ids": ["arm-second"],
                "source": {"path": "game/canary.rpy", "start": {"line": 13}},
            }
        ],
    }

    html = render_storyboard_html(evidence, profile, analysis, report)

    assert "Validation: rejected" in html
    assert "missing_menu_arm" in html
    assert "The second arm is missing." in html
    assert "game/canary.rpy:13" in html
    assert "<h3>Uncertainty</h3>" in html
