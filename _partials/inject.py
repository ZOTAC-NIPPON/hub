#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共通パーツ注入（Jekyll を使わない自前テンプレート機構）— hub 全体の単一ソース。

目的:
  ヘッダー / 計測タグ等「全ページ共通の塊」を 1 ソース（_partials/<name>.html）に集約し、
  このスクリプトで公開ページへ流し込む。1 か所直す→全ページ反映。複製ズレ・設置漏れを構造的に無くす。
  ※ 本ファイルと _partials/ は 00_hub_zotac 直下に置く（hub 配下 全プロジェクトの正本）。

使い方:
  cd 00_hub_zotac
  python _partials/inject.py            # 反映
  python _partials/inject.py --check    # 差分が出るか確認のみ（書き込まない・CI/監査用）

対象:
  既定は index/ 配下の公開 HTML（_ 始まりフォルダは除外）＋ case-studies のコピー元。
  兄弟プロジェクト（Reviews/ 等）は ONBOARD に明示追加して取り込む（バリアント指定可）。

仕組み:
  各ページ内を HTML コメントのマーカーで囲って管理する（冪等）。
    <!-- @partial:header START ... -->  ... 中身 ...  <!-- @partial:header END -->
  - マーカーが既にあれば中身だけ差し替え
  - マーカーが無い既存ページは「アンカー位置」へ新規挿入（旧・無印ブロックは legacy 正規表現で除去）
  - header はページ階層に応じて該当ナビへ is-active を自動付与
  - header は variant 指定（例: variant=light → _partials/header-light.html）に対応
