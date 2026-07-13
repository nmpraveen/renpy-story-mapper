"""Unified read-only discovery, precedence, and ingestion service."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath

from renpy_story_mapper import storage
from renpy_story_mapper.ingestion.contracts import (
    CancelCheck,
    IngestionOptions,
    IngestionPlan,
    IngestionResult,
    IngestionSource,
    InputKind,
    RecoveryFailure,
    SourceCandidate,
    SourceProvenance,
    SourceTier,
)
from renpy_story_mapper.ingestion.errors import (
    AmbiguousSourceError,
    IngestionError,
    RecoveryError,
)
from renpy_story_mapper.ingestion.runtime import recover_compiled
from renpy_story_mapper.rpa import RpaArchive, fingerprint_file

_TIER_ORDER = (
    SourceTier.LOOSE_ORIGINAL,
    SourceTier.ARCHIVED_ORIGINAL,
    SourceTier.LOOSE_RECOVERED,
    SourceTier.ARCHIVED_RECOVERED,
)


def inspect_input(
    path: str | os.PathLike[str],
    options: IngestionOptions | None = None,
    cancel_check: CancelCheck = None,
) -> IngestionPlan:
    """Inventory a supported input and select deterministic source candidates."""

    configured = options or IngestionOptions()
    requested = Path(path)
    resolved = requested.resolve(strict=True)
    _check_cancelled(cancel_check)
    if resolved.is_file() and resolved.suffix.casefold() == ".rsmproj":
        connection = storage.connect(resolved)
        try:
            storage.validate_database(connection, allow_legacy_v4=True)
        finally:
            connection.close()
        return IngestionPlan(
            requested,
            resolved,
            InputKind.PROJECT,
            None,
            (),
            (),
            existing_project=resolved,
        )

    source_root: Path | None = None
    candidates: list[SourceCandidate] = []
    secondary_candidates: list[SourceCandidate] = []
    if resolved.is_dir():
        source_root = _resolve_game_root(resolved)
        kind = InputKind.GAME_FOLDER
        candidates.extend(_loose_candidates(source_root, configured, cancel_check))
        archives: list[Path] = []
        for item in source_root.rglob("*.rpa"):
            if not item.is_file():
                continue
            archive = item.resolve(strict=True)
            try:
                archive.relative_to(source_root)
            except ValueError as exc:
                raise IngestionError(
                    f"archive path escapes selected game folder: {item}"
                ) from exc
            archives.append(archive)
        archives.sort(key=lambda item: item.as_posix().casefold())
        archive_names = {archive.name.casefold() for archive in archives}
        quarantine_extras = {"scripts.rpa", "extras.rpa"}.issubset(archive_names)
        for archive in archives:
            archive_candidates = _archive_candidates(archive, configured, cancel_check)
            if quarantine_extras and archive.name.casefold() == "extras.rpa":
                secondary_candidates.extend(archive_candidates)
            else:
                candidates.extend(archive_candidates)
    elif resolved.is_file():
        suffix = resolved.suffix.casefold()
        if suffix == ".rpa":
            kind = InputKind.ARCHIVE
            candidates.extend(_archive_candidates(resolved, configured, cancel_check))
        elif suffix in {".rpy", ".rpyc"}:
            kind = InputKind.SOURCE_FILE if suffix == ".rpy" else InputKind.COMPILED_FILE
            candidates.append(_direct_candidate(resolved, configured.max_input_bytes))
        else:
            raise IngestionError(
                "unsupported input; select a game folder, .rpy, .rpyc, .rpa, or .rsmproj"
            )
    else:
        raise IngestionError(f"input is not a regular file or directory: {resolved}")
    if len(candidates) + len(secondary_candidates) > configured.max_sources:
        raise IngestionError("source inventory exceeds configured source-count limit")
    selected = _select_sources(candidates)
    secondary_selected = _select_sources(secondary_candidates)
    if not selected:
        raise IngestionError("input contains no .rpy or .rpyc story sources")
    return IngestionPlan(
        requested,
        resolved,
        kind,
        source_root,
        tuple(sorted(candidates, key=_candidate_sort_key)),
        selected,
        secondary_candidates=secondary_selected,
    )


def ingest_input(
    path: str | os.PathLike[str],
    options: IngestionOptions | None = None,
    cancel_check: CancelCheck = None,
) -> IngestionResult:
    """Read selected inert sources and recover compiled inputs under strict policy."""

    configured = options or IngestionOptions()
    plan = inspect_input(path, configured, cancel_check)
    if plan.input_kind is InputKind.PROJECT:
        return IngestionResult(plan, (), True, False)
    _validate_cache_location(plan, configured)
    sources: list[IngestionSource] = []
    secondary_sources: list[IngestionSource] = []
    warnings: list[str] = []
    recovery_failures: list[RecoveryFailure] = []
    secondary_recovery_failures: list[RecoveryFailure] = []
    complete = True
    total_output = 0
    archive_fingerprints: dict[Path, object] = {}
    materialization_groups = (
        (plan.selected, sources, recovery_failures, False),
        (plan.secondary_candidates, secondary_sources, secondary_recovery_failures, True),
    )
    for candidates, destination, failures, is_secondary in materialization_groups:
        for candidate in candidates:
            _check_cancelled(cancel_check)
            if (
                candidate.archive_entry is not None
                and candidate.container_path not in archive_fingerprints
            ):
                archive_fingerprints[candidate.container_path] = fingerprint_file(
                    candidate.container_path
                )
            content = _read_candidate(candidate, configured.max_input_bytes)
            if hashlib.sha256(content).hexdigest() != candidate.input_hash:
                raise IngestionError(f"source changed during ingestion: {candidate.locator}")
            if candidate.tier in {
                SourceTier.LOOSE_RECOVERED,
                SourceTier.ARCHIVED_RECOVERED,
            }:
                try:
                    output, provenance = recover_compiled(
                        candidate, content, configured, cancel_check
                    )
                except RecoveryError as exc:
                    if not configured.allow_partial_recovery:
                        raise
                    if not is_secondary:
                        complete = False
                    sanitized = " ".join(str(exc).replace("\x00", "").split())[:500]
                    qualifier = "Secondary recovery" if is_secondary else "Recovery"
                    warnings.append(f"{qualifier} omitted {candidate.logical_path}: {sanitized}")
                    failures.append(
                        RecoveryFailure(
                            candidate.logical_path,
                            candidate.locator,
                            candidate.input_hash,
                            type(exc).__name__,
                            sanitized,
                        )
                    )
                    continue
            else:
                output = content
                provenance = SourceProvenance(
                    source_kind="original",
                    locator=candidate.locator,
                    tier=candidate.tier,
                    input_sha256=candidate.input_hash,
                    output_sha256=candidate.input_hash,
                    line_basis="physical_original_source",
                )
            total_output += len(output)
            if total_output > configured.max_total_output_bytes:
                raise IngestionError("selected source output exceeds aggregate byte limit")
            output_path = str(PurePosixPath(candidate.logical_path).with_suffix(".rpy"))
            destination.append(IngestionSource(output_path, output, provenance))
            if not provenance.complete and not is_secondary:
                complete = False
                warnings.extend(provenance.warnings)
    for archive_path, before in archive_fingerprints.items():
        if fingerprint_file(archive_path) != before:
            raise IngestionError(f"archive changed during ingestion: {archive_path}")
    if not sources:
        raise IngestionError("no usable story sources remain after recovery")
    if not complete:
        warnings.append(
            "Source coverage is incomplete; AI transmission remains blocked until explicit "
            "acknowledgement."
        )
    return IngestionResult(
        plan,
        tuple(sorted(sources, key=lambda item: item.path.casefold())),
        complete,
        not complete,
        tuple(dict.fromkeys(warnings)),
        tuple(recovery_failures),
        tuple(sorted(secondary_sources, key=lambda item: item.path.casefold())),
        tuple(secondary_recovery_failures),
    )


def _resolve_game_root(selected: Path) -> Path:
    if selected.name.casefold() == "game":
        return selected
    game = selected / "game"
    if game.is_dir():
        return game.resolve(strict=True)
    return selected


def _logical_path(relative: str) -> str:
    normalized = PurePosixPath(relative.replace("\\", "/"))
    parts = normalized.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise IngestionError(f"unsafe source path: {relative!r}")
    if parts[0].casefold() == "game":
        return PurePosixPath("game", *parts[1:]).as_posix()
    return PurePosixPath("game", *parts).as_posix()


def _loose_candidates(
    root: Path, options: IngestionOptions, cancel_check: CancelCheck
) -> list[SourceCandidate]:
    result: list[SourceCandidate] = []
    files = sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and item.suffix.casefold() in {".rpy", ".rpyc"}
        ),
        key=lambda item: item.as_posix().casefold(),
    )
    for candidate in files:
        _check_cancelled(cancel_check)
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise IngestionError(f"source path escapes selected game folder: {candidate}") from exc
        result.append(_file_candidate(resolved, _logical_path(relative), options.max_input_bytes))
    return result


def _direct_candidate(path: Path, max_input_bytes: int) -> SourceCandidate:
    return _file_candidate(path, _logical_path(path.name), max_input_bytes)


def _file_candidate(path: Path, logical_path: str, max_input_bytes: int) -> SourceCandidate:
    size = path.stat().st_size
    if size > max_input_bytes:
        raise IngestionError(f"source exceeds configured input limit: {path}")
    content = path.read_bytes()
    if len(content) != size:
        raise IngestionError(f"source changed while being inspected: {path}")
    suffix = path.suffix.casefold()
    tier = SourceTier.LOOSE_ORIGINAL if suffix == ".rpy" else SourceTier.LOOSE_RECOVERED
    return SourceCandidate(
        logical_path,
        tier,
        str(path),
        hashlib.sha256(content).hexdigest(),
        size,
        path,
    )


def _archive_candidates(
    path: Path, options: IngestionOptions, cancel_check: CancelCheck
) -> list[SourceCandidate]:
    _check_cancelled(cancel_check)
    before = fingerprint_file(path)
    archive = RpaArchive(path, max_entry_size=options.max_input_bytes)
    result: list[SourceCandidate] = []
    for entry in archive.entries:
        _check_cancelled(cancel_check)
        suffix = PurePosixPath(entry.path).suffix.casefold()
        if suffix not in {".rpy", ".rpyc"}:
            continue
        tier = SourceTier.ARCHIVED_ORIGINAL if suffix == ".rpy" else SourceTier.ARCHIVED_RECOVERED
        result.append(
            SourceCandidate(
                _logical_path(entry.path),
                tier,
                f"{path}!/{entry.path}",
                archive.hash_entry(entry),
                entry.size,
                path,
                entry.path,
            )
        )
    if fingerprint_file(path) != before:
        raise IngestionError(f"archive changed while being inspected: {path}")
    return result


def _select_sources(candidates: list[SourceCandidate]) -> tuple[SourceCandidate, ...]:
    by_stem: dict[str, list[SourceCandidate]] = {}
    for candidate in candidates:
        stem = str(PurePosixPath(candidate.logical_path).with_suffix("")).casefold()
        by_stem.setdefault(stem, []).append(candidate)
    selected: list[SourceCandidate] = []
    for stem in sorted(by_stem):
        group = by_stem[stem]
        for tier in _TIER_ORDER:
            same_tier = sorted(
                (item for item in group if item.tier is tier), key=_candidate_sort_key
            )
            if not same_tier:
                continue
            hashes = {item.input_hash for item in same_tier}
            if len(hashes) > 1:
                locators = ", ".join(item.locator for item in same_tier)
                raise AmbiguousSourceError(
                    f"conflicting same-tier sources for {stem!r} ({tier.value}): {locators}"
                )
            selected.append(same_tier[0])
            break
    return tuple(sorted(selected, key=_candidate_sort_key))


def _read_candidate(candidate: SourceCandidate, max_input_bytes: int) -> bytes:
    if candidate.archive_entry is None:
        return candidate.container_path.read_bytes()
    archive = RpaArchive(candidate.container_path, max_entry_size=max_input_bytes)
    entry = next((item for item in archive.entries if item.path == candidate.archive_entry), None)
    if entry is None:
        raise IngestionError(f"archive source disappeared: {candidate.locator}")
    return b"".join(archive.iter_entry_bytes(entry))


def _candidate_sort_key(value: SourceCandidate) -> tuple[str, str, str]:
    return (value.logical_path.casefold(), value.tier.value, value.locator.casefold())


def _validate_cache_location(plan: IngestionPlan, options: IngestionOptions) -> None:
    cache = options.resolved_cache_root()
    source_boundary = (
        plan.source_root
        if plan.source_root is not None
        else plan.resolved_input.parent
    )
    try:
        cache.relative_to(source_boundary)
    except ValueError:
        return
    raise IngestionError("recovery cache must be outside the selected source/game directory")


def _check_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        from renpy_story_mapper.storage import ProjectOperationCancelled

        raise ProjectOperationCancelled("input inspection was cancelled")
