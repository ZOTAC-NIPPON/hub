#!/usr/bin/env python3
"""check-contamination.py -- READ-ONLY scan of (2') for SharePoint damage.

The other three completion checks compare (2') against itself or against (3),
so all three can go green while (2') itself is damaged -- which is exactly what
happened on 2026-08-02: a SharePoint document library had written its column
metadata into 185 HTML files, emptying every <title>. (3) and the live site were
clean only because no publish had run since.

This check looks at the canonical content itself:
  - SharePoint mso metadata (xmlns:mso / xmlns:msdt / mso:CustomDocumentProperties)
  - an empty or missing <title> in a full HTML document
  - a duplicate <head>, i.e. a generator inlined an already-damaged partial

Usage:
  python3 _tools/check-contamination.py            # published scope + _partials
  python3 _tools/check-contamination.py --all      # the whole 00_hub_zotac tree
  python3 _tools/check-contamination.py --hub      # scan (3) instead

Exit code: 0 = clean, 1 = contamination found, 2 = environment error.
This script never writes anything.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402


def targets(args):
    """(label, root, paths) for the requested scan scope."""
    if args.onedrive:
        root = hublib.onedrive_root()
        if root is None:
            raise FileNotFoundError(
                "(2') 00_hub_zotac not found -- set $HUB_ONEDRIVE_ROOT")
        return "(2') OneDrive whole tree", root, sorted(root.rglob("*.html"))

    # Default: this tree. Everything that is published, plus the partials --
    # the highest-risk files, since every generator inlines them.
    root = hublib.hub_root()
    site = hublib.site_root()
    paths = [
        p for p in sorted(site.rglob("*.html"))
        if hublib.in_published_scope(p.relative_to(site).as_posix())
    ]
    paths += sorted((root / "_partials").glob("*.html"))
    label = "published scope + _partials"
    if args.all:
        paths = sorted(set(paths) | set(root.rglob("*.html")))
        label = "whole tree"
    return label, root, sorted(set(paths))


def main():
    hublib.use_utf8_stdout()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--all", action="store_true", help="scan this whole tree, not just published scope")
    ap.add_argument("--onedrive", action="store_true", help="scan (2') 00_hub_zotac instead")
    args = ap.parse_args()

    try:
        label, root, paths = targets(args)
    except OSError as e:
        print(f"cannot scan: {e}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"root not found: {root}", file=sys.stderr)
        return 2

    hits, unreadable = [], []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            # Never "skip and stay green": an unreadable file is usually an
            # unmaterialised OneDrive placeholder or a stalled sync, i.e. we do
            # not know whether it is clean. Fail closed.
            unreadable.append((p.relative_to(root).as_posix(), str(e)))
            continue
        problems = hublib.contamination(text)
        if problems:
            hits.append((p.relative_to(root).as_posix(), problems))

    print(f"check-contamination: {label}  {root}")
    print(f"  scanned: {len(paths)} html files")
    print()
    if unreadable:
        print(f"UNREADABLE ({len(unreadable)}) -- cannot be verified "
              "(OneDrive placeholder not materialised / sync stalled?):")
        for rel, err in unreadable:
            print(f"  ? {rel}  [{err}]")
        print()
    if hits:
        print(f"CONTAMINATED ({len(hits)}):")
        for rel, problems in hits:
            print(f"  ! {rel}  [{', '.join(problems)}]")
        print()
    if hits or unreadable:
        print("RESULT: " + ("CONTAMINATION FOUND" if hits else "UNVERIFIABLE"))
        return 1
    print("RESULT: OK (clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
