#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sitemap.xml 自動生成 — index/ のファイル実体を唯一のソースにする。

目的:
  sitemap.xml の手書き運用をやめる。手書きだと (a) 新規公開ページの載せ忘れ、
  (b) 削除済み URL の載せっぱなし（404 混入）が構造的に起きる。
  実際 2026-07 時点で未掲載 8 ページ／404 1 件（catalogs/zbox/eamax390c）が発生していた。
  ※ 本ファイルは 00_hub_zotac\\_tools\\ に置く（ハブ全体の正本。実行は 00_hub_zotac で）。

使い方:
  cd 00_hub_zotac
  python _tools/gen-sitemap.py             # index/sitemap.xml を再生成
  python _tools/gen-sitemap.py --check     # 差分が出るか確認のみ（書き込まない・CI/監査用）
  python _tools/gen-sitemap.py --verify    # 本番 URL に HTTP アクセスして 404 混入を検査
  python _tools/gen-sitemap.py --check --verify

収録ルール:
  - index/ 配下の *.html を走査（_ 始まりフォルダは除外＝inject.py と同じ基準）
  - <meta name="robots" ... noindex ...> のページは除外（例: catalogs/zbox/index.html の旧URLスタブ）
  - canonical が自分自身以外を指すページは除外（重複ページを sitemap に載せない）
  - index.html → ディレクトリ URL（/catalogs/zbox/ci655/）、それ以外 → ファイル URL
  - PDF 等 HTML 以外は EXTRA_URLS に明示（自動収録しない。pdfs/ 配下を全部載せないため）

lastmod:
  既存 sitemap.xml にある URL はその値を引き継ぐ（＝公開日として手当てした値を壊さない）。
  新規 URL はファイルの更新日時を使う。特定 URL を固定したい場合は LASTMOD_OVERRIDE に書く。
