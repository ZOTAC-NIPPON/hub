#!/usr/bin/env python3
"""sanitize.py -- SharePoint がHTMLへ書き込んだ列メタデータを取り除く。

SharePoint ドキュメントライブラリは、格納した HTML に次の 3 つを書き込む:

  1. `</head>` の直前に `<!--[if gte mso 9]><xml><mso:CustomDocumentProperties>…`
  2. `<html>` タグへ `xmlns:mso` / `xmlns:msdt` 属性
  3. **`<title>` の中身を空にする**

3 が最も痛い。失われた文字列はファイル内に残らない……が、**`og:title` と
`twitter:title` は消されない**。これを使えば復元できる（③ の清浄な原本
39 件と照合し、誤りゼロを確認済み。差異は SKU 表記の更新分のみで、
そちらは og:title の方が新しかった）。

復元元が無い場合は書き換えず、その旨を返す。空タイトルのまま公開するくらい
なら止めるため。

  python3 _tools/sanitize.py <file...>            # 確認のみ（書き換えない）
  python3 _tools/sanitize.py <file...> --write    # 実際に書き換える

終了コード: 0 = 全て清浄化できた（または元から清浄） / 1 = 復元できないものがある
"""

import argparse
import re
import sys
from pathlib import Path

# SharePoint が挿入するブロック
MSO_BLOCK_RE = re.compile(r"\n?[ \t]*<!--\[if gte mso 9\]><xml>.*?</xml><!\[endif\]-->", re.S)
# 汚染された partial が inject/生成器で展開された痕跡。
# `<html xmlns:mso=…><head>` … `<title></title></head>` が本文中に紛れ込む。
INLINE_FRAGMENT_RE = re.compile(
    r"\n?<html xmlns:mso=[^>]*>\s*<head>.*?</head>", re.S)
XMLNS_ATTR_RE = re.compile(r'\s+xmlns:(?:mso|msdt)="[^"]*"')
EMPTY_TITLE_RE = re.compile(r"<title>\s*</title>")
OG_TITLE_RES = (
    re.compile(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"'),
    re.compile(r'<meta[^>]*content="([^"]*)"[^>]*property="og:title"'),
    re.compile(r'<meta[^>]*name="twitter:title"[^>]*content="([^"]*)"'),
)


def recover_title(text):
    for r in OG_TITLE_RES:
        m = r.search(text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def sanitize(text):
    """(清浄化後のテキスト, 適用した処置のリスト, 未解決の問題のリスト)"""
    fixes, unresolved = [], []
    out = text

    n = len(INLINE_FRAGMENT_RE.findall(out))
    if n:
        out = INLINE_FRAGMENT_RE.sub("", out)
        fixes.append(f"展開された汚染パーツを除去 ×{n}")

    n = len(MSO_BLOCK_RE.findall(out))
    if n:
        out = MSO_BLOCK_RE.sub("", out)
        fixes.append(f"mso メタデータブロックを除去 ×{n}")

    n = len(XMLNS_ATTR_RE.findall(out))
    if n:
        out = XMLNS_ATTR_RE.sub("", out)
        fixes.append(f"xmlns:mso / xmlns:msdt 属性を除去 ×{n}")

    if EMPTY_TITLE_RE.search(out):
        title = recover_title(out)
        if title:
            out = EMPTY_TITLE_RE.sub(f"<title>{title}</title>", out, count=1)
            fixes.append(f"title を og:title から復元: {title}")
        else:
            unresolved.append("title が空で、og:title からも復元できない")

    return out, fixes, unresolved


PARTIAL_REGION_RE = re.compile(
    r"\n?<!-- @partial:(\w+) START.*?<!-- @partial:\1 END -->", re.S)


def strip_partial_regions(text):
    """共通パーツの注入領域を落とす。

    ③ の HTML は「②' の内容 ＋ inject.py が注入した共通パーツ」。注入部分は
    ③ 側の生成物（`_partials/` が正本）なので、②' との照合対象にしてはいけない。
    生成器が作ったページは ②' 側にマーカーを持たないため、ここを比較に含めると
    正しく取り込んだ内容が丸ごと弾かれる。
    """
    return PARTIAL_REGION_RE.sub("", text)


def to_hub(text, previous=None):
    """②' の内容から、③ に置くべき内容を作る。

    取り込み（hub.py import）とガード（pre-commit-hub.py）の両方がこれを使う。
    別々に実装すると必ずずれて、正しく取り込んだ内容をガードが弾く
    （実際に起きた）。

    previous には ③ の既存内容を渡す。og:title が無くて title を復元できない
    場合の、最後の復元源になる。
    """
    out, fixes, unresolved = sanitize(text)
    if unresolved and previous:
        m = re.search(r"<title>(.*?)</title>", previous, re.S)
        if m and m.group(1).strip():
            out = EMPTY_TITLE_RE.sub(f"<title>{m.group(1).strip()}</title>", out, count=1)
            fixes.append(f"title を ③ の既存ページから復元: {m.group(1).strip()}")
            unresolved = []
    return out, fixes, unresolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--write", action="store_true", help="実際に書き換える")
    args = ap.parse_args()

    changed = failed = clean = 0
    for f in args.files:
        p = Path(f)
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"  ? 読めない: {p} ({e})")
            failed += 1
            continue
        out, fixes, unresolved = sanitize(text)
        if not fixes and not unresolved:
            clean += 1
            continue
        print(f"  {p}")
        for x in fixes:
            print(f"     ✓ {x}")
        for x in unresolved:
            print(f"     ✗ {x}")
        if unresolved:
            failed += 1
            continue
        if args.write:
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(out)
        changed += 1

    verb = "清浄化した" if args.write else "清浄化できる"
    print(f"\n{verb}: {changed} / 元から清浄: {clean} / 復元できない: {failed}")
    if not args.write and changed:
        print("※ 確認のみです。実際に書き換えるには --write を付けてください。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
