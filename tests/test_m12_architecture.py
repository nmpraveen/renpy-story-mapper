from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from renpy_story_mapper import storage
from renpy_story_mapper.m12_persistence import ROUTE_RESULTS_COLLECTION
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.project import create_ingested_project

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m12" / "route_targets.rpy"
M12_MODULES = tuple(sorted((ROOT / "src" / "renpy_story_mapper").glob("m12_*.py")))


def _project(tmp_path: Path):
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "routes.rsmproj", source), source


def _payload_bytes(project: object, collection: str, key: str) -> bytes:
    value = project.payload(collection, key)  # type: ignore[attr-defined]
    assert isinstance(value, dict)
    return storage.canonical_json(value)


def test_m12_modules_import_headlessly_without_execution_or_remote_dependencies() -> None:
    code = r"""
import builtins, json, socket, sys, urllib.request
sys.path.insert(0, sys.argv[1])
blocked = {"PySide6", "renpy", "requests", "httpx", "webbrowser"}
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".", 1)[0] in blocked or name == "renpy_story_mapper.organization.provider":
        raise AssertionError(f"forbidden import: {name}")
    return real_import(name, *args, **kwargs)
def boundary(*args, **kwargs):
    raise AssertionError("network boundary crossed")
builtins.__import__ = guarded
socket.create_connection = boundary
urllib.request.OpenerDirector.open = boundary
for name in (
    "renpy_story_mapper.m12_model",
    "renpy_story_mapper.m12_solver",
    "renpy_story_mapper.m12_persistence",
    "renpy_story_mapper.m12_service",
):
    __import__(name)
print(json.dumps({"imported": True, "forbidden_loaded": sorted(blocked & set(sys.modules))}))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT / "src")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"imported": true' in completed.stdout
    assert '"forbidden_loaded": []' in completed.stdout


def test_m12_source_has_no_execution_provider_network_or_export_subsystem() -> None:
    forbidden_import_roots = {
        "PySide6",
        "renpy",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "webbrowser",
    }
    forbidden_calls = {"exec", "eval", "compile", "os.system", "runpy.run_path"}
    for path in M12_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name.split(".", 1)[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
                assert node.module != "renpy_story_mapper.organization.provider"
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    calls.add(f"{node.func.value.id}.{node.func.attr}")
        assert not (imports & forbidden_import_roots), path
        assert not (calls & forbidden_calls), path

    product = ROOT / "src" / "renpy_story_mapper"
    assert not (product / "m12_export.py").exists()
    assert not (product / "m12_walkthrough.py").exists()
    assert not (product / "m12_interpretation.py").exists()
    html = (product / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert '<aside id="routePanel"' in html
    assert 'id="openRouteEvidence"' in html
    assert 'data-level="route"' not in html


def test_one_target_solve_preserves_m10_m11_and_source_and_publishes_exact_provenance(
    tmp_path: Path,
) -> None:
    project, source = _project(tmp_path)
    source_hash = hashlib.sha256((source / "story.rpy").read_bytes()).hexdigest()
    with project:
        before_m10 = {
            key: _payload_bytes(project, collection, key)
            for collection, key in (
                ("m10_analysis_state", "authoritative"),
                ("m10_canonical_graph", "authoritative"),
            )
        }
        phase_keys = tuple(
            str(row[0])
            for row in project._require_open().execute(
                "SELECT record_key FROM payloads WHERE collection='m11_phase_results' "
                "ORDER BY record_key"
            )
        )
        before_m11 = {key: _payload_bytes(project, "m11_phase_results", key) for key in phase_keys}
        service = M12RouteService(project)
        authority = load_m12_authority(project)
        destination = next(
            item
            for item in service.destinations(query="Foyer", limit=50)["nodes"]
            if item["kind"] == "generic_scene"
        )
        prepared = service.prepare(str(destination["kind"]), str(destination["target_id"]))
        outcome = service.solve(prepared)

        assert outcome.result is not None
        recommended = outcome.result["recommended"]
        assert isinstance(recommended, dict)
        provenance = recommended["provenance"]
        assert isinstance(provenance, dict)
        graph_node_ids = {item.id for item in authority.graph.nodes}
        graph_edge_ids = {item.id for item in authority.graph.edges}
        graph_fact_ids = {item.id for item in authority.graph.facts}
        scene_ids = {item.id for item in authority.scene_model.scenes}
        occurrence_ids = {item.id for item in authority.scene_model.occurrences}
        assert set(provenance["node_ids"]) <= graph_node_ids
        assert set(provenance["edge_ids"]) <= graph_edge_ids
        assert set(provenance["fact_ids"]) <= graph_fact_ids
        assert set(provenance["scene_ids"]) <= scene_ids
        assert set(provenance["occurrence_ids"]) <= occurrence_ids
        assert provenance["node_ids"] and provenance["scene_ids"]

        after_m10 = {
            key: _payload_bytes(project, collection, key)
            for collection, key in (
                ("m10_analysis_state", "authoritative"),
                ("m10_canonical_graph", "authoritative"),
            )
        }
        after_m11 = {key: _payload_bytes(project, "m11_phase_results", key) for key in phase_keys}
        rows = (
            project._require_open()
            .execute(
                "SELECT record_key FROM payloads WHERE collection=? ORDER BY record_key",
                (ROUTE_RESULTS_COLLECTION,),
            )
            .fetchall()
        )
        assert [str(row[0]) for row in rows] == [prepared.identity.cache_key]
        assert before_m10 == after_m10
        assert before_m11 == after_m11
    assert hashlib.sha256((source / "story.rpy").read_bytes()).hexdigest() == source_hash
