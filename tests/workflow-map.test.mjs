import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const map = JSON.parse(
  await readFile(new URL("../app/workflow-map.json", import.meta.url), "utf8"),
);

test("every workflow link connects two real boxes", () => {
  const nodeIds = new Set(map.nodes.map((node) => node.id));
  const edgeIds = new Set();

  for (const edge of map.edges) {
    assert.ok(!edgeIds.has(edge.id), `duplicate link id: ${edge.id}`);
    edgeIds.add(edge.id);
    assert.ok(nodeIds.has(edge.source), `missing source box: ${edge.source}`);
    assert.ok(nodeIds.has(edge.target), `missing target box: ${edge.target}`);
    assert.notEqual(edge.source, edge.target, `self-link: ${edge.id}`);
  }
});

test("the current Phase 01 dependency links match the accepted workflow", () => {
  const actual = map.edges
    .map((edge) => `${edge.source}->${edge.target}${edge.kind ? `:${edge.kind}` : ""}`)
    .sort();
  const expected = [
    "ai-analysis->final-validator",
    "ai-profile->ai-analysis",
    "branch-ownership->coverage-audit",
    "canonical-schemas->final-validator",
    "coverage-audit->final-validator",
    "evidence-index->ai-analysis",
    "evidence-index->ai-profile",
    "evidence-index->coverage-audit",
    "final-validator->ai-analysis:feedback",
    "final-validator->five-files",
    "five-files->browser-inspection",
    "game-folder->recover-scripts",
    "parser-annotations->evidence-index",
    "path-redaction->five-files",
    "provider-transport->ai-analysis",
    "provider-transport->ai-profile",
    "recover-scripts->script-lines",
    "script-lines->evidence-index",
    "status-rule->final-validator",
  ].sort();

  assert.deepEqual(actual, expected);
});

test("box fill ownership is explicit and accurate", () => {
  const byExecutor = Object.groupBy(map.nodes, (node) => node.executor);

  assert.deepEqual(
    byExecutor.ai.map((node) => node.id).sort(),
    ["ai-analysis", "ai-profile"],
  );
  assert.deepEqual(
    byExecutor.browser.map((node) => node.id),
    ["browser-inspection"],
  );
  assert.equal(byExecutor.python.length, map.nodes.length - 3);
  assert.equal(byExecutor.undefined, undefined);
});
