import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const siteRoot = resolve(scriptDirectory, "..");
const projectRoot = resolve(siteRoot, "..");
const dataPath = resolve(siteRoot, "app", "workflow-map.json");

const data = JSON.parse(await readFile(dataPath, "utf8"));

try {
  data.project.commit = execFileSync(
    "git",
    ["rev-parse", "--short", "HEAD"],
    { cwd: projectRoot, encoding: "utf8" },
  ).trim();
} catch {
  // Keep the last verified commit when the parent project is unavailable.
}

data.project.updatedAt = new Date().toISOString().slice(0, 10);
await writeFile(dataPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
