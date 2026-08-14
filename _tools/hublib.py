#!/usr/bin/env python3
"""hublib.py -- shared logic for the (2') <-> (3) consistency guards.

Single source of truth for:
  - the deploy-only allowlist (HUB.md sec.2)
  - the "published scope" file walk (excludes "_" / "." path segments)
  - path resolution for (2') index and (3) deploy repo, on Windows and macOS

Used by pre-commit-hub.py (staged guard), check-contamination.py,
check-invariants.py, gen-sitemap.py, inject.py and hub.py -- the allowlist and
the scan scope live here only, per HUB.md sec.2.
"""

import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

# --- Deploy-only paths allowed to exist ONLY in (3). Keep in sync with HUB.md sec.2.
ALLOW_HUB_ONLY_FILES = {
    "CNAME",
    "README.md",
    ".gitignore",
    "favicon.ico",
    "robots.txt",
    "google2a4e44ce4ec33d4a.html",
    "CLAUDE.md",    # AI の作業入口。README への薄いポインタ
}
# Hub-only top-level folders (old-URL redirect stubs, local tool settings, and
# the build inputs that became git-canonical on 2026-08-02). Jekyll drops every
# "_"-prefixed folder, so _partials/ and _tools/ are tracked but never served
# (verified: https://hub.zotac.co.jp/_partials/header.html returns 404).
# ".git" is deliberately NOT listed: git never stages paths inside it, and the
# drift walk already drops every "."-prefixed segment.
ALLOW_HUB_ONLY_DIRS = {
    "event",
    ".claude",
    ".github",      # CI ワークフロー。git にしか存在しえない
    "_partials",
    "_tools",
}
# Workspace-only docs in (2') that are never published (not "pending").
ALLOW_INDEX_ONLY = {
    "CLAUDE.md",
}
# ③ 側で生成される派生物。②' にも同名ファイルがあるが内容は一致しない
# （③ の実体から生成するため）。ミラー比較の対象外にする。
GENERATED_IN_HUB = {
    "sitemap.xml",
}


