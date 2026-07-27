"""The committed `frontend/dist` bundle is the real UI. This test guards it.

`backend/app/main.py` serves `frontend/dist` for every non-`/api` path, and the
README promises "a committed frontend build so cloning needs only Python". That
makes the bundle a source artifact, not a byproduct: whatever is committed under
`frontend/dist` is what a user actually runs.

Nothing else in either suite reads it. pytest exercises the backend, vitest
imports `frontend/src` directly, and neither ever opens the built asset. So a
commit that changes `frontend/src` without re-running `npm run build` ships a
stale UI with the whole suite green. That is not hypothetical: on this branch,
commits 61f01c9, 8509609, 4642276 and d956901 each changed `frontend/src` while
the committed bundle stayed at the pre-registry build. Anyone cloning at any of
those four commits got dropdowns offering four templates instead of eight and no
template switcher at all.

The guard: `npm run build` records a hash of every file the bundle is built from
into `frontend/dist/build-inputs.sha256`; this test recomputes those hashes and
fails when they disagree. Editing a source file without rebuilding fails here,
and names the files that moved on.

Two deliberate choices:

- Line endings are normalized to LF before hashing. `core.autocrlf` is true and
  `.gitattributes` says nothing about `.ts`/`.tsx`, so the same commit has CRLF
  in a Windows working tree and LF in a Linux one. Hashing raw bytes would make
  a correctly built bundle fail on the other platform.
- Test files are excluded. Vite's entry graph starts at `index.html` and reaches
  only production modules, so `*.test.tsx` and `test-setup.ts` cannot change the
  emitted asset; hashing them would demand a pointless rebuild after every
  test-only commit.

What this does not catch: rebuilding and then committing without `git add
frontend/dist`. That leaves the working tree passing while the commit is stale.
It also leaves `git status` dirty, which is the signal for that one.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from backend.app.main import FRONTEND_DIST

FRONTEND = FRONTEND_DIST.parent
STAMP = FRONTEND_DIST / "build-inputs.sha256"

# Files outside src/ that the emitted bundle depends on. Dependency versions are
# an input too: an `npm install` that bumps react or vite changes the output, so
# package.json and the lockfile are hashed alongside the code.
ROOT_INPUTS = (
    "index.html",
    "vite.config.ts",
    "tsconfig.json",
    "package.json",
    "package-lock.json",
)

REBUILD = "cd frontend && npm run build"


def _is_test_source(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == "test-setup.ts" or ".test." in name


def _digest(path: Path) -> str:
    """sha256 of the file with CRLF normalized to LF, so the hash is portable."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def build_inputs(frontend: Path) -> dict[str, str]:
    """Every file the built bundle depends on -> its normalized sha256.

    `frontend/scripts/stamp-build.mjs` mirrors this exactly. The two are kept
    honest by comparison rather than by trust: this test diffs the whole path
    set, so a file either side collects and the other does not shows up as a
    named added/missing entry rather than silently weakening the hash.
    """
    inputs: dict[str, str] = {}
    for name in ROOT_INPUTS:
        candidate = frontend / name
        if candidate.is_file():
            inputs[name] = _digest(candidate)
    for path in sorted((frontend / "src").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(frontend).as_posix()
        if _is_test_source(rel):
            continue
        inputs[rel] = _digest(path)
    return inputs


def parse_stamp(text: str) -> dict[str, str]:
    """Read `sha256␠␠path` lines, the shape `sha256sum` itself emits."""
    recorded: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        recorded[rel] = digest
    return recorded


def test_stamp_file_exists():
    assert STAMP.is_file(), (
        f"{STAMP} is missing. It is written by `npm run build`; without it "
        f"nothing can tell whether the committed bundle matches the sources. "
        f"Run: {REBUILD}"
    )


def test_committed_bundle_was_built_from_the_committed_sources():
    current = build_inputs(FRONTEND)
    recorded = parse_stamp(STAMP.read_text(encoding="utf-8"))

    changed = sorted(k for k in current.keys() & recorded.keys() if current[k] != recorded[k])
    added = sorted(current.keys() - recorded.keys())
    removed = sorted(recorded.keys() - current.keys())

    assert not (changed or added or removed), (
        "frontend/dist is stale: it was built from different sources than the "
        "ones committed here, so the UI a user gets is not the UI in "
        f"frontend/src.\n  changed since the build: {changed or 'none'}\n"
        f"  new, never built: {added or 'none'}\n"
        f"  built from, now gone: {removed or 'none'}\n"
        f"Fix: {REBUILD}"
    )


def test_dist_index_references_assets_that_exist():
    """A half-committed dist: index.html naming assets that were never added."""
    index = FRONTEND_DIST / "index.html"
    assert index.is_file(), f"{index} is missing. Run: {REBUILD}"

    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
    assert refs, f"{index} references no build assets at all. Run: {REBUILD}"

    missing = [ref for ref in refs if not (FRONTEND_DIST / ref.lstrip("/")).is_file()]
    assert not missing, (
        f"frontend/dist/index.html points at assets that are not in dist: "
        f"{missing}. The build output was committed incompletely. Fix: {REBUILD}"
    )