"""
import re
import sys
import pathlib
import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent      # .../00_hub_zotac
# 公開サイトのルート。OneDrive 側は ROOT/index/、deploy リポジトリ（③）では
# ROOT 自身がサイトのルート（2026-08-02 の git 正本化に対応）。
SITE = (ROOT / "index") if (ROOT / "index").is_dir() else ROOT

# --- 実行場所のガード ---------------------------------------------------
# このスクリプトは deploy リポジトリ（③）の中でしか動かない。②' の OneDrive
# 側で実行すると、SharePoint に汚染された共通パーツを全ページへ配ってしまう
# （2026-08-02 に実際に起きた。退役させたファイルが復元・再コピーされれば
# 同じ事故を再現できるため、コード側で拒否する）。
if not ((ROOT / ".git").exists() and (ROOT / "_tools" / "hublib.py").is_file()):
    sys.stderr.write(
        f"このスクリプトは deploy リポジトリの中でしか実行できません。\n"
        f"  実行しようとした場所: {ROOT}\n"
        f"  ②' の OneDrive 側で動かすと、汚染された共通パーツを全ページへ配ります。\n"
        f"  ③ へ移動して実行してください（例: cd ~/Developer/hub）。\n")
    sys.exit(2)

OUT = SITE / "sitemap.xml"
BASE = "https://hub.zotac.co.jp"

# deploy 専用ファイル（GSC 検証用 HTML 等）はページではないので載せない。
# 許容リストの実装正本は _tools/hublib.py（HUB.md §2 と同期）。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hublib import is_deploy_only as _is_deploy_only   # 見つからなければ落ちてよい

# ── HTML 以外で収録したい URL（明示のみ）──────────────────────────────
# パスは SITE からの相対。存在しないものは警告して落とす（404 を sitemap に載せない）。
EXTRA_URLS = [
    ("pdfs/ZOTAC_Enterprise_Catalog_MAY_2026.pdf", "2026-06-16"),
]

# ── lastmod を固定したい URL パス（"/reviews/" 形式）→ 日付 ──────────
LASTMOD_OVERRIDE = {}

# ── ②' に実体はあるが「まだ公開していない」ページ（sitemap から除外）─────
# 未公開ページを sitemap に載せると 404 を申告することになるため、ここで明示除外する。
# 公開したら該当行を消すこと（--verify で 200 を確認してから）。
PENDING_PUBLISH = {
    # 2026-08-02: エンタープライズ 12 ページを公開したため一覧から削除。
    # 残る enterprise_catalog_may_2026_a4 は総合PDFから誤生成された偽製品ページ
    # （sku="WORKSTATION &"）＝公開対象ではない。生成器側を直して削除する。
    "/catalogs/enterprise/enterprise_catalog_may_2026_a4/",
}

# ── 出力順とセクション見出しコメント（前方一致・先に書いたものが優先）──
# ここに載らないパスは末尾に「その他」としてパス順で出力される（載せ忘れが目視で分かる）。
SECTIONS = [
    ("/",                     None),
    ("/catalogs/",            "製品カタログ インデックス"),
    ("/catalogs/zbox/",       "ZBOX 製品カタログ（SEO/AIO の主資産＝HTML）"),
    ("/catalogs/gpu/",        "GeForce RTX 製品カタログ"),
    ("/catalogs/enterprise/", "Enterprise / GPU ワークステーション 製品カタログ"),
    ("/pdfs/",                "PDF 資産（EXTRA_URLS で明示収録）"),
    ("/reviews/",             "レビュー（一覧＋個別記事）"),
    ("/case-studies/",        "導入・活用事例"),
    ("/press/",               "メディア掲載"),
    ("/trial-program/",       "機材トライアルプログラム"),
    ("/events/",              "イベント"),
]

NOINDEX_RE = re.compile(r'<meta\s+name=["\']robots["\']\s+content=["\'][^"\']*noindex', re.I)
CANONICAL_RE = re.compile(r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']', re.I)


def page_urls():
    """index/ 配下の公開 HTML → (url_path, lastmod_date, source_path)。除外理由は skipped に積む。"""
    found, skipped = [], []
    for p in sorted(SITE.rglob("*.html")):
        rel = p.relative_to(SITE)
        if any(part.startswith(("_", ".")) for part in rel.parts):
            continue
        if _is_deploy_only(rel.as_posix()):
            skipped.append(("/" + rel.as_posix(), "deploy 専用ファイル（ページではない）"))
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        url_path = "/" + str(rel.parent).replace("\\", "/").strip(".").strip("/")
        url_path = (url_path.rstrip("/") + "/") if url_path != "/" else "/"
        if p.name != "index.html":
            url_path = url_path + p.name
        if url_path in PENDING_PUBLISH:
            skipped.append((url_path, "PENDING_PUBLISH（未公開）"))
            continue
        if NOINDEX_RE.search(text):
            skipped.append((url_path, "noindex"))
            continue
        m = CANONICAL_RE.search(text)
        if m and m.group(1).rstrip("/") != (BASE + url_path).rstrip("/"):
            skipped.append((url_path, f"canonical→{m.group(1)}"))
            continue
        mtime = datetime.date.fromtimestamp(p.stat().st_mtime).isoformat()
        found.append((url_path, mtime, p))
    return found, skipped


def existing_lastmod():
    """既存 sitemap.xml の lastmod を URL パス→日付で読む（手当て済みの公開日を保持する）。"""
    if not OUT.exists():
        return {}
    xml = OUT.read_text(encoding="utf-8")
    out = {}
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>(.*?)</loc>", block)
        mod = re.search(r"<lastmod>(.*?)</lastmod>", block)
        if loc and mod:
            out[loc.group(1).strip().replace(BASE, "")] = mod.group(1).strip()
    return out


def section_index(url_path):
    """url_path が属する SECTIONS の添字。最長前方一致を採る（/catalogs/ より /catalogs/zbox/）。未定義は末尾。"""
    best_i, best_len = len(SECTIONS), -1
    for i, (prefix, _) in enumerate(SECTIONS):
        if prefix == "/":
            if url_path == "/":
                return i
            continue
        if url_path.startswith(prefix) and len(prefix) > best_len:
            best_i, best_len = i, len(prefix)
    return best_i


def section_key(url_path):
    """(セクション順, URL) のソートキー。"""
    return (section_index(url_path), url_path)


def build():
    pages, skipped = page_urls()
    keep = existing_lastmod()

    entries = {}
    for url_path, mtime, _src in pages:
        entries[url_path] = LASTMOD_OVERRIDE.get(url_path) or keep.get(url_path) or mtime

    missing_extra = []
    for rel, default_date in EXTRA_URLS:
        f = SITE / rel
        url_path = "/" + rel.replace("\\", "/")
        if not f.exists():
            missing_extra.append(url_path)
            continue
        entries[url_path] = LASTMOD_OVERRIDE.get(url_path) or keep.get(url_path) or default_date

    ordered = sorted(entries.items(), key=lambda kv: section_key(kv[0]))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- 自動生成: python _tools/gen-sitemap.py — 手で編集しない（index/ のファイル実体が正本） -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    shown = set()
    for url_path, lastmod in ordered:
        sec = section_index(url_path)
        if sec < len(SECTIONS) and sec not in shown and SECTIONS[sec][1]:
            lines.append(f"  <!-- {SECTIONS[sec][1]} -->")
            shown.add(sec)
        lines.append("  <url>")
        lines.append(f"    <loc>{BASE}{url_path}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n", entries, skipped, missing_extra


def verify(entries):
    """本番 URL に実アクセスして 404 等を検出（sitemap に死んだ URL を載せないための最終防衛）。"""
    import urllib.request
    import urllib.error
    bad = []
    print("\n-- verify (本番 HTTP) --")
    for url_path in entries:
        url = BASE + url_path
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "hub-sitemap-check/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:                                  # noqa: BLE001 — ネットワーク不通も落とさず報告
            code = f"ERR {e}"
        flag = "ok  " if code == 200 else "NG  "
        if code != 200:
            bad.append((url_path, code))
        print(f"  {flag}{code}  {url}")
    return bad


def main():
    check = "--check" in sys.argv
    do_verify = "--verify" in sys.argv

    xml, entries, skipped, missing_extra = build()

    print(f"-- collected {len(entries)} URLs --")
    for url_path, lastmod in sorted(entries.items()):
        print(f"  {lastmod}  {url_path}")
    if skipped:
        print("\n-- excluded --")
        for url_path, why in skipped:
            print(f"  {url_path}  ({why})")
    if missing_extra:
        print("\n-- EXTRA_URLS の実体が無い（sitemap から除外した）--")
        for url_path in missing_extra:
            print(f"  ! {url_path}")

    bad = verify(entries) if do_verify else []

    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if xml == old:
        print(f"\nok. {OUT.relative_to(ROOT)} は最新（{len(entries)} URLs）")
    elif check:
        print(f"\nWOULD-UPDATE {OUT.relative_to(ROOT)}（{len(entries)} URLs）")
    else:
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(xml)
        print(f"\nupdated {OUT.relative_to(ROOT)}（{len(entries)} URLs）")

    if bad:
        print(f"\n!! 200 以外が {len(bad)} 件。EXTRA_URLS / ページ実体を確認すること")
        sys.exit(1)
    if check and xml != old:
        sys.exit(1)      # CI 用: 未反映があれば非ゼロ


if __name__ == "__main__":
    main()