def use_utf8_stdout():
    """Keep Japanese paths printable on the Windows console too."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def hub_root():
    """The tree holding this _tools folder -- the deploy repo (3) since the
    2026-08-02 migration, or 00_hub_zotac for a copy still living in OneDrive."""
    return Path(__file__).resolve().parent.parent


def site_root():
    """Root the published URLs are relative to.

    OneDrive keeps the site under 00_hub_zotac/index/; in the deploy repo the
    repository root *is* the site root.
    """
    root = hub_root()
    return (root / "index") if (root / "index").is_dir() else root


# Fast paths for (2') 00_hub_zotac. Only a shortcut -- never rely on these
# alone: the SharePoint library has already been renamed once (2026-08, the
# Windows box was still on "00_Marketing NAS"), which silently disabled the
# guard there. Discovery below is what actually has to work.
_ONEDRIVE_CANDIDATES = (
    "Library/CloudStorage/OneDrive-株式会社ゾタック日本/00_Share Point - マーケティング/hub_zotac",  # macOS
    "OneDrive - 株式会社ゾタック日本/00_Share Point - マーケティング/hub_zotac",                    # Windows
    "OneDrive - 株式会社ゾタック日本/00_Marketing NAS/00_hub_zotac",                              # 〜2026-08 の旧名
)


def _safe_dirs(p):
    """p 直下のディレクトリ。列挙できなければ空。

    クラウド同期フォルダは .Trash などで列挙が固まる／失敗することがあるので、
    素通しせず握って進む（探索は補助手段で、失敗しても env と既知候補が残る）。
    """
    try:
        return [c for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        return []


def _onedrive_sync_roots():
    home = Path.home()
    try:
        yield from (d for d in home.iterdir()
                    if d.is_dir() and d.name.startswith("OneDrive"))
    except OSError:
        pass
    yield from _safe_dirs(home / "Library" / "CloudStorage")


def _looks_like_hub(p):
    """ライブラリ名は変わりうるので、名前ではなく中身で判定する。"""
    try:
        return (p.name.endswith("hub_zotac")
                and (p / "HUB.md").is_file() and (p / "index").is_dir())
    except OSError:
        return False


def discover_onedrive_roots():
    """同期ルート配下（2 階層まで）から 00_hub_zotac を探し、全件返す。

    実体パスで重複排除する。macOS は ~/OneDrive-<組織> を
    ~/Library/CloudStorage/... への symlink として作るため、素朴に数えると
    同じ場所が 2 件に見えて「判断できない」と誤判定する。
    """
    found = {}
    for root in _onedrive_sync_roots():
        if not root.name.startswith("OneDrive"):
            continue
        for a in _safe_dirs(root):
            for cand in ([a] if _looks_like_hub(a) else
                         [b for b in _safe_dirs(a) if _looks_like_hub(b)]):
                try:
                    found[cand.resolve()] = cand
                except OSError:
                    found[cand] = cand
    # 表示は見つけたときの形、同一判定は実体パスで行う
    return [found[k] for k in sorted(found)]


def onedrive_root():
    """(2') 00_hub_zotac、見つからない／一意に決まらない場合は None。

    移行期のミラー検査だけがこれを必要とする。サイト本体の正本は deploy
    リポジトリ側。$HUB_ONEDRIVE_ROOT で明示指定できる。

    候補が複数見つかった場合は推測せず None を返す（古いコピーや別の同期先を
    掴んで「正本が1つ」の前提を壊さないため）。
    """
    env = os.environ.get("HUB_ONEDRIVE_ROOT")
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None
    for rel in _ONEDRIVE_CANDIDATES:
        p = Path.home() / rel
        if p.is_dir():
            return p
    found = discover_onedrive_roots()
    return found[0] if len(found) == 1 else None


def index_path():
    """(2') the OneDrive editing canonical for the site.

    Falls back to hub_root()/index so a copy of this file still sitting in
    OneDrive keeps behaving as before.
    """
    local = hub_root() / "index"
    if local.is_dir():
        return local
    root = onedrive_root()
    return (root / "index") if root else local


# deploy リポジトリ (3) の置き場所。端末ごとに違ってよい。
# 直書きを候補の羅列にとどめ、最終的には「中身」で判定する。SharePoint
# ライブラリ名の変更で直書きパスが黙って外れ、Windows のガードが不成立に
# なっていた（2026-08-02）のと同じ失敗を繰り返さないため。
_DEPLOY_CANDIDATES = (
    "Developer/hub",              # macOS 標準の開発用フォルダ。iCloud 対象外
    "Documents/projects/hub",     # Windows / 移行前の macOS
    "projects/hub",
)


def _looks_like_deploy(p):
    """名前ではなく中身で判定する。"""
    try:
        return ((p / ".git").exists() and (p / "_tools" / "hublib.py").is_file()
                and (p / "_partials").is_dir())
    except OSError:
        return False


def deploy_path(override=None):
    """(3) the git deploy repo.

    解決順: 明示指定 -> $HUB_DEPLOY_PATH -> このファイル自身の位置 ->
    既知の候補。自分自身がリポジトリ内にあるなら、それが答え。
    """
    if override:
        return Path(override).expanduser()
    env = os.environ.get("HUB_DEPLOY_PATH")
    if env:
        return Path(env).expanduser()
    here = hub_root()
    if _looks_like_deploy(here):
        return here
    for rel in _DEPLOY_CANDIDATES:
        p = Path.home() / rel
        if _looks_like_deploy(p):
            return p
    return Path.home() / _DEPLOY_CANDIDATES[0]


def in_published_scope(rel):
    """False for any path segment starting with "_" or ".".

    "_" folders are unpublished dev space; "." covers .git / .claude /
    .gitignore / .DS_Store.
    """
    return not any(part.startswith(("_", ".")) for part in Path(rel).parts)


def rel_files(base):
    """Relative POSIX-style paths of all files under `base`, published scope only."""
    base = Path(base)
    out = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        if in_published_scope(rel):
            out.append(rel)
    return sorted(out)


# 公開ページではないが共通パーツを注入する生成元（inject.py と同じ定義を使う）。
INJECT_EXTRA_SOURCES = ("_case_studies_poc/live.html",)


def injected_pages(base):
    """共通パーツを注入する HTML（base からの相対 POSIX パス）。

    inject.py の対象と検査の対象がずれると、「注入はされるが検査はされない」
    ページができる（実際 _case_studies_poc/live.html がそれだった）。定義を
    ここ 1 か所に置き、注入器と検査の両方から使う。
    """
    base = Path(base)
    out = [rel for rel in rel_files(base)
           if rel.endswith(".html") and not is_deploy_only(rel)]
    out += [rel for rel in INJECT_EXTRA_SOURCES if (base / rel).is_file()]
    return sorted(out)


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def same_content(a, b):
    return md5(a) == md5(b)


def is_deploy_only(rel):
    """True if `rel` (POSIX-style) may change in (3) without a (2') counterpart."""
    if rel in ALLOW_HUB_ONLY_FILES:
        return True
    return Path(rel).parts[0] in ALLOW_HUB_ONLY_DIRS


# --- SharePoint document-property contamination -----------------------------
# A SharePoint document library writes its column metadata back into HTML files
# it stores: an "<!--[if gte mso 9]><xml><mso:CustomDocumentProperties>" block
# is inserted before </head>, xmlns:mso / xmlns:msdt land on the <html> tag, and
# the <title> is emptied. Detected on 185 files on 2026-08-02; (3) was clean.
# Generators that inline a contaminated partial (inject.py, _gpu_gen.py, ...)
# propagate it further, producing a second block and a duplicate <head>.

MSO_MARKERS = (
    "mso:CustomDocumentProperties",
    "xmlns:mso=",
    "xmlns:msdt=",
)
# 平文で marker 名を書いただけのファイル（この件を説明する文書や検査ツール自身）を
# 汚染と誤判定しないため、実際の構文として現れる場合だけを拾う:
#   - 条件付きコメントのブロック
#   - タグの属性としての xmlns:mso / xmlns:msdt
_MSO_BLOCK_RE = re.compile(r"<!--\[if\s+gte\s+mso\s+9\]>", re.I)
_MSO_ATTR_RE = re.compile(r"<[a-z][^>]*\sxmlns:(?:mso|msdt)\s*=", re.I)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
# "<head" alone also matches "<header", which every page has -- require the tag
# to actually end there.
_HEAD_RE = re.compile(r"<head(?=[\s>])", re.I)
_HTML_RE = re.compile(r"<html(?=[\s>])", re.I)


def contamination(text):
    """Problems making `text` unfit to publish. Empty list == clean.

    Text-level only, so it works on a staged git blob as well as a file.
    """
    problems = []
    if _MSO_BLOCK_RE.search(text) or _MSO_ATTR_RE.search(text):
        problems.append("SharePoint mso metadata")

    # <title> を問うのは <head> を持つページだけ。<html><body> 直結の描画補助
    # HTML（canvas ラッパ等）はタイトルを持たないのが正常で、SharePoint 障害とは
    # 無関係。ここを区別しないと別問題を汚染として数えてしまう。
    heads = len(_HEAD_RE.findall(text))
    if _HTML_RE.search(text) and heads:
        # 正規表現ではなくパーサで取る。コメント内に "<title>" と書かれた文書で
        # 誤った文字列を拾い、「空ではない」と判定して通していた（title-policy.md §6）。
        title = page_title(text)
        if title is None:
            problems.append("no <title>")
        elif not title.strip():
            problems.append("empty <title>")
        if heads > 1:
            problems.append("duplicate <head> (a contaminated partial was inlined)")
    return problems


MARKUP_SUFFIXES = {".html", ".htm", ".xhtml", ".xml", ".svg"}


def is_markup(rel):
    """True if `rel` is a file the contamination check applies to.

    Scoping by extension matters: this module and check-contamination.py carry
    the mso marker strings as constants, so scanning source files would have
    the detector flag its own definitions.
    """
    return Path(rel).suffix.lower() in MARKUP_SUFFIXES


def contamination_of_bytes(data):
    """Same check for raw bytes; non-UTF-8 / non-HTML payloads are ignored."""
    try:
        return contamination(data.decode("utf-8"))
    except UnicodeDecodeError:
        return []


# --- 共通ヘッダーの複製検出 --------------------------------------------------
# 制作時のプレビューを成立させるため、ページ側に共通ヘッダーの CSS を丸ごと
# 書き写す運用が続いていた。inject.py はマークアップ（<header class="site-header">）
# だけを差し替えるので、CSS の写しは注入後もページに残る。公開版では
# partial 側（.site-header .site-header-inner = クラス2個）が詳細度で勝つため
# 見た目は正しく、2026-08-14 まで 30 ページで気づかれなかった。
# 実害は二つ。②' のプレビューが本番と違う幅で出る（今回の発見の経緯）。
# そして partial のセレクタを 1 段浅くした瞬間に全ページが静かに壊れる。
#
# 規則: 共通ヘッダーの見た目を決める CSS は @partial:header 領域だけに置く。
# ページ側で上書きしたくなったら header-<variant>.html を作る（ページCSSで
# ねじ伏せない）。
HEADER_HOOKS = (
    ".site-header", ".site-header-inner", ".site-logo", ".logo-divider",
    ".logo-url", ".host-hub", ".site-nav", ".nav-cta", ".nav-mobile",
    ".nav-toggle", ".nav-toggle-bar", "#site-nav",
)
# 予約フックの直後に続けて識別子が来る別クラス（.site-navigation 等）は無関係。
_HOOK_RE = re.compile("|".join(re.escape(h) + r"(?![\w-])" for h in HEADER_HOOKS))
_HEADER_REGION_RE = re.compile(
    r"<!--\s*@partial:header START.*?@partial:header END[^>]*-->", re.S)
_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.I)
_REL_SHEET_RE = re.compile(r"""\brel\s*=\s*["']?[^"'>]*\bstylesheet\b""", re.I)
# 中に「規則」が入る at-rule（＝再帰する）。@keyframes / @font-face / @page /
# @property の中身はセレクタではないので再帰しない（0% などを拾わないため）。
_NESTED_AT = ("media", "supports", "layer", "container", "scope")
_AT_HEAD_RE = re.compile(r"^@([\w-]+)")
UNPARSABLE = "<CSS を解析できない: 波括弧が閉じていない>"


def _css_skip(css, i):
    """css[i] から「中身を読み飛ばすべきもの」を飛ばした次位置を返す。

    文字列・コメント・エスケープ・url() を素通りさせないためのもの。
    2026-08-14 の初版はこれが無く、`content:"{"` のような**正常な CSS で
    公開を止め**、逆に文字列内の `/*` で本物の規則を見落としていた（Codex 指摘）。
    """
    c = css[i]
    if c == "\\":
        return i + 2
    if c in "\"'":
        j = i + 1
        while j < len(css):
            if css[j] == "\\":
                j += 2
                continue
            if css[j] == c:
                return j + 1
            j += 1
        return len(css)
    if css.startswith("/*", i):
        e = css.find("*/", i + 2)
        return len(css) if e < 0 else e + 2
    if css[i:i + 4].lower() == "url(":            # 引用符なし url(...) の中は生
        e = css.find(")", i + 4)
        return len(css) if e < 0 else e + 1
    return i + 1


def _selector_text(css, a, b):
    """css[a:b] をセレクタ文字列にする。コメントは落とし、文字列は残す。

    セレクタの直前に置かれた見出しコメント（`/* ===== Site Header ===== */`）を
    セレクタの一部として拾うと、コメントに書いただけのフック名で公開が
    止まってしまう。
    """
    out, i = [], a
    while i < b:
        if css.startswith("/*", i):
            e = css.find("*/", i + 2)
            i = b if e < 0 else min(e + 2, b)
            continue
        if css[i] in "\"'":
            j = _css_skip(css, i)
            out.append(css[i:min(j, b)])
            i = j
            continue
        out.append(css[i])
        i += 1
    return " ".join("".join(out).split())


def _css_rules(css, out):
    """css 中の規則のセレクタを out へ積む。解析不能なら False を返す。

    ネストした規則（`.card{& .site-nav{…}}`）も拾うため、通常規則の中身へも
    再帰する。宣言（`color:red;`）は `;` 区切りの文として読み飛ばされる。
    """
    i, n, start = 0, len(css), 0
    while i < n:
        c = css[i]
        if c in "\"'\\/" or css[i:i + 4].lower() == "url(":
            j = _css_skip(css, i)
            if j > i + 1 or c in "\"'\\":
                i = j
                continue
        if c == ";":                               # @import 等・宣言の切れ目
            i += 1
            start = i
            continue
        if c == "}":                               # 対応の無い閉じ括弧は読み飛ばす
            i += 1
            start = i
            continue
        if c == "{":
            sel = _selector_text(css, start, i)
            depth, j = 1, i + 1
            while j < n and depth:
                ch = css[j]
                if ch in "\"'\\/" or css[j:j + 4].lower() == "url(":
                    k = _css_skip(css, j)
                    if k > j + 1 or ch in "\"'\\":
                        j = k
                        continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                j += 1
            if depth:
                return False                       # 閉じていない＝解析不能
            body = css[i + 1:j - 1]
            at = _AT_HEAD_RE.match(sel)
            if at:
                if at.group(1).lower() in _NESTED_AT and not _css_rules(body, out):
                    return False
            else:
                out.append(sel)
                if "{" in body and not _css_rules(body, out):
                    return False
            i = j
            start = i
            continue
        i += 1
    return True


def _css_selectors(css):
    """CSS 中の規則のセレクタを返す。解析不能なら末尾に None を足す。"""
    out = []
    if not _css_rules(css, out):
        out.append(None)
    return out


def page_stylesheets(text):
    """ページが読み込むローカル CSS の href（絶対 URL・プロトコル相対は除く）。"""
    out = []
    for tag in _LINK_RE.findall(text):
        if not _REL_SHEET_RE.search(tag):
            continue
        m = _HREF_RE.search(tag)
        if m and not re.match(r"[a-z][a-z0-9+.-]*:|//", m.group(1), re.I):
            out.append(m.group(1))
    return out


def header_css_selectors(text, read_stylesheet=None):
    """ページ側の CSS に残る「共通ヘッダー用セレクタ」を返す（無ければ空）。

    @partial:header 領域は生成物なので対象外。混在セレクタ（`a, .site-nav a`）も
    一枝でも予約フックを含むなら返す（自動削除できないので人が分ける）。

    read_stylesheet(href) を渡すと、ページが読み込むローカル CSS も同じ基準で
    見る。渡さない場合はインライン <style> だけが対象（＝外部 CSS へ複製を
    移されると見逃す。呼び出し側が解決手段を持つときは必ず渡すこと）。
    """
    outside = _HEADER_REGION_RE.sub("", text)
    sources = [m.group(1) for m in _STYLE_RE.finditer(outside)]
    if read_stylesheet:
        for href in page_stylesheets(outside):
            css = read_stylesheet(href)
            if css:
                sources.append(css)
    hits = []
    for css in sources:
        for sel in _css_selectors(css):
            if sel is None:
                hits.append(UNPARSABLE)
            elif any(_HOOK_RE.search(b) for b in sel.split(",")):
                hits.append(sel)
    return hits


# --- UTM の検査 --------------------------------------------------------------
# 2026-07〜08 の GA4 で、セッションの 23%（162/711）が Unassigned（チャネル判定
# 不能）になっていた。原因は X 投稿の UTM が `utm_source=x` / `utm_medium=article`
# だったこと。GA4 の Organic Social 判定は「ソースが公式のソーシャル一覧に一致
# OR メディアが ^(social|social-network|social-media|sm|...)$ に一致」の OR で、
# この値は両方を外す。Google 公式の Source Categories 一覧（819 エントリ・
# 2026-08-14 照合）に `x` も `x.com` も無く、`twitter` / `twitter.com` / `t.co`
# だけが SOCIAL として載っている。
#
# つまり「UTM を丁寧に付けた投稿ほど Unassigned に落ち、付けていない X 流入は
# t.co のリファラで正しく分類される」という逆転が起きていた。値を1つ間違える
# だけで起きる事故なので、閉じたリストと登録簿で縛り、ここで機械的に検査する。
#
# 規約の正本は _tools/analytics/utm-policy.md、値は utm-taxonomy.json と
# campaigns.json。**規約・登録簿・検査の3点で1組**（どれか1つだけ直さない）。
ANALYTICS_DIR = "_tools/analytics"

# 本文中の URL らしきものを拾う。Markdown の [文言](url) と HTML の href="url"
# の両方を通すため、閉じ括弧・引用符・空白・和文の句読点で切る。
_URL_RE = re.compile(r"""(?:https?://|/)[^\s"'<>()\[\]｜、。「」]+""")

# yyyymm_name（開始年月6桁）。媒体ごとに campaign を分けると横断集計ができない。
_CAMPAIGN_RE = re.compile(r"^(20\d{2})(0[1-9]|1[0-2])_[a-z0-9_]+$")

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def load_analytics(root=None):
    """utm-taxonomy.json と campaigns.json を読む。戻り値 = (taxonomy, campaigns)。

    見つからない・壊れているときは例外にする（fail-open しない）。検査だけ静かに
    素通りすると「規約が無いから緑」になり、事故の再発に気づけない。
    """
    base = Path(root) if root else hub_root()
    tax_path = base / ANALYTICS_DIR / "utm-taxonomy.json"
    cmp_path = base / ANALYTICS_DIR / "campaigns.json"
    for p in (tax_path, cmp_path):
        if not p.exists():
            raise FileNotFoundError(f"UTM の登録簿がありません: {p}")
    taxonomy = json.loads(tax_path.read_text(encoding="utf-8"))
    campaigns = json.loads(cmp_path.read_text(encoding="utf-8"))
    return taxonomy, campaigns


def find_utm_urls(text):
    """本文から UTM を含む URL を拾う（重複は保ったまま出現順で返す）。"""
    return [m.group(0).rstrip(".,;:") for m in _URL_RE.finditer(text)
            if "utm_" in m.group(0)]


def _query_pairs(url):
    """URL のクエリを (key, value) の並びで返す。&amp; 表記も解く。"""
    if "?" not in url:
        return []
    query = url.split("?", 1)[1].split("#", 1)[0].replace("&amp;", "&")
    pairs = []
    for part in query.split("&"):
        if not part:
            continue
        key, _, val = part.partition("=")
        pairs.append((unquote(key), unquote(val)))
    return pairs


def utm_problems(url, taxonomy, campaigns, on_hub_page=False):
    """URL 1本の UTM 規約違反を返す（無ければ空リスト）。

    「なぜ駄目か」ではなく「どう直すか」を返す。登録簿に代替案を持たせてあるのは、
    エラーを見た人がそのまま直せるようにするため。

    `on_hub_page` は「この URL を書いた文書自身がハブのページか」。内部リンク判定
    はリンク先のホストでは決まらない ―― X の投稿から hub.zotac.co.jp へ UTM 付き
    で送るのは正しい用法で、同じ URL がハブのページ内にあると内部リンクになる。
    """
    pairs = _query_pairs(url)
    utm = {k: v for k, v in pairs if k.startswith("utm_")}
    if not utm:
        return []

    problems = []
    host = ""
    m = re.match(r"https?://([^/]+)", url)
    if m:
        host = m.group(1).lower()

    # 1. 内部リンクへの UTM。セッションが途中で分断され、本来の流入元が失われる。
    #    ルート相対リンクは書いた場所によらず内部（外部媒体では成立しない書き方）。
    internal = (not host and url.startswith("/")) or (
        on_hub_page and host in taxonomy.get("internal_hosts", []))
    if internal:
        problems.append("内部リンクに UTM が付いている（内部リンクには付けない）")
        return problems  # 以降の値の検査は無意味

    # 2. 値の書式（小文字 ASCII のみ）。大文字・全角は GA4 で別値になり集計が割れる。
    pattern = re.compile(taxonomy.get("value_pattern", r"^[a-z0-9_.-]+$"))
    for key in UTM_KEYS:
        val = utm.get(key)
        if val and not pattern.match(val):
            problems.append(f"{key}={val} は小文字 ASCII と _ . - のみ")

    # 3. 必須3項目。1つでも欠けると GA4 のチャネル判定が崩れる。
    for key in taxonomy.get("required_keys", []):
        if not utm.get(key):
            problems.append(f"{key} が無い（必須）")

    # 4. utm_medium は閉じたリストから。禁止語には代替案を添える。
    medium = utm.get("utm_medium", "")
    if medium and medium not in taxonomy.get("mediums", {}):
        hint = taxonomy.get("banned_mediums", {}).get(medium)
        allowed = ", ".join(k for k in taxonomy.get("mediums", {}) if not k.startswith("_"))
        problems.append(
            f"utm_medium={medium} は使用禁止 → {hint}" if hint else
            f"utm_medium={medium} は未登録 → 使えるのは {allowed}")

    # 5. utm_source は登録簿から。x / x.com は今回の事故そのものなので個別に説明する。
    source = utm.get("utm_source", "")
    if source:
        banned = taxonomy.get("banned_sources", {}).get(source)
        if banned:
            problems.append(f"utm_source={source} は使用禁止 → {banned}")
        elif source not in taxonomy.get("sources", {}):
            problems.append(
                f"utm_source={source} が未登録 → 先に utm-taxonomy.json の "
                "sources へ登録する（GA4 のチャネル判定を確認したという宣言）")

    # 6. utm_campaign は登録簿にあり、かつ yyyymm_name 形式であること。
    campaign = utm.get("utm_campaign", "")
    if campaign:
        known = campaigns.get("campaigns", {})
        if campaign not in known:
            problems.append(
                f"utm_campaign={campaign} が未登録 → campaigns.json に追加する")
        if not _CAMPAIGN_RE.match(campaign):
            problems.append(
                f"utm_campaign={campaign} の形式が違う → yyyymm_name（例 202607_power_limit）")

    # 7. utm_term は有料検索専用。それ以外に付いていたら utm_content の誤用。
    if utm.get("utm_term") and medium not in ("cpc", "paid_social", "display"):
        problems.append(
            f"utm_term は有料検索専用（utm_medium={medium or '未指定'} には付けない）"
            " → クリエイティブの識別は utm_content")

    return problems


def utm_legacy_paths(taxonomy):
    """訂正不能な既投稿の記録として、検査から除外するパスの集合。

    投稿済みの X 記事などは「規約違反だが記録としては正しい」ので書き換えない。
    check-invariants.py の HEADER_CSS_LEGACY と同じ移行用の名簿で、**減らす方向
    にしか変えない**（新しい項目を足したくなったら、それは直すべき違反）。
    """
    return set(taxonomy.get("legacy_records", {}).get("_paths", []))


# --- <title> の抽出と規約判定 -------------------------------------------------
# 「毎回レビューで指摘され、毎回直すのに終わらない」状態を止めるための機械判定。
# 直しても戻っていたのではなく、完了の定義が無かった（公開64ページでサフィックス
# 9種・区切り3種に割れており、誰が見ても何か指摘できた）。規約の正本は
# _tools/seo/title-policy.md、登録簿は title-registry.json。3点で1組。
#
# 抽出を正規表現でやらないのが要点。trial-program/index.html の冒頭コメントに
# "- <title>を確定版に更新" という行があり、`<title>(.*?)</title>` はコメント側
# から拾って壊れた文字列を返していた。contamination() もそれを「空ではない」と
# 判定して通していた＝判定が効いていなかった（title-policy.md §6）。
SEO_DIR = "_tools/seo"

TITLE_SUFFIX = " | ZOTAC NIPPON"

# ページ種別ごとの固定カテゴリ語。GPU だけ違うのは、現行サフィックスのうち
# "ZOTAC GAMING" は製品名と重複する一方 "グラフィックスカード" は重複しておらず、
# GSC に `zotac グラボ` 等のクエリが実在するため（title-policy.md §3）。
TITLE_CATEGORY = {
    "catalog_zbox": "製品カタログ",
    "catalog_enterprise": "製品カタログ",
    "catalog_gpu": "グラフィックスカード",
}

TITLE_MAX_LEN = 60          # 超過は警告だけ。文字数は CTR を説明しない（§4）
_FULLWIDTH_BAR = "｜"
_TITLE_IN_COMMENT_RE = re.compile(r"<!--(?:(?!-->).)*?<\s*title\b", re.S | re.I)


class _TitleReader(HTMLParser):
    """<head> 内の <title> だけを拾う。コメントとメタ要素は自動的に無視される。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles = []
        self._in_head = False
        self._in_title = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self._in_head = True
        elif tag == "title" and self._in_head:
            self._in_title = True
            self._buf = []
        elif tag == "body":
            self._in_head = False

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self.titles.append("".join(self._buf))
            self._in_title = False
        elif tag == "head":
            self._in_head = False

    def handle_data(self, data):
        if self._in_title:
            self._buf.append(data)


def page_titles(text):
    """<head> 内の <title> の中身を出現順で返す（0個なら空リスト）。"""
    r = _TitleReader()
    try:
        r.feed(text)
        r.close()
    except Exception:
        # 壊れた HTML でも例外で検査全体を落とさない。拾えた分だけ返す。
        pass
    return r.titles


def page_title(text):
    """<head> 内の最初の <title> の中身。無ければ None。"""
    t = page_titles(text)
    return t[0] if t else None


def title_in_comment(text):
    """HTML コメントの中に "<title" と書かれていれば True（§6 の事故の再発検知）。"""
    return bool(_TITLE_IN_COMMENT_RE.search(text))


def title_kind(rel):
    """パスからページ種別を決める。

    カタログ配下でも `catalogs/<系統>/index.html` は製品ページではなく索引なので
    listing 扱いにする（製品名もカテゴリ語も持たないのが正しい）。
    """
    rel = rel.lstrip("/")
    if rel == "index.html":
        return "home"
    parts = rel.split("/")
    if parts[0] == "catalogs" and len(parts) == 4 and parts[3] == "index.html":
        return {"gpu": "catalog_gpu", "zbox": "catalog_zbox",
                "enterprise": "catalog_enterprise"}.get(parts[1], "other")
    if parts[0] == "reviews" and len(parts) == 3:
        return "review"
    if rel in ("catalogs/index.html", "catalogs/zbox/index.html",
               "catalogs/gpu/index.html", "catalogs/enterprise/index.html",
               "reviews/index.html", "press/index.html", "case-studies/index.html"):
        return "listing"
    return "other"


def title_problems(rel, title):
    """タイトル1本の規約違反を返す（無ければ空リスト）。

    返すのは「なぜ駄目か」ではなく「どう直すか」。utm_problems() と同じ方針。
    重複検査はサイト全体を見ないと判定できないので、呼び出し側で行う。
    """
    kind = title_kind(rel)
    problems = []

    if title is None:
        return ["<head> 内に <title> が無い"]
    if not title.strip():
        return ["<title> が空"]
    if title != title.strip():
        problems.append("前後に空白がある")
    if "\n" in title or "\r" in title:
        problems.append("改行が入っている")

    t = title.strip()

    # 区切り文字。全角と半角の混在は 2026-08-14 時点で3ページにあった。
    has_full = _FULLWIDTH_BAR in t
    has_half = " | " in t
    if has_full and has_half:
        problems.append(f"全角 {_FULLWIDTH_BAR} と半角 | が混在 → 半角 ' | ' に統一する")
    elif has_full:
        problems.append(f"全角 {_FULLWIDTH_BAR} を使っている → 半角 ' | ' に統一する")
    if re.search(r"\S\|\S", t):
        problems.append("| の前後にスペースが無い → ' | ' の形にする")

    # サフィックス。トップは別型、それ以外は ZOTAC NIPPON で名乗る。
    if kind != "home" and not t.endswith(TITLE_SUFFIX):
        problems.append(f"サフィックスが '{TITLE_SUFFIX.strip()}' でない"
                        f" → 末尾を '{TITLE_SUFFIX}' にする")

    # カタログのカテゴリ語。製品名の正本照合は生成器側の責務（CI から ②' の
    # sku_catalog.json へ到達できないため、ここでは見ない。§8）。
    cat = TITLE_CATEGORY.get(kind)
    if cat:
        core = t[:-len(TITLE_SUFFIX)] if t.endswith(TITLE_SUFFIX) else t
        if f" — {cat}" not in core:
            problems.append(f"カテゴリ語が '{cat}' でない"
                            f" → '{{製品名}} — {cat}{TITLE_SUFFIX}' の形にする")
        if core.strip().startswith("—"):
            problems.append("製品名が入っていない")

    return problems


def title_warnings(rel, title):
    """公開は止めないが伝えたいこと。文字数は CTR を説明しないので警告止まり。"""
    if not title:
        return []
    out = []
    if len(title) > TITLE_MAX_LEN:
        out.append(f"{len(title)}字（目安 {TITLE_MAX_LEN} 字超）")
    return out


def load_title_registry(root=None):
    """title-registry.json を読む。無ければ例外（fail-open しない）。"""
    base = Path(root) if root else hub_root()
    p = base / SEO_DIR / "title-registry.json"
    if not p.exists():
        raise FileNotFoundError(f"タイトルの登録簿がありません: {p}")
    return json.loads(p.read_text(encoding="utf-8"))
