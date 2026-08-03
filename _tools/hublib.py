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
import os
import re
import sys
from pathlib import Path

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
        m = _TITLE_RE.search(text)
        if m is None:
            problems.append("no <title>")
        elif not m.group(1).strip():
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
