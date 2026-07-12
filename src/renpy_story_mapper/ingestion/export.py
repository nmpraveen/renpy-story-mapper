"""Explicit recovered-source export with provenance and containment checks."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from renpy_story_mapper.ingestion.contracts import IngestionResult
from renpy_story_mapper.ingestion.errors import UnsafeExportError


def export_recovered_sources(
    result: IngestionResult,
    destination: str | os.PathLike[str],
) -> Path:
    recovered = [
        source for source in result.sources if source.provenance.source_kind == "reconstructed"
    ]
    if not recovered:
        raise UnsafeExportError("ingestion result contains no reconstructed sources")
    target = Path(destination).resolve()
    forbidden = [result.plan.resolved_input]
    if result.plan.resolved_input.is_file():
        forbidden.append(result.plan.resolved_input.parent)
    if result.plan.source_root is not None:
        forbidden.append(result.plan.source_root)
    if result.plan.existing_project is not None:
        forbidden.append(result.plan.existing_project.parent)
    for root in forbidden:
        if target == root or _is_relative_to(target, root):
            raise UnsafeExportError(
                "recovered-source export must be outside the source/game/project"
            )
    if target.exists():
        raise UnsafeExportError("recovered-source export destination must not already exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    staged.mkdir()
    try:
        records: list[dict[str, object]] = []
        for source in sorted(recovered, key=lambda item: item.path.casefold()):
            relative = Path(*Path(source.path).parts)
            output = (staged / relative).resolve()
            if not _is_relative_to(output, staged):
                raise UnsafeExportError("recovered source path escapes export destination")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(source.content)
            records.append({"path": source.path, "provenance": source.provenance.to_dict()})
        manifest = {
            "schema_version": 1,
            "warning": (
                "These files are reconstructed evidence, not original author source. "
                "Line numbers are reconstructed and may differ from physical original lines."
            ),
            "complete": result.complete,
            "ai_transmission_blocked": result.ai_transmission_blocked,
            "sources": records,
        }
        encoded = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        (staged / "RECOVERY_PROVENANCE.json").write_bytes(encoded)
        (staged / "RECOVERY_PROVENANCE.sha256").write_text(
            hashlib.sha256(encoded).hexdigest() + "\n", encoding="ascii"
        )
        staged.replace(target)
    except BaseException:
        import shutil

        shutil.rmtree(staged, ignore_errors=True)
        raise
    return target


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
