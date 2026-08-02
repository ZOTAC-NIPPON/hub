#!/usr/bin/env python3
"""check-invariants.py -- 壊れると公開が壊れる不変条件の検査（読取専用）。

他の検査は「内容が正しいか」を見るが、これは「消えてはいけないものが
消えていないか」を見る。過去に踏んだ事故（③ をミラー同期して CNAME ごと
消し、独自ドメインが停止）と同じ形の失敗を CI で止めるのが目的。

  python3 _tools/check-invariants.py

終了コード: 0 = OK / 1 = 違反あり / 2 = 環境エラー
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402

# 消えたら公開が壊れるファイル（消失＝即座に実害）
REQUIRED = {
    "CNAME": "hub.zotac.co.jp",          # 消えると独自ドメインが停止
    "robots.txt": None,
    "favicon.ico": None,
    "google2a4e44ce4ec33d4a.html": None,  # 消えると Search Console の認証が外れる
    "index.html": None,
    "sitemap.xml": None,
    "_partials/header.html": None,
    "_partials/analytics.html": None,
    "_partials/inject.py": None,
    "_tools/hublib.py": None,
}

# git に実体を置かない方針（大容量素材は OneDrive）。逸脱を早期に検出する。
MAX_FILE_MB = 30


def tracked_files(root):
    out = subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotepath=false",
         "ls-files", "-s", "-z"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "git ls-files failed")
    for rec in out.stdout.split("\0"):
        if not rec:
            continue
        meta, _, path = rec.partition("\t")
        yield meta.split()[0], path          # (mode, path)


def main():
    hublib.use_utf8_stdout()
    root = hublib.hub_root()
    errors = []

    print(f"check-invariants: {root}")

    for rel, expected in REQUIRED.items():
        p = root / rel
        if not p.is_file():
            errors.append(f"必須ファイルが無い: {rel}")
            continue
        if expected is not None:
            actual = p.read_text(encoding="utf-8").strip()
            if actual != expected:
                errors.append(f"{rel} の内容が想定と違う: {actual!r} != {expected!r}")

    try:
        tracked = list(tracked_files(root))
    except (OSError, RuntimeError) as e:
        print(f"git を読めない: {e}", file=sys.stderr)
        return 2

    for mode, rel in tracked:
        if mode not in ("100644", "100755"):
            errors.append(f"通常ファイルでないものが追跡されている (mode {mode}): {rel}")
        p = root / rel
        if p.is_file():
            mb = p.stat().st_size / (1024 * 1024)
            if mb > MAX_FILE_MB:
                errors.append(f"{MAX_FILE_MB}MB 超のファイルが追跡されている ({mb:.1f}MB): {rel}")

    # _partials/ と _tools/ は Jekyll が除外する前提で置いている。この前提が
    # 崩れると内部ファイルが公開されるので、除外を無効化する .nojekyll を禁止する。
    if (root / ".nojekyll").exists():
        errors.append(
            ".nojekyll があると Jekyll の除外が効かず _partials/ と _tools/ が公開される")

    print(f"  追跡ファイル: {len(tracked)}")
    print()
    if errors:
        print(f"VIOLATION ({len(errors)}):")
        for e in errors:
            print(f"  ! {e}")
        print()
        print("RESULT: INVARIANT VIOLATED")
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
