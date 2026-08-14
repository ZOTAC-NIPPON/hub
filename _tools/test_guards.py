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
]

MARKUP_CASES = [
    ("index.html", True), ("_partials/header.html", True), ("sitemap.xml", True),
    ("_tools/hublib.py", False),      # 検査ツール自身を誤検知しないこと
    ("CNAME", False), ("pdfs/a.pdf", False),
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

    total = (len(CASES) + len(ALLOWLIST_CASES) + len(MARKUP_CASES)
             + len(HEADER_CSS_CASES))
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
