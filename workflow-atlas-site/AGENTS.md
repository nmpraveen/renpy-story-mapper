# Workflow Atlas repository rules

This directory is the Git subtree source for the private Ren'Py Workflow Atlas. The parent Ren'Py
repository is the only local source of truth. Do not initialize a nested Git repository here and do
not push the parent repository branch directly to the Sites source remote.

Only the active-phase coordinator may edit or publish this site during coordinated work. Worker tasks
report their node or workstream, status, evidence or commit, and safe failure summary to the
coordinator. They do not change `app/workflow-map.json`, site code, Git history, or deployments.

Before publishing:

1. Update accepted plans and every material `not-built`, `in-progress`, `passed`, `failed`, or
   `attention` transition in `app/workflow-map.json`.
2. Run the site lint, production build, focused tests, and `git diff --check`.
3. Commit the parent repository change.
4. Split the committed subtree with `git subtree split --prefix=workflow-atlas-site` and push that
   split commit to the existing Sites source repository using a short-lived Sites credential.
5. Package and save the validated site version using the split commit SHA, then deploy privately.

Never publish prompts, credentials, private payloads, generated canary files, or absolute local paths.
