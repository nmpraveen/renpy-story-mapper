# Third-party notices

## Unrpyc minimal runtime

Ren'Py Story Mapper includes only the Unrpyc `decompiler/` runtime modules needed to reconstruct
modern `RENPY RPC2` source in the isolated recovery helper.

- Upstream: https://github.com/CensoredUsername/unrpyc
- Upstream tag: `v2.0.4`
- Upstream internal version string: `2.0.3`
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

## tiktoken

Ren'Py Story Mapper uses OpenAI's `tiktoken` package to count the exact product-owned Codex input
before starting the provider process.

- Upstream: https://github.com/openai/tiktoken
- License: MIT
- Copyright: OpenAI and Shantanu Jain

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
