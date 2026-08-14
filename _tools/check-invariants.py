#!/usr/bin/env python3
"""check-invariants.py -- 壊れると公開が壊れる不変条件の検査（読取専用）。

他の検査は「内容が正しいか」を見るが、これは「消えてはいけないものが
消えていないか」を見る。過去に踏んだ事故（③ をミラー同期して CNAME ごと
消し、独自ドメインが停止）と同じ形の失敗を CI で止めるのが目的。

  python3 _tools/check-invariants.py

終了コード: 0 = OK / 1 = 違反あり / 2 = 環境エラー
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402

# 消えたら公開が壊れるファイル（消失＝即座に実害）
REQUIRED = {
    # 独自ドメインの正本は「リポジトリ設定の Custom domain」であって
    # このファイルではない（Actions 配信では成果物の CNAME は無視される）。
    # ブランチ配信へ戻す場合の記録として保持する。
    "CNAME": "hub.zotac.co.jp",
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

# 共通ヘッダーの CSS がページ側にも残っているページ（2026-08-14 時点の棚卸し）。
# 経緯と規則は hublib.header_css_selectors の解説にある。
# ここに載っている間だけ公開を通す移行用の名簿で、**減らす方向にしか変えない**。
# 新しいページを足してはいけない（足したくなったら、それは直すべき複製）。
# 空になったらこの表ごと消す。
#
# 値は「その時点で残っていた規則の数」。単なるパス免除だと、免除中のページに
# 規則が増えても通ってしまう（Codex 指摘）。増えたら違反、減ったら「名簿を更新
# しろ」、ページ自体が消えたら「名簿から消せ」と言う。移行中の悪化も止まる。
#
# reviews/ 配下は 2026-08-14 に清掃済み。残りはカタログ生成器
# （②' の _brochure_poc/build_pages.py と catalog_*.html）と手書き 4 ページ。
HEADER_CSS_LEGACY = {
    "case-studies/index.html": 31,
    "catalogs/index.html": 32,
    "catalogs/zbox/ci655/index.html": 32,
    "catalogs/zbox/ci675/index.html": 32,
    "catalogs/zbox/eamax385c/index.html": 32,
    "catalogs/zbox/eamax395c/index.html": 32,
    "catalogs/zbox/en275060tc/index.html": 32,
    "catalogs/zbox/er98n5070c/index.html": 32,
    "catalogs/zbox/eu27506tc/index.html": 32,
    "catalogs/zbox/eu275070c/index.html": 32,
    "catalogs/zbox/eu27507tc/index.html": 32,
    "catalogs/zbox/eu275080c/index.html": 32,
    "catalogs/zbox/mi656/index.html": 32,
    "catalogs/zbox/mi676/index.html": 32,
    "catalogs/zbox/qu27n5000/index.html": 32,
    "catalogs/zbox/s35n150a/index.html": 32,
    "catalogs/zbox/s35n150p/index.html": 32,
    "index.html": 33,
    "press/index.html": 32,
    "trial-program/index.html": 33,
}


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


def nav_toggle_violations(root, tracked):
    """モバイルナビの開閉ハンドラが二重登録されていないかを見る。

    2026-08-13 まで、共通ヘッダーとページ側の両方に同じ開閉スクリプトが
    あり、1クリックで「開く→閉じる」が相殺してハンバーガーが無反応だった
    （公開31ページ）。ページ側の実装には再登録ガードが無かったため、
    partial 側のガードでは止まらなかった。

    規則: `.nav-toggle` に click を登録するスクリプトは、必ず
    `dataset.bound` の再登録ガードを持つこと。ヘッダーの構成要素は
    1ページに1個ずつであること。
    """
    out = []
    for _mode, rel in tracked:
        if not rel.endswith(".html") or rel.startswith("_"):
            continue
        p = root / rel
        if not p.is_file():
            continue
        s = p.read_text(encoding="utf-8", errors="replace")
        if 'class="nav-toggle"' not in s:
            continue
        for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", s, re.S):
            body = m.group(1)
            if ("nav-toggle" in body
                    and re.search(r"addEventListener\(\s*['\"]click", body)
                    and "dataset.bound" not in body):
                out.append(f"再登録ガードの無いナビ開閉スクリプトがある: {rel}")
        counts = (
            len(re.findall(r'<header[^>]*class="[^"]*site-header', s)),
            len(re.findall(r'id="site-nav"', s)),
            len(re.findall(r'class="nav-toggle"', s)),
        )
        if counts != (1, 1, 1):
            out.append(
                "ヘッダー要素が1個ずつでない "
                f"(site-header/#site-nav/.nav-toggle = {counts}): {rel}")
        # 生成器が partial をマーカー無しで焼き込むと、inject が別途マーカー範囲を
        # 挿入し、ヘッダーの CSS/JS だけがページ内に二重で残る（GPU カタログ16ページ）。
        # 見た目は正常なので、共通ヘッダー CSS の個数で検出する。
        css = len(re.findall(r"=== ZOTAC hub 共通ヘッダー", s))
        if css != 1:
            out.append(f"共通ヘッダーの CSS が {css} 個ある（1 個であること）: {rel}")
    return out


def _stylesheet_reader(root, rel):
    """ページ rel が読み込むローカル CSS を読む関数を返す（外部URLは None）。"""
    def read(href):
        href = unquote(href.split("?")[0].split("#")[0])
        p = (root / href.lstrip("/")) if href.startswith("/") else (root / rel).parent / href
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return read


def header_css_violations(root):
    """共通ヘッダーの CSS がページ側にも書かれていないかを見る。

    追跡済みファイルではなく作業ツリーを見る。publish は「取り込み → 反映 →
    検査」の順なので、②' から入ってきたばかりの未追跡ページこそ検査したい。
    対象の定義は注入器と共有する（hublib.injected_pages）。
    """
    out, seen = [], set()
    for rel in hublib.injected_pages(root):
        hits = hublib.header_css_selectors(
            (root / rel).read_text(encoding="utf-8", errors="replace"),
            _stylesheet_reader(root, rel))
        allowed = HEADER_CSS_LEGACY.get(rel)
        if allowed is not None:
            seen.add(rel)
        if not hits:
            if allowed is not None:
                out.append(f"HEADER_CSS_LEGACY に載っているが既に清浄。"
                           f"名簿から消すこと: {rel}")
            continue
        if allowed is None:
            out.append(f"共通ヘッダーの CSS がページ側にもある（{len(hits)} 規則。"
                       f"例: {hits[0]}）。_partials/header.html へ寄せること: {rel}")
        elif len(hits) > allowed:
            out.append(f"移行中のページで複製が増えている（{allowed} → {len(hits)} 規則。"
                       f"例: {hits[0]}）: {rel}")
        elif len(hits) < allowed:
            out.append(f"複製が減っている。HEADER_CSS_LEGACY の値を {allowed} から "
                       f"{len(hits)} へ更新すること: {rel}")
    for rel in sorted(set(HEADER_CSS_LEGACY) - seen):
        out.append(f"HEADER_CSS_LEGACY にあるページが存在しない。名簿から消すこと: {rel}")
    return out


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

    errors.extend(nav_toggle_violations(root, tracked))
    errors.extend(header_css_violations(root))

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
