#!/usr/bin/env python3
"""test_guards.py -- ガードそのものが機能しているかの自己テスト。

検査ツールが「何も検出しない状態」に退化しても、対象が清浄なら緑になって
しまい気づけない。既知の汚染サンプルを必ず検出することを CI で確かめる。

  python3 _tools/test_guards.py

終了コード: 0 = 全て合格 / 1 = 不合格
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402

# 2026-08-02 に実際に踏んだ汚染の形（SharePoint が挿入したもの）
MSO_BLOCK = (
    '<!--[if gte mso 9]><xml>\n<mso:CustomDocumentProperties>\n'
    '<mso:ContentTypeId msdt:dt="string">0x0101</mso:ContentTypeId>\n'
    '</mso:CustomDocumentProperties>\n</xml><![endif]-->'
)
CLEAN = '<!doctype html>\n<html lang="ja"><head><title>正常なページ</title></head>\n<body><header>x</header></body></html>'

CASES = [
    # (説明, 入力, 検出されるべきか)
    ("清浄な文書", CLEAN, False),
    ("mso ブロック挿入", CLEAN.replace("</head>", MSO_BLOCK + "</head>"), True),
    ("xmlns:mso 属性", CLEAN.replace('<html lang="ja">', '<html lang="ja" xmlns:mso="urn:schemas-microsoft-com:office:office">'), True),
    ("title の空化", CLEAN.replace("<title>正常なページ</title>", "<title></title>"), True),
    ("head の重複（汚染 partial の展開）", CLEAN.replace("<body>", "<html><head><title></title></head><body>"), True),
    ("属性なし <html>", '<html><head><title></title></head><body></body></html>', True),
    ("大文字タグ", '<HTML LANG="ja"><HEAD><TITLE></TITLE></HEAD><BODY></BODY></HTML>', True),
    ("断片（partial。title を持たないのが正常）", '<style>a{}</style>\n<header>x</header>', False),
    ("断片に mso 追記", '<style>a{}</style>\n' + MSO_BLOCK, True),
    # 偽陽性の負例（2026-08-03 に実際に発生）。marker 名を平文で書いただけの
    # 文書や、検査ツール自身のソースを汚染と判定してはいけない。
    ("marker 名を平文で説明している文書",
     CLEAN.replace("<body>", "<body><p>mso:CustomDocumentProperties や xmlns:mso= が入る</p>"), False),
    # <head> を持たない描画補助 HTML。title が無いのが正常で、SharePoint 障害とは無関係。
    ("head を持たない canvas ラッパ",
     '<!DOCTYPE html><html><body style="margin:0"><canvas id="c"></canvas></body></html>', False),
]

ALLOWLIST_CASES = [
    ("CNAME", True), ("README.md", True), ("event/askfes2026/index.html", True),
    ("_partials/header.html", True), ("_tools/hublib.py", True),
    ("CLAUDE.md", True),
    ("index.html", False), ("catalogs/index.html", False),
]

# 2026-08-14: ページ側に共通ヘッダーの CSS が残る形（30 ページで起きていた）。
# partial 側が詳細度で勝つため見た目は正常で、検出器が黙ると誰も気づけない。
_PARTIAL = ('<!-- @partial:header START — 編集は _partials/header.html -->\n'
            '<style>.site-header .site-header-inner{max-width:1100px;}</style>\n'
            '<header class="site-header"><div class="site-header-inner"></div></header>\n'
            '<!-- @partial:header END -->')
HEADER_CSS_CASES = [
    # (説明, 入力, 検出されるべきか)
    ("注入済みブロックだけ", _PARTIAL, False),
    ("ページ側にも .site-header-inner",
     _PARTIAL + '<style>.site-header-inner{max-width:1200px}</style>', True),
    ("@media の中に隠れている",
     _PARTIAL + '<style>@media (max-width:700px){.site-nav{gap:8px}}</style>', True),
    ("混在セレクタ（自動削除できない形）",
     _PARTIAL + '<style>a, .site-nav a{color:#fff}</style>', True),
    ("宣言値やコメントの中の文字列は拾わない",
     _PARTIAL + '<style>/* .site-header を上書きしない */\n.x{--n:".site-nav"}</style>', False),
    ("フック名で始まる別クラスは無関係",
     _PARTIAL + '<style>.site-navigation{display:flex}</style>', False),
    ("波括弧が閉じていない CSS は解析不能として挙げる",
     _PARTIAL + '<style>.x{color:red</style>', True),
    ("ヘッダーCSSを持たない素のページ",
     '<style>body{margin:0}.wrap{max-width:780px}</style>', False),

    # 2026-08-14 の初版が取りこぼした形（Codex レビューと自前の red-team で判明）。
    # 偽陽性＝正常なページで公開が止まる。偽陰性＝複製を見逃す。前者の方が実害が大きい。
    ("偽陽性: content に { を含む",
     _PARTIAL + '<style>.x::before{content:"{"}.y{color:red}</style>', False),
    ("偽陽性: content に } を含む",
     _PARTIAL + '<style>.x::before{content:"}"}.y{color:red}</style>', False),
    ("偽陽性: 宣言値の文字列にフック名",
     _PARTIAL + '<style>.x{content:"}";--label:".site-header{"}</style>', False),
    ("偽陽性: 属性セレクタに {",
     _PARTIAL + '<style>[data-x="{"]{color:red}</style>', False),
    ("偽陽性: @font-face の文字列に {",
     _PARTIAL + '<style>@font-face{font-family:"{";src:url(x.woff2)}</style>', False),
    ("偽陽性: 引用符なし url(...) に {",
     _PARTIAL + '<style>.x{background:url(data:image/svg+xml,{)}</style>', False),
    ("偽陰性: 文字列内の /* で挟んで隠す",
     _PARTIAL + '<style>.x{content:"/*"}.site-header{display:block}.y{content:"*/"}</style>', True),
    ("偽陰性: セミコロン型 at-rule の後ろ",
     _PARTIAL + '<style>@import url("base.css"); .site-header{display:block}</style>', True),
    ("偽陰性: @supports を空白なしで書く",
     _PARTIAL + '<style>@supports(display:grid){.site-nav{gap:1px}}</style>', True),
    ("偽陰性: CSS ネスティングの中",
     _PARTIAL + '<style>.card{color:red;& .site-nav{gap:1px}}</style>', True),
    ("偽陰性: <STYLE> が大文字",
     _PARTIAL + '<STYLE>.site-header{display:block}</STYLE>', True),
    ("@keyframes の 0% はセレクタではない",
     _PARTIAL + '<style>@keyframes k{0%{opacity:0}100%{opacity:1}}</style>', False),
]

# 外部 CSS へ複製を移されたら見逃す、という穴を塞げているか。
HEADER_CSS_LINK_CASES = [
    ("外部 CSS の中の複製",
     _PARTIAL + '<link rel="stylesheet" href="style.css">',
     {"style.css": ".site-header{position:fixed}"}, True),
    ("外部 CSS が清浄",
     _PARTIAL + '<link rel="stylesheet" href="style.css">',
     {"style.css": ".wrap{max-width:780px}"}, False),
    ("外部 URL は読みに行かない",
     _PARTIAL + '<link rel="stylesheet" href="https://example.com/a.css">', {}, False),
]

MARKUP_CASES = [
    ("index.html", True), ("_partials/header.html", True), ("sitemap.xml", True),
    ("_tools/hublib.py", False),      # 検査ツール自身を誤検知しないこと
    ("CNAME", False), ("pdfs/a.pdf", False),
]

# 2026-08: GA4 のセッション 23%（162/711）が Unassigned になっていた形。
# 規約（_tools/analytics/utm-policy.md）どおりの URL を誤検知しないことと、
# 実際に踏んだ間違いを必ず検出することの両方を確かめる。
_BASE = "https://hub.zotac.co.jp/reviews/power-limit-rtx-50-series/"
_OK = "?utm_source=twitter&utm_medium=social&utm_campaign=202607_power_limit"
UTM_CASES = [
    # (説明, URL, ハブのページ上か, 検出されるべきか)
    ("規約どおり（最小構成）", _BASE + _OK, False, False),
    ("規約どおり（utm_content 付き）", _BASE + _OK + "&utm_content=article_5090", False, False),
    ("UTM を持たない普通のリンク", _BASE, False, False),
    ("HTML エンティティ &amp; 区切り",
     _BASE + _OK.replace("&", "&amp;") + "&amp;utm_content=thread_day1", False, False),
    ("別ドメイン宛ての正しい UTM",
     "https://zotac.co.jp/lp/?utm_source=twitter&utm_medium=social&utm_campaign=202607_power_limit",
     False, False),

    # 実際に踏んだ間違い（2026-07 の Power Limit 企画）
    ("utm_source=x（GA4 のソース一覧に無い）",
     _BASE + "?utm_source=x&utm_medium=social&utm_campaign=202607_power_limit", False, True),
    ("utm_medium=article（チャネル定義に無い）",
     _BASE + "?utm_source=twitter&utm_medium=article&utm_campaign=202607_power_limit", False, True),
    ("当時の実物そのまま",
     _BASE + "?utm_source=x&utm_medium=thread&utm_campaign=powerlimit2026&utm_content=5090",
     False, True),

    # 規約の各条項
    ("utm_campaign が無い", _BASE + "?utm_source=twitter&utm_medium=social", False, True),
    ("utm_campaign が未登録",
     _BASE + "?utm_source=twitter&utm_medium=social&utm_campaign=202612_unknown", False, True),
    ("utm_campaign の形式違反（年月が無い）",
     _BASE + "?utm_source=twitter&utm_medium=social&utm_campaign=powerlimit2026", False, True),
    ("utm_source が未登録",
     _BASE + "?utm_source=note&utm_medium=social&utm_campaign=202607_power_limit", False, True),
    ("大文字が混じる",
     _BASE + "?utm_source=Twitter&utm_medium=social&utm_campaign=202607_power_limit", False, True),
    ("utm_term を無償投稿に付けている", _BASE + _OK + "&utm_term=rtx_5090", False, True),

    # 内部リンク判定はリンク先ではなく「書いた文書がハブのページか」で決まる。
    # 同じ URL が、X の投稿では正しく、ハブのページ内では違反になる。
    ("ハブのページ内に同じ URL（内部リンク）", _BASE + _OK, True, True),
    ("ルート相対リンクは書いた場所によらず内部", "/reviews/meganex8kmk2/" + _OK, False, True),
    ("ハブのページから別ドメインへ UTM 付き（正しい用法）",
     "https://zotac.co.jp/lp/?utm_source=twitter&utm_medium=social&utm_campaign=202607_power_limit",
     True, False),
]

# 本文からの URL 抽出。Markdown と HTML の両方の書き方で拾えること。
UTM_EXTRACT_CASES = [
    ("Markdown のリンク記法", f"詳しくは[こちら]({_BASE}{_OK})をご覧ください。", 1),
    ("HTML の href", f'<a href="{_BASE}{_OK}">記事</a>', 1),
    ("裸の URL が和文に埋まっている", f"公開しました。{_BASE}{_OK}、ぜひどうぞ。", 1),
    ("UTM を持たない URL は拾わない", f'<a href="{_BASE}">記事</a>', 0),
    ("複数行に複数本", f"{_BASE}{_OK}\n{_BASE}{_OK}&utm_content=thread_day1", 2),
]


def main():
    hublib.use_utf8_stdout()
    fails = []

    for label, text, should_flag in CASES:
        got = bool(hublib.contamination(text))
        if got != should_flag:
            fails.append(f"contamination: {label} → 検出={got} 期待={should_flag}")

    for rel, expected in ALLOWLIST_CASES:
        got = hublib.is_deploy_only(rel)
        if got != expected:
            fails.append(f"is_deploy_only: {rel} → {got} 期待={expected}")

    for rel, expected in MARKUP_CASES:
        got = hublib.is_markup(rel)
        if got != expected:
            fails.append(f"is_markup: {rel} → {got} 期待={expected}")

    for label, text, should_flag in HEADER_CSS_CASES:
        got = bool(hublib.header_css_selectors(text))
        if got != should_flag:
            fails.append(f"header_css_selectors: {label} → 検出={got} 期待={should_flag}")

    for label, text, sheets, should_flag in HEADER_CSS_LINK_CASES:
        got = bool(hublib.header_css_selectors(text, sheets.get))
        if got != should_flag:
            fails.append(f"header_css_selectors(外部CSS): {label} → 検出={got} 期待={should_flag}")

    # UTM は登録簿（utm-taxonomy.json / campaigns.json）を読んで判定するので、
    # 登録簿が消えていれば検査ごと成立しない。ここで一緒に落とす。
    try:
        taxonomy, campaigns = hublib.load_analytics()
    except (OSError, ValueError) as e:
        fails.append(f"load_analytics: 登録簿を読めない → {e}")
        taxonomy = campaigns = None

    if taxonomy is not None:
        for label, url, on_hub, should_flag in UTM_CASES:
            got = bool(hublib.utm_problems(url, taxonomy, campaigns, on_hub_page=on_hub))
            if got != should_flag:
                fails.append(f"utm_problems: {label} → 検出={got} 期待={should_flag}")

    for label, text, expected in UTM_EXTRACT_CASES:
        got = len(hublib.find_utm_urls(text))
        if got != expected:
            fails.append(f"find_utm_urls: {label} → {got} 本 期待={expected} 本")

    total = (len(CASES) + len(ALLOWLIST_CASES) + len(MARKUP_CASES)
             + len(HEADER_CSS_CASES) + len(HEADER_CSS_LINK_CASES)
             + len(UTM_CASES) + len(UTM_EXTRACT_CASES))
    print(f"test_guards: {total - len(fails)}/{total} 合格")
    if fails:
        for f in fails:
            print(f"  ! {f}")
        print("\nRESULT: FAILED")
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