"""
import re, sys, pathlib, html, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent      # 00_hub_zotac または deploy リポジトリ
PDIR = ROOT / "_partials"
# 公開サイトのルート（root 相対パスの基準）。OneDrive 側は ROOT/index/、
# deploy リポジトリ（③）では ROOT 自身がサイトのルート。
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


# deploy 専用ファイルの判定は _tools/hublib.py を単一の正本として使う。
# hublib が無い配置（OneDrive 側の旧コピー等）では全ファイルを対象にする従来動作。
sys.path.insert(0, str(ROOT / "_tools"))
from hublib import is_deploy_only as _is_deploy_only   # 見つからなければ落ちてよい
                                                          # （検査が黙って弱まるより止める）

# ── 注入対象パーツ定義 ───────────────────────────────────────────────
# anchor: マーカーが無い初回に挿入する位置。('</title>', 'after') = </title> の直後
#         文字列のほか正規表現（re.compile）も可。<body data-sku="..."> のような属性付きタグに対応
# legacy: 旧・無印ブロックを除去する正規表現（移行用。無ければ None）
PARTIALS = {
    "analytics": {
        "file":   PDIR / "analytics.html",
        "anchor": ("</title>", "after"),
        # 旧・無印ブロックの除去（全バリアント対応）。script本体＋直前コメントのみを狙い、
        # プライバシー表記の .analytics-notice（CSS/段落）は対象外＝残す。
        "legacy": [
            # GA4 ローダ（直前の GA コメントごと）
            re.compile(r"\n?[ \t]*(?:<!--[^>]*?(?:Google Analytics|Analytics|gtag)[^>]*?-->[ \t]*\n?)?[ \t]*<script[^>]*src=\"https://www\.googletagmanager\.com/gtag/js\?id=G-N5X4CC48YH\"[^>]*>\s*</script>", re.S),
            # gtag インライン設定
            re.compile(r"\n?[ \t]*<script>\s*window\.dataLayer\s*=\s*window\.dataLayer.*?gtag\(\s*'config'\s*,\s*'G-N5X4CC48YH'.*?</script>", re.S),
            # Microsoft Clarity（直前の Clarity コメントごと）
            re.compile(r"\n?[ \t]*(?:<!--[^>]*?Clarity[^>]*?-->[ \t]*\n?)?[ \t]*<script[^>]*>\s*\(function\(c,l,a,r,i,t,y\).*?wk7j63hn3o.*?</script>", re.S),
            # 旧バナーコメント類
            re.compile(r"\n?[ \t]*<!--[^>]*?Analytics \(hub\.zotac\.co\.jp[^>]*?-->", re.S),
            re.compile(r"\n?[ \t]*<!--.*?ANALYTICS / TRACKING TAGS.*?-->", re.S),
            re.compile(r"\n?[ \t]*<!--[ \t]*=+[ \t]*Analytics[ \t]*=+[ \t]*-->", re.S),
        ],
    },
    "header": {
        "file":   PDIR / "header.html",
        "anchor": (re.compile(r"<body(?:\s[^>]*)?>"), "after"),
        # 旧・無印の <header class="site-header">…</header>（.wrap / .container いずれの外枠も）を除去。
        "legacy": [
            re.compile(r"\n?[ \t]*<header class=\"site-header\">.*?</header>", re.S),
        ],
    },
}

# header の is-active 判定: SITE からの相対パス先頭セグメント → ハイライトするナビ href
SECTION_NAV = {
    "trial-program": "/trial-program/",
    "case-studies":  "/case-studies/",
    "_case_studies_poc": "/case-studies/",   # コピー元 live.html 用
    "reviews":       "/reviews/",
    "catalogs":      "/catalogs/",
    "press":         "/press/",
}

# 兄弟プロジェクト等の明示取り込み（このパスを SITE 同様に走査）。variant は将来の header-<v>.html 切替用。
# 例: ROOT/"Reviews": {"variant": None}, ROOT/"2601_ZBOX_Trial_Campaign": {"variant": "light"}
ONBOARD = {}

# header 内の問い合わせ CTA。注入時にページ別のクエリを付与する（URL 規約の正本 = _forms/README.md §3）。
#   - from: 全ページ（ルート相対パス）
#   - sku/pname/series/line: 製品ページのみ。生成器（build_pages / _gpu_gen / build_enterprise）と
#     レビュー記事が <body data-inquiry-*> で明示した製品文脈を転写する（暗黙の推測はしない）。
#   - intent は付けない（ヘッダーの「お問い合わせ」は相談種類を表明していないため）。
INQUIRY_URL = "https://zotac.co.jp/product-biz-inquiry/"
INQ_KEYS = ("sku", "pname", "series", "line")
INQ_SKU_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")   # 型番形式の検証（汚染値をヘッダーへ拡散させない）


def target_files():
    """公開対象 HTML（_ 始まりフォルダは除外）。index/ 配下＋case-studies コピー元＋ONBOARD。"""
    files = []
    roots = [SITE] + [pathlib.Path(p) for p in ONBOARD]
    for base in roots:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.html")):
            rel = p.relative_to(base)
            if any(part.startswith(("_", ".")) for part in rel.parts):
                continue
            # deploy 専用ファイル（GSC 検証用 HTML・旧URL リダイレクトスタブ等）は
            # 共通ヘッダーを持たない素の HTML なので注入対象外。許容リストの正本は
            # _tools/hublib.py（HUB.md §2 と同期）。
            if _is_deploy_only(rel.as_posix()):
                continue
            files.append(p)
    src = SITE / "_case_studies_poc" / "live.html"   # case-studies/index.html のコピー元も同期
    if src.exists():
        files.append(src)
    return files


def active_href(path):
    """path（公開ページ）に対応するナビ href。無ければ None。"""
    try:
        rel = path.relative_to(SITE)
    except ValueError:
        return None
    head = rel.parts[0] if rel.parts else ""
    return SECTION_NAV.get(head)


def stamp_active(block, href):
    """header ブロック内の該当ナビ <a href="href"> に is-active を付与（1個だけ）。"""
    if not href:
        return block
    return block.replace(f'<a href="{href}">', f'<a href="{href}" class="is-active">', 1)


def page_from(path):
    """path（公開ページ）のルート相対 URL。SITE 外なら None（from 無しで注入）。"""
    try:
        rel = path.relative_to(SITE)
    except ValueError:
        return None
    parts = list(rel.parts)
    if parts and parts[0] == "_case_studies_poc":     # コピー元 live.html → 公開先の URL で計測
        return "/case-studies/"
    if parts and parts[-1] == "index.html":
        parts = parts[:-1]
        return "/" + "".join(p + "/" for p in parts)
    return "/" + "/".join(parts)


def inquiry_params(text):
    """<body data-inquiry-*> の製品文脈を読む。戻り値 = (params dict | None, エラー | None)。

    属性が無い（製品ページでない）= (None, None) は正常。属性はあるが sku が型番形式でない
    場合は (None, "BAD-INQUIRY-ATTRS")＝from のみで注入したうえで問題として報告する。"""
    m = re.search(r"<body\b[^>]*>", text)
    if not m:
        return None, None
    tag = m.group(0)
    vals = {}
    for k in INQ_KEYS:
        a = re.search(r'data-inquiry-%s="([^"]*)"' % k, tag)
        if a:
            v = html.unescape(a.group(1)).strip()
            if v:
                vals[k] = v
    if not vals:
        return None, None
    if not INQ_SKU_OK.match(vals.get("sku", "")):
        return None, "BAD-INQUIRY-ATTRS"
    return vals, None


def stamp_from(block, page, params=None):
    """header 内の問い合わせ CTA にクエリを付与（1個だけ）。
    params（sku/pname/series/line）は製品ページのみ。from は常にページパスで確定する。"""
    if not page and not params:
        return block
    pairs = []
    if params:
        pairs += [f"{k}={urllib.parse.quote(params[k], safe='')}" for k in INQ_KEYS if k in params]
    if page:
        pairs.append(f"from={page}")
    return block.replace(f'href="{INQUIRY_URL}"', f'href="{INQUIRY_URL}?' + "&".join(pairs) + '"', 1)


def variant_file(name, spec, text):
    """既存マーカーに variant=xxx があれば header-xxx.html を採用（無ければ既定）。"""
    if name != "header":
        return spec["file"]
    m = re.search(r"@partial:header START[^>]*?\bvariant=([A-Za-z0-9_-]+)", text)
    if m:
        cand = PDIR / f"header-{m.group(1)}.html"
        if cand.exists():
            return cand
    return spec["file"]


def apply_partial(text, name, spec, path):
    """戻り値 = (新しいテキスト, ステータス)。

    ⚠ 重要（2026-07-28 の障害を受けて）: 挿入位置（anchor）が見つからない場合は
    **元のテキストをそのまま返す**こと。以前は「既存ブロックを除去 → anchor が無いので return」
    という順序のため、除去済みテキストが呼び出し側に渡り、main() が status を見ずに
    書き込んでいた結果、**ヘッダーを削除しただけのファイルが保存される**事故が起きた
    （ZBOX カタログ 13 ページ。`<body data-sku="...">` がリテラル `<body>` に一致しないため）。
    """
    original = text
    src = variant_file(name, spec, text)
    partial = src.read_text(encoding="utf-8").strip("\n")
    attr_err = None
    if name == "header":
        # 製品文脈は <body data-inquiry-*>（生成器/記事が明示）から読む。header ブロックの外に
        # あるため original から読んで安全（自己参照しない）。不正値は from のみに落として報告。
        params, attr_err = inquiry_params(original)
        partial = stamp_active(partial, active_href(path))
        partial = stamp_from(partial, page_from(path), params)
    start = f"<!-- @partial:{name} START — 編集は _partials/{name}.html、反映は python _partials/inject.py -->"
    end   = f"<!-- @partial:{name} END -->"
    block = f"{start}\n{partial}\n{end}"
    # 既存マーカーブロックを除去（前置の改行/字下げごと＝再実行で空行が増えない）
    text = re.sub(r"\n?[ \t]*<!-- @partial:" + re.escape(name) + r" START.*?@partial:" + re.escape(name) + r" END -->",
                  "", text, flags=re.S)
    # 旧・無印ブロックを除去（移行用・全バリアント）
    for rx in spec.get("legacy", []):
        text = rx.sub("", text)
    # 挿入（anchor は文字列 or 正規表現）
    anchor, where = spec["anchor"]
    if isinstance(anchor, re.Pattern):
        m = anchor.search(text)
        if not m:
            # 除去済みの text ではなく original を返す＝このパーツについては何もしなかったことにする
            return original, "NO-ANCHOR"
        hit = m.group(0)
        ins = (hit + "\n" + block) if where == "after" else (block + "\n" + hit)
        text = text[:m.start()] + ins + text[m.end():]
    else:
        if anchor not in text:
            # 除去済みの text ではなく original を返す＝このパーツについては何もしなかったことにする
            return original, "NO-ANCHOR"
        ins = (anchor + "\n" + block) if where == "after" else (block + "\n" + anchor)
        text = text.replace(anchor, ins, 1)
    return text, (attr_err or "ok")


def main():
    check = "--check" in sys.argv
    files = target_files()
    changed, problems = 0, 0
    for f in files:
        orig = f.read_text(encoding="utf-8")
        text = orig
        for name, spec in PARTIALS.items():
            text, status = apply_partial(text, name, spec, f)
            if status != "ok":
                problems += 1
                print(f"  ! {f.relative_to(ROOT)} [{name}] {status}")
        rel = f.relative_to(ROOT)
        if text != orig:
            changed += 1
            if check:
                print(f"  WOULD-UPDATE {rel}")
            else:
                with open(f, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                print(f"  updated {rel}")
        else:
            print(f"  ok      {rel}")
    verb = "would change" if check else "changed"
    print(f"\ndone. {verb} {changed}/{len(files)} files. problems: {problems}")
    if check and (changed or problems):
        sys.exit(1)   # CI 用: 未反映 or 検証エラー（NO-ANCHOR / BAD-INQUIRY-ATTRS）があれば非ゼロ


if __name__ == "__main__":
    main()
