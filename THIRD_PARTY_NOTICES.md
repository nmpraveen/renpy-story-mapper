# Third-party notices

## Unrpyc minimal runtime

Ren'Py Story Mapper includes only the Unrpyc `decompiler/` runtime modules needed to reconstruct
modern `RENPY RPC2` source in the isolated recovery helper.

- Upstream: https://github.com/CensoredUsername/unrpyc
- Version: 2.0.3
- Commit: `3ae8334ed71a05535927dcc559663d3aca51215b`
- Reviewed runtime bundle SHA-256:
  `fb764521f9d3120b0c62198f086226f837802d73eccc9cad3c2ad683b1117775`
- License: MIT; the complete upstream license text is retained at
  `src/renpy_story_mapper/ingestion/_vendor/unrpyc/LICENSE.txt`.

The upstream CLI, injector, translation path, deobfuscation module, multiprocessing entry point,
tests, testcase decompiler, AST dumper, translation helper, and compiled injector artifacts are
intentionally not included or invoked. The local helper
uses the upstream safe fake-class unpickler and decompiler only after bounded modern-header and
zlib validation.
