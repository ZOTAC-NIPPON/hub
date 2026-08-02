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
]

ALLOWLIST_CASES = [
    ("CNAME", True), ("README.md", True), ("event/askfes2026/index.html", True),
    ("_partials/header.html", True), ("_tools/hublib.py", True),
    ("index.html", False), ("catalogs/index.html", False),
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

    total = len(CASES) + len(ALLOWLIST_CASES) + len(MARKUP_CASES)
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
