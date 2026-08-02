#!/usr/bin/env python3
"""pre-commit-hub.py -- READ-ONLY guard run by the pre-commit hook in (3).

Purpose: block commits in the deploy repo (3) that cannot have come through the
sanctioned path. For every staged change it verifies that a counterpart exists
in (2'), that the blob is a regular file, and that no SharePoint contamination
is being committed. Staged deletions must already be deleted in (2') as well.
Deploy-only files (allowlist, HUB.md sec.2) are exempt from needing a
counterpart, but never from the content checks.

Content is NOT compared byte-for-byte against (2') any more -- see the comment
in main(). (3) is a derived artifact, not a mirror.

Unlike check-hub-drift.py (full-tree audit), this only inspects STAGED changes,
so unrelated work-in-progress in (2') never blocks a commit.

What is compared is the STAGED BLOB, not the working-tree file: `git add`ing a
bad version and then restoring the working tree would otherwise slip through
(a flaw inherited from the original pre-commit-hub.ps1).

Also refuses to commit SharePoint-contaminated HTML, so a damaged (2') cannot
reach GitHub Pages even if the content matches on both sides.

Exit code: 0 = ok to commit, 1 = blocked, 2 = environment error (also blocks).

Cross-platform replacement for pre-commit-hub.ps1 (pwsh/Windows only).
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402

# Blob modes git may report. Anything else (symlink 120000, submodule 160000)
# has no meaning as a mirrored page and is refused.
REGULAR_MODES = {"100644", "100755"}


def git(hub, *args, binary=False):
    out = subprocess.run(
        ["git", "-C", str(hub), "-c", "core.quotepath=false", *args],
        capture_output=True,
    )
    if out.returncode != 0:
        msg = out.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(msg or f"git {' '.join(args)} failed")
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def staged_changes(hub):
    """Parse `git diff --cached --raw -z` into (status, mode, sha, path, old_path).

    The raw format carries the mode and blob sha that will actually be
    committed, and -z keeps non-ASCII paths intact. Renames (R) and copies (C)
    carry two paths; every other status carries one.
    """
    raw = git(hub, "diff", "--cached", "--raw", "-z", "--diff-filter=ACMRTD")
    fields = raw.split("\0")
    i, changes = 0, []
    while i < len(fields):
        head = fields[i]
        if not head.startswith(":"):
            i += 1
            continue
        # :<srcmode> <dstmode> <srcsha> <dstsha> <status>
        parts = head[1:].split()
        dst_mode, dst_sha, status = parts[1], parts[3], parts[4]
        if status[0] in ("R", "C"):
            old_path, path = fields[i + 1], fields[i + 2]
            i += 3
        else:
            old_path, path = None, fields[i + 1]
            i += 2
        changes.append((status[0], dst_mode, dst_sha, path, old_path))
    return changes


def main():
    hublib.use_utf8_stdout()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--hub", help="path to the (3) deploy repo")
    args = ap.parse_args()

    index = hublib.index_path()
    hub = hublib.deploy_path(args.hub)

    if not index.is_dir():
        print(f"pre-commit: editing canonical not found (OneDrive offline?): {index}")
        print("pre-commit: refusing to commit without verification.")
        return 2

    try:
        changes = staged_changes(hub)
    except (OSError, RuntimeError, IndexError) as e:
        print(f"pre-commit: cannot read the staging area: {e}")
        print("pre-commit: refusing to commit without verification.")
        return 2

    errors = []

    def check_absent(rel, why):
        if (index / rel).exists():
            errors.append(f"{why}, but the file still exists in (2') index: {rel}")

    for status, mode, sha, rel, old_rel in changes:
        # A rename moves the old path away: (2') must no longer have it.
        if old_rel is not None and not hublib.is_deploy_only(old_rel):
            check_absent(old_rel, "staged rename away from this path")

        if status == "D":
            if not hublib.is_deploy_only(rel):
                check_absent(rel, "staged deletion")
            continue

        # The allowlist exempts a path from needing a (2') counterpart. It must
        # NOT exempt it from checks on the content itself -- _partials/ is both
        # allowlisted and the very thing SharePoint contaminated, so letting the
        # allowlist skip the scan would leave the guard blind where it matters
        # most.
        if mode not in REGULAR_MODES:
            errors.append(f"staged as a non-regular file (mode {mode}): {rel}")
            continue

        try:
            blob = git(hub, "cat-file", "blob", sha, binary=True)
        except (OSError, RuntimeError) as e:
            errors.append(f"cannot read the staged blob for {rel}: {e}")
            continue

        if hublib.is_markup(rel):
            for problem in hublib.contamination_of_bytes(blob):
                errors.append(f"contaminated, must not be published [{problem}]: {rel}")

        if hublib.is_deploy_only(rel) or rel in hublib.GENERATED_IN_HUB:
            continue        # git 正本 / deploy 専用 / ③ 側の生成物

        # 対応するファイルが (2') に存在すること。ここは維持する
        # ――③ にだけ勝手に増やしたファイルを検出できる。
        src = index / rel
        if src.is_symlink() or not src.is_file():
            errors.append(f"staged but missing (or not a regular file) in (2') index: {rel}")
            continue

        # 【2026-08-02 に内容のバイト照合を廃止】
        #
        # 「③ は ②' のバイト単位のミラー」という前提が成り立たなくなったため。
        # 現在の ③ の HTML は ②' の派生物で、取り込みまでに 3 つの変換が入る:
        #   1. SharePoint 汚染の除去（sanitize）
        #   2. <title> の復元（og:title もしくは ③ の既存値から）
        #   3. inject による共通パーツの置換
        #      （②' はマーカー無しで直接埋め込み、③ はマーカー付き）
        # 3 を正しく照合するにはフック内で inject を再実装する必要があり、
        # 実装を二重に持てば必ずずれる。今日 5 回パッチして、いずれも局所的には
        # 正しく構造的には不十分だった。
        #
        # 通らないガードは --no-verify を誘発して形骸化するので、成立しない
        # 検査は畳む。ここで守るべき「壊れたものを公開しない」は、内容そのものを
        # 見る検査（汚染検査・inject --check・sitemap --check・不変条件）と
        # CI＋ブランチ保護が担う。「③ を手編集しない」は hub.py import を唯一の
        # 経路にすることと、PR で差分が見えることで担保する。

    if errors:
        print("pre-commit: commit blocked -- (3) must mirror a clean (2'). See HUB.md sec.2.")
        for e in errors:
            print(f"  ! {e}")
        print("Fix: edit in (2') OneDrive index, copy the changed files here, then commit.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
