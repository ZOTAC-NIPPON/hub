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


# ── 公開しないコメントの除去（2026-11-12 追加） ──────────────────────────
# ②' のコメントは制作メモ（経緯・決定者・生成器のパス等）で、読者には不要。
# ②' 側には残し、③（＝公開サイトと public リポジトリ）へ取り込むときにだけ消す。
# 残すもの:
#   - @partial のマーカー（inject.py が差し替え位置に使う）と、その区間の中身
#     （共通パーツは inject.py が毎回入れ直す生成物）
#   - 条件付きコメント（<!--[if …]> / <!--<![endif]-->）
#   - <script> <textarea> <title> 等の中身（HTML のコメントではなくただの文字列）
# <style> の中は CSS のコメント（/* */）を消す。ただし前後が空白でないものは
# 残す（`1px/**/solid` や `.a/**/.b` は、消すと字句が繋がって意味が変わる）。
# JS のコメントは文字列・正規表現と見分けにくいので触らない。

_RAW_TEXT_TAGS = {"script", "style", "textarea", "title", "noscript",
                  "iframe", "xmp", "noembed", "noframes", "plaintext"}
_TAG_OPEN_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")


def _keep_html_comment(body):
    b = body.lstrip()
    return b.startswith(("@partial:", "[if", "<![endif]"))


def _tag_end(text, i):
    """i は '<' の位置。タグを閉じる '>' の次の位置（引用符の中の > は無視）。"""
    q = None
    for k in range(i + 1, len(text)):
        c = text[k]
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == ">":
            return k + 1
    return -1


def _line_span(text, start, end):
    """コメントがその行に単独なら、行ごと（改行 1 つを含む）の範囲を返す。"""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    le = len(text) if le == -1 else le
    if text[end:le].strip():
        return start, end
    if text[ls:start].strip():     # 行末のコメント: 前の空白ごと（行末に空白を残さない）
        while start > ls and text[start - 1] in " \t":
            start -= 1
        return start, le
    if le < len(text):
        return ls, le + 1          # 行末の改行ごと
    if ls > 0:
        return ls - 1, le          # 最終行: 直前の改行ごと
    return ls, le


def strip_css_comments(css):
    """CSS の /* */ を消す。(結果, 消した数)。文字列の中は触らない。"""
    spans, i, q, n = [], 0, None, len(css)
    while i < n:
        c = css[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif css.startswith("/*", i):
            e = css.find("*/", i + 2)
            if e == -1:
                break               # 閉じていない: 触らない
            e += 2
            before = css[i - 1] if i > 0 else " "
            after = css[e] if e < n else " "
            if before.isspace() or after.isspace() or before in "{};," or after in "{};,":
                spans.append(_line_span(css, i, e))
            i = e
            continue
        i += 1
    return _cut(css, spans), len(spans)


def _cut(text, spans):
    if not spans:
        return text
    out, last = [], 0
    for s, e in spans:
        if s < last:               # 行ごと削除が前の範囲と重なる場合
            s = last
        out.append(text[last:s])
        last = max(last, e)
    out.append(text[last:])
    return "".join(out)


def strip_comments(text):
    """HTML のコメントと <style> 内の CSS コメントを消す。(結果, 消した数)。"""
    spans, repl = [], []           # repl: (start, end, 新しい中身) … <style> の中身
    removed, i, n = 0, 0, len(text)
    while True:
        j = text.find("<", i)
        if j == -1:
            break
        if text.startswith("<!--", j):
            if text.startswith("<!-->", j):
                e = j + 5
            elif text.startswith("<!--->", j):
                e = j + 6
            else:
                e = text.find("-->", j + 4)
                if e == -1:
                    break           # 閉じていない: 以降は触らない
                e += 3
            body = text[j + 4:e - 3]
            m = re.match(r"\s*@partial:(\w+) START", body)
            if m:                   # 共通パーツの区間は丸ごと残す
                end_mark = f"<!-- @partial:{m.group(1)} END -->"
                k = text.find(end_mark, e)
                i = (k + len(end_mark)) if k != -1 else e
                continue
            if not _keep_html_comment(body):
                spans.append(_line_span(text, j, e))
                removed += 1
            i = e
            continue
        if text.startswith("<![CDATA[", j):
            k = text.find("]]>", j)
            i = n if k == -1 else k + 3
            continue
        if text.startswith("<!", j) or text.startswith("<?", j):
            k = text.find(">", j)
            i = n if k == -1 else k + 1
            continue
        m = _TAG_OPEN_RE.match(text, j)
        if not m:
            i = j + 1
            continue
        k = _tag_end(text, j)
        if k == -1:
            break
        name = m.group(2).lower()
        if not m.group(1) and name in _RAW_TEXT_TAGS and not text[j:k].rstrip(">").endswith("/"):
            close = re.compile(r"</" + name + r"(?=[\s/>])", re.I).search(text, k)
            c = n if close is None else close.start()
            if name == "style":
                css, cn = strip_css_comments(text[k:c])
                if cn:
                    repl.append((k, c, css))
                    removed += cn
            i = c
            continue
        i = k
    # 範囲を前から順に組み立てる（コメント削除と <style> の差し替えは重ならない）
    edits = sorted([(s, e, "") for s, e in spans] + repl)
    out, last = [], 0
    for s, e, new in edits:
        if s < last:
            s = last
        out.append(text[last:s])
        out.append(new)
        last = max(last, e)
    out.append(text[last:])
    return "".join(out), removed


def to_hub(text, previous=None, strip_comment=False):
    """②' の内容から、③ に置くべき内容を作る。

    取り込み（hub.py import）とガード（pre-commit-hub.py）の両方がこれを使う。
    別々に実装すると必ずずれて、正しく取り込んだ内容をガードが弾く
    （実際に起きた）。

    previous には ③ の既存内容を渡す。og:title が無くて title を復元できない
    場合の、最後の復元源になる。

    strip_comment=True（HTML のとき取り込みが指定）で制作メモのコメントを消す。
    """
    out, fixes, unresolved = sanitize(text)
    if unresolved and previous:
        m = re.search(r"<title>(.*?)</title>", previous, re.S)
        if m and m.group(1).strip():
            out = EMPTY_TITLE_RE.sub(f"<title>{m.group(1).strip()}</title>", out, count=1)
            fixes.append(f"title を ③ の既存ページから復元: {m.group(1).strip()}")
            unresolved = []
    if strip_comment:
        out, _ = strip_comments(out)
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
