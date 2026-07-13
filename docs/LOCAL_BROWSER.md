# Local browser operations

Ren'Py Story Mapper is a single-user Windows application served to the system browser from a
loopback-only HTTP service. The supported product command is:

```powershell
.\.venv\Scripts\renpy-story-mapper-web.exe
```

The launcher binds only to `127.0.0.1` on an operating-system-selected port, creates per-launch
session and CSRF tokens, and opens that URL in the default browser. It serves packaged HTML, CSS,
and JavaScript without remote assets. The local page cannot supply arbitrary filesystem paths;
native Windows file and folder dialogs return selections to the Python service, which gives the
browser only short-lived opaque identifiers and a display name.

## Product workflow

1. Choose **Open Folder**, **Open Archive**, **Open File**, or **Open Project**.
2. For a new source, choose a `.rsmproj` destination outside the selected game folder.
3. Navigate the bounded **Route Map** overview.
4. Open a route element for **Detail / Evidence**, including exact source text and physical lines.
5. Use **Refresh** after the source changes. Optional organization always requires its explicit
   consent flow and does not replace deterministic graph authority.

Use **Quit** in the browser to stop the local service. If the browser was closed first, stop the
launcher with `Ctrl+C` in its terminal. For automation or diagnostics, `--no-browser` suppresses
opening the default browser while retaining the same loopback service and security policy.

The `renpy-story-mapper` command and `python -m renpy_story_mapper` remain analyzer/export tools;
they do not launch another interactive product.
