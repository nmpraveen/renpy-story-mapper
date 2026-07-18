"""Run one explicit public-synthetic M13 structured-output schema canary.

The default action is a local preview. A provider call requires both ``--execute`` and the
literal public-synthetic confirmation. No story, project, source, or private evidence is read.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from renpy_story_mapper.narrative.contracts import JsonValue, ProviderSettings
from renpy_story_mapper.narrative.provider import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    RESPONSE_SCHEMA_VERSION,
    CodexCliNarrativeProvider,
    ProviderBatchItem,
    ProviderRequest,
)

_CONFIRMATION = "PUBLIC_SYNTHETIC_SCHEMA_CANARY"
_LOGICAL_JOB_ID = "public-synthetic-schema-canary"


def build_canary_request(model: str, reasoning_effort: str) -> ProviderRequest:
    """Build the exact one-item, no-story request used by the canary."""

    settings = ProviderSettings(
        values=(
            ("fast_mode", False),
            ("model_reasoning_effort", reasoning_effort),
        )
    )
    payload: dict[str, JsonValue] = {
        "job_kind": "public_synthetic_schema_canary",
        "public_synthetic": True,
        "instruction": (
            "Return one schema-valid synthetic artifact confirming that a blue circle is round."
        ),
        "evidence_handles": [
            {
                "handle": "E1",
                "public_synthetic_fact": "A blue circle is round.",
            }
        ],
    }
    return ProviderRequest(
        request_id="m13-public-synthetic-schema-canary-v1",
        consent_manifest_id="public-synthetic-schema-canary-explicit-confirmation-v1",
        requested_model=model,
        settings=settings,
        items=(
            ProviderBatchItem(
                logical_job_id=_LOGICAL_JOB_ID,
                input_revision_id="public-synthetic-schema-canary-input-v1",
                payload=payload,
            ),
        ),
        timeout_seconds=120.0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Exact provider model identifier.")
    parser.add_argument(
        "--reasoning-effort",
        required=True,
        choices=("low", "medium", "high", "xhigh"),
        help="Exact model reasoning effort recorded in provider identity.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Permit the utility's single provider call.",
    )
    parser.add_argument(
        "--confirm-public-synthetic",
        metavar="TEXT",
        help=f"Required with --execute; must equal {_CONFIRMATION!r}.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = build_canary_request(args.model, args.reasoning_effort)
    preview = {
        "adapter": ADAPTER_NAME,
        "adapter_version": ADAPTER_VERSION,
        "model": request.requested_model,
        "provider_calls": 0 if not args.execute else 1,
        "public_synthetic": True,
        "response_schema_version": RESPONSE_SCHEMA_VERSION,
        "settings": request.settings.to_dict(),
    }
    if not args.execute:
        print(json.dumps(preview, sort_keys=True))
        return 0
    if args.confirm_public_synthetic != _CONFIRMATION:
        _parser().error(
            f"--execute requires --confirm-public-synthetic {_CONFIRMATION}"
        )

    response = CodexCliNarrativeProvider().submit(request, lambda: False)
    if response.usage.provider_calls != 1:
        raise AssertionError("schema canary must account for exactly one provider call")
    if response.response_schema_version != RESPONSE_SCHEMA_VERSION:
        raise AssertionError("schema canary response used a different schema version")
    if (
        response.provider.adapter != ADAPTER_NAME
        or response.provider.adapter_version != ADAPTER_VERSION
    ):
        raise AssertionError("schema canary response used a different adapter")
    if response.provider.requested_model != request.requested_model:
        raise AssertionError("schema canary response used a different requested model")
    if response.provider.settings != request.settings:
        raise AssertionError("schema canary response used different provider settings")
    if len(response.items) != 1 or response.items[0].logical_job_id != _LOGICAL_JOB_ID:
        raise AssertionError("schema canary response did not preserve its one logical job")
    print(
        json.dumps(
            {
                **preview,
                "resolved_model": response.provider.resolved_model,
                "succeeded": response.items[0].succeeded,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
