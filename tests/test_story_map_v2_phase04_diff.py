# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_reader_contract_v1.json"
V2_FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_reader_contract_v2.json"
MODULE = ROOT / "src" / "renpy_story_mapper" / "web" / "static" / "story-map-v2-diff.js"
MANIFEST = MODULE.parent / "asset-manifest.json"


def _node(source: str) -> dict[str, object]:
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", source],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_reader_diff_consumes_frozen_v1_without_deriving_new_from_wording() -> None:
    source = f"""
      import fs from 'node:fs';
      import {{ pathToFileURL }} from 'node:url';
      const m = await import(pathToFileURL({json.dumps(str(MODULE))}));
      const fixture = JSON.parse(fs.readFileSync({json.dumps(str(FIXTURE))}, 'utf8'));
      const extension = JSON.parse(fs.readFileSync({json.dumps(str(V2_FIXTURE))}, 'utf8'));
      const contract = {{ ...fixture, schema: extension.schema, extends: extension.extends, delta: extension.delta }};
      m.validateReaderContract(contract);
      fixture.examples.manifest.schema = extension.schema;
      const current = m.presentReaderDiff(fixture.examples.manifest, fixture.examples.view_state.state);
      const wordingOnly = structuredClone(fixture.examples.manifest);
      wordingOnly.overview.title = 'Completely different wording';
      wordingOnly.sections[0].title = 'Renamed without structural change';
      wordingOnly.sections[0].summary = 'Changed summary only.';
      const changed = m.presentReaderDiff(wordingOnly, fixture.examples.view_state.state);
      const arm = m.presentNew(fixture.examples.branch_page.items[1]);
      const hidden = m.presentNew(fixture.examples.branch_page.items[1], {{ hideNew: true }});
      console.log(JSON.stringify({{
        schema: contract.schema,
        current: current.freshness,
        wordingSame: JSON.stringify(current.sections) === JSON.stringify(changed.sections),
        unchangedVisible: current.sections[0].presentation.visible,
        apiNew: arm,
        hidden,
        staleRevision: m.staleRevisionFromResponse(409, fixture.examples.stale_error),
      }}));
    """
    result = _node(source)

    assert result["schema"] == "story-map-v2-reader-contract-v2"
    assert result["current"] == {"key": "current", "label": "Current", "is_stale": False}
    assert result["wordingSame"] is True
    assert result["unchangedVisible"] is False
    assert result["apiNew"]["visible"] is True
    assert result["apiNew"]["label"] == "NEW"
    assert result["hidden"]["visible"] is False
    assert result["hidden"]["is_new"] is True
    assert result["hidden"]["facts"] == result["apiNew"]["facts"]
    assert result["staleRevision"] == 8


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_reader_diff_fails_closed_for_conflicting_api_new_fields() -> None:
    source = f"""
      import {{ pathToFileURL }} from 'node:url';
      const m = await import(pathToFileURL({json.dumps(str(MODULE))}));
      let rejected = 0;
      for (const value of [
        {{ is_new: true, new_facts: [] }},
        {{ is_new: false, new_facts: [{{ kind: 'arm', fact_id: 'arm:x' }}] }},
        {{ is_new: true }},
      ]) {{
        try {{ m.presentNew(value); }} catch (error) {{ if (error instanceof TypeError) rejected += 1; }}
      }}
      console.log(JSON.stringify({{ rejected }}));
    """
    assert _node(source) == {"rejected": 3}


def test_reader_diff_is_a_packaged_local_asset_with_current_hash() -> None:
    asset_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "story-map-v2-diff.js" in asset_manifest["assets"]
    canonical = MODULE.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    assert (
        hashlib.sha256(canonical.encode()).hexdigest()
        == asset_manifest["assets"]["story-map-v2-diff.js"]
    )
    assert "http://" not in canonical and "https://" not in canonical
    assert "innerHTML" not in canonical and "eval(" not in canonical
