#!/usr/bin/env python3
"""check-utm.py -- UTM パラメータの規約違反を検査する（読取専用）。

2026-07〜08 の GA4 で、セッションの 23%（162/711）が Unassigned（チャネル判定
不能）になっていた。原因は X 投稿の UTM が `utm_source=x` / `utm_medium=article`
だったこと。GA4 のソースカテゴリ一覧に `x` は無く、`article` はどのチャネル定義
にも一致しないため、**UTM を丁寧に付けた投稿ほど計測できなくなっていた**。
PC Watch 掲載で流入が跳ねた月に、その効果検証ができない状態だったということ。

値を1つ間違えるだけで起きる事故なので、機械で止める。

  python3 _tools/check-utm.py              # ③ の公開スコープ（内部リンクへの UTM 混入）
  python3 _tools/check-utm.py --onedrive   # ②' の投稿下書き・キャンペーン素材（全ルール）
  python3 _tools/check-utm.py --both       # 両方（②' が見つからなければ 2 で落ちる）

規約の正本は _tools/analytics/utm-policy.md、値は同ディレクトリの
utm-taxonomy.json と campaigns.json。**規約・登録簿・検査の3点で1組**。

終了コード: 0 = 違反なし / 1 = 違反あり / 2 = 環境エラー
このスクリプトは何も書き換えない。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402

# ②' 側で投稿文・キャンペーン素材が置かれる拡張子。UTM は本文に平文で現れる。
ONEDRIVE_SUFFIXES = {".md", ".html", ".htm", ".txt", ".csv"}

# ②' の走査から外すディレクトリ。退役済み・過去物・生成物は直しようがない。
ONEDRIVE_SKIP_PARTS = {
    "_archive", "_backup", "_partials_RETIRED", "_retired", "node_modules",
    ".git", "temp_resized",
}


def _iter_files(root, suffixes, skip_parts=()):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        if skip_parts and skip_parts & set(p.relative_to(root).parts):
            continue
        yield p


def _is_hub_page(rel):
    """このパスの文書自身がハブのページか（＝そこからハブ宛ての UTM は内部リンク）。

    ②' の index/ 配下はハブサイトの編集正本なのでページ扱い。Campaigns/ や
    Reviews/ の投稿下書きは外部媒体に出るものなので、ハブ宛ての UTM は正しい。
    """
    return rel == "index.html" or rel.startswith("index/") or not rel.startswith(
        ("Campaigns/", "Reviews/", "_forms/", "_Report/", "assets/"))


def targets(args):
    """[(ラベル, ルート, [パス], ハブのページ扱いか)] を走査する順に返す。"""
    out = []
    if args.hub or not args.onedrive:
        root = hublib.hub_root()
        site = hublib.site_root()
        paths = [
            p for p in sorted(site.rglob("*.html"))
            if hublib.in_published_scope(p.relative_to(site).as_posix())
        ]
        # ③ は公開物そのもの。ここに載る UTM 付きハブリンクは常に内部リンク。
        out.append(("③ 公開スコープ", root, paths, lambda rel: True))
    if args.onedrive:
        root = hublib.onedrive_root()
        if root is None:
            raise FileNotFoundError(
                "②' 00_hub_zotac が見つかりません（$HUB_ONEDRIVE_ROOT を設定してください）")
        out.append(("②' OneDrive 全体", root,
                    list(_iter_files(root, ONEDRIVE_SUFFIXES, ONEDRIVE_SKIP_PARTS)),
                    _is_hub_page))
    return out


def scan(label, root, paths, on_hub_page, taxonomy, campaigns, legacy):
    """1スコープを走査して (違反件数, 読めなかった件数, 除外件数) を返す。"""
    hits, unreadable, skipped = [], [], 0
    for p in paths:
        rel = p.relative_to(root).as_posix()
        if rel in legacy:
            skipped += 1
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            # 読めない＝清浄か違反か分からない。黙って緑にしない（fail closed）。
            unreadable.append((rel, str(e)))
            continue
        for url in hublib.find_utm_urls(text):
            problems = hublib.utm_problems(
                url, taxonomy, campaigns, on_hub_page=on_hub_page(rel))
            if problems:
                hits.append((rel, url, problems))

    print(f"check-utm: {label}  {root}")
    print(f"  走査: {len(paths)} ファイル"
          + (f"（記録として除外 {skipped}）" if skipped else ""))
    if unreadable:
        print(f"\n  読めないファイル ({len(unreadable)}) "
              "-- OneDrive の実体化待ち／同期停止の可能性:")
        for rel, err in unreadable:
            print(f"    ? {rel}  [{err}]")
    if hits:
        print(f"\n  違反 ({len(hits)}):")
        for rel, url, problems in hits:
            print(f"    ! {rel}")
            print(f"      {url}")
            for msg in problems:
                print(f"        → {msg}")
    print()
    return len(hits), len(unreadable), skipped


def main():
    hublib.use_utf8_stdout()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--onedrive", action="store_true",
                    help="②' の投稿下書き・キャンペーン素材を検査する")
    ap.add_argument("--hub", action="store_true",
                    help="③ の公開スコープを検査する（既定）")
    ap.add_argument("--both", action="store_true", help="③ と ②' の両方")
    args = ap.parse_args()
    if args.both:
        args.hub = args.onedrive = True

    try:
        taxonomy, campaigns = hublib.load_analytics()
        scopes = targets(args)
    except (OSError, ValueError) as e:
        print(f"検査できません: {e}", file=sys.stderr)
        return 2

    legacy = hublib.utm_legacy_paths(taxonomy)
    bad = unread = 0
    for label, root, paths, on_hub_page in scopes:
        b, u, _ = scan(label, root, paths, on_hub_page, taxonomy, campaigns, legacy)
        bad += b
        unread += u

    if bad:
        print("RESULT: UTM 規約違反あり")
        print("  規約: _tools/analytics/utm-policy.md")
        print("  値の登録簿: _tools/analytics/utm-taxonomy.json / campaigns.json")
        return 1
    if unread:
        print("RESULT: UNVERIFIABLE（読めないファイルがある）")
        return 1
    print("RESULT: OK（違反なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
