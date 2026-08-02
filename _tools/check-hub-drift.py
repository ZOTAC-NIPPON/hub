#!/usr/bin/env python3
"""check-hub-drift.py -- READ-ONLY consistency check between
  (2') OneDrive editing canonical:  00_hub_zotac/index/
  (3)  git deploy mirror:           ~/Documents/projects/hub/

Rule (HUB.md sec.2): (3) = mirror of (2') plus a fixed allowlist of deploy-only
files. Anything else that exists only in (3) is drift (evidence of editing (3)
directly). Files only in (2') are treated as "pending publish" (informational,
not an error).

Usage:
  python3 _tools/check-hub-drift.py              # from 00_hub_zotac (or anywhere)
  python3 _tools/check-hub-drift.py --hub <path> # override the (3) path

Exit code: 0 = clean, 1 = drift found (DIFF or ONLY-IN-HUB).
This script never writes anything.

Cross-platform replacement for check-hub-drift.ps1 (pwsh/Windows only).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402


def main():
    hublib.use_utf8_stdout()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--hub", help="path to the (3) deploy repo")
    args = ap.parse_args()

    index = hublib.index_path()
    hub = hublib.deploy_path(args.hub)

    if not index.is_dir():
        print(f"index not found: {index}", file=sys.stderr)
        return 2
    if not hub.is_dir():
        print(f"hub not found: {hub}", file=sys.stderr)
        return 2

    i_files = hublib.rel_files(index)
    h_files = hublib.rel_files(hub)
    i_set, h_set = set(i_files), set(h_files)

    diff, pending, only_hub, allowed = [], [], [], []

    for f in i_files:
        if f in h_set:
            if not hublib.same_content(index / f, hub / f):
                diff.append(f)
        elif f not in hublib.ALLOW_INDEX_ONLY:
            pending.append(f)

    for f in h_files:
        if f not in i_set:
            (allowed if hublib.is_deploy_only(f) else only_hub).append(f)

    print(f"check-hub-drift: (2') {index}  vs  (3) {hub}")
    print(f"  compared: {len(i_files)} index files / {len(h_files)} hub files")
    print()

    if diff:
        print(f"DIFF ({len(diff)}) -- same path, different content. Re-copy (2') -> (3):")
        for f in diff:
            print(f"  ! {f}")
        print()
    if only_hub:
        print(f"ONLY-IN-HUB ({len(only_hub)}) -- not in allowlist. (3) was edited directly?")
        for f in only_hub:
            print(f"  ! {f}")
        print()
    if pending:
        print(f"PENDING ({len(pending)}) -- only in (2'), not published yet (info only):")
        for f in pending:
            print(f"  . {f}")
        print()
    if allowed:
        print(f"allowlisted deploy-only files present in (3): {len(allowed)}")

    if diff or only_hub:
        print()
        print("RESULT: DRIFT FOUND")
        return 1
    print("RESULT: OK (no drift)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
