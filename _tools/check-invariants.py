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

# 共通ヘッダーの CSS がページ側にも残っているページ。経緯と規則は
# hublib.header_css_selectors の解説にある。
#
# 2026-08-14 に公開30ページすべての移行が終わったので空にした。**ここに新しい
# ページを足さないこと** — 足したくなったら、それは直すべき複製の方。
# 移行中は {パス: 規則数} で「増えたら違反・減ったら値を更新」を回していた
# （単なるパス免除だと免除中の悪化が通る、という Codex 指摘への対応）。
# 同じ移行をまたやるならその形に戻す。
HEADER_CSS_LEGACY = {}


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


def title_violations(root):
    """`<title>` が規約（_tools/seo/title-policy.md）に合っているかを見る。

    戻り値 = (公開を止める違反, 報告だけの指摘)。Phase 0 では移行中なので前者は
    「登録簿そのものの腐り」だけにし、ページの型違反は後者に入れる（レポート
    モード）。公開停止への昇格は Phase 2。

    frozen と migration を区別するのが要点。migration はページが適合したら名簿
    から消させるが、frozen は適合していても残す ―― 成果の出ているページを将来の
    「改善」から守るのが目的で、未処理の負債ではないため。
    """
    reg = hublib.load_title_registry(root)
    frozen = reg.get("frozen", {})
    migration = {k: v for k, v in reg.get("migration", {}).items()
                 if not k.startswith("_")}

    hard, report = [], []
    titles, seen_migration, backlog = {}, set(), []

    for rel in hublib.injected_pages(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        title = hublib.page_title(text)
        problems = hublib.title_problems(rel, title)

        # コメント内の <title> は登録簿で免除しない。正規表現でタイトルを読む
        # 道具を壊し、実タイトルを直しても毎回「壊れている」と再発見される
        # （title-policy.md §6 の事故そのもの）。
        if hublib.title_in_comment(text):
            hard.append(f"HTML コメントの中に <title> がある（抽出器が壊れる）: {rel}")

        if rel in frozen:
            continue                     # frozen は型違反を報告しない（レビュー対象外）
        if rel in migration:
            seen_migration.add(rel)
            if not problems:
                hard.append("title-registry.json の migration に載っているが既に"
                            f"規約に適合。名簿から消すこと: {rel}")
            else:
                backlog.append((migration[rel].get("review_by", "期限なし"), rel))
            continue

        for msg in problems:
            report.append(f"{msg}: {rel}")
        if title:
            titles.setdefault(title.strip(), []).append(rel)

    for rel in sorted(set(migration) - seen_migration):
        hard.append("title-registry.json の migration にあるページが存在しない。"
                    f"名簿から消すこと: {rel}")
    for rel in sorted(frozen):
        if not (root / rel).is_file():
            hard.append("title-registry.json の frozen にあるページが存在しない。"
                        f"名簿から消すこと: {rel}")

    for title, rels in sorted(titles.items()):
        if len(rels) > 1:
            report.append(f"タイトルが重複している（{title}）: {' / '.join(rels)}")

    # 期限なしの migration は永久 lag になるので、名簿の欠陥として必ず挙げる。
    for review_by, rel in backlog:
        if review_by == "期限なし":
            hard.append("title-registry.json の migration に review_by が無い"
                        f"（期限の無い移行は終わらない）: {rel}")

    return hard, report, backlog


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

    title_hard, title_report, title_backlog = title_violations(root)
    errors.extend(title_hard)

    print(f"  追跡ファイル: {len(tracked)}")
    # Phase 0 はレポートのみ（公開を止めない）。公開停止への昇格は Phase 2
    # （title-policy.md §7）。登録簿に無い違反＝新しく増えたものなので目立たせる。
    if title_report:
        print()
        print(f"  ▲ タイトル規約の未登録違反（報告のみ・公開は止めません）: {len(title_report)} 件")
        for msg in title_report:
            print(f"    - {msg}")
        print("    直すか、_tools/seo/title-registry.json の migration へ期限付きで登録すること")
    if title_backlog:
        # 名簿を「検査を黙らせるゴミ箱」にしないため、残数と期限を常に見せる。
        print()
        print(f"  タイトル規約の移行残り: {len(title_backlog)} 件"
              "（登録済み・_tools/seo/title-registry.json）")
        by_date = {}
        for review_by, rel in title_backlog:
            by_date.setdefault(review_by, []).append(rel)
        for review_by in sorted(by_date):
            rels = by_date[review_by]
            # 表示用の短縮。ルート直下の index.html はディレクトリ名を持たない。
            def short(r):
                parts = r.split("/")
                return parts[-2] if len(parts) > 1 else r
            head = ", ".join(short(r) for r in sorted(rels)[:3])
            more = f" ほか{len(rels) - 3}件" if len(rels) > 3 else ""
            print(f"    期限 {review_by}: {len(rels):2d} 件  （{head}{more}）")
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
