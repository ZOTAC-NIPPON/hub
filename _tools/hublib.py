#!/usr/bin/env python3
"""hublib.py -- shared logic for the (2') <-> (3) consistency guards.

Single source of truth for:
  - the deploy-only allowlist (HUB.md sec.2)
  - the "published scope" file walk (excludes "_" / "." path segments)
  - path resolution for (2') index and (3) deploy repo, on Windows and macOS

Used by check-hub-drift.py (full-tree audit) and pre-commit-hub.py (staged
guard). Replaces the Windows/pwsh-only check-hub-drift.ps1 + pre-commit-hub.ps1
so that one implementation covers both machines -- keeping the allowlist in a
single place, per HUB.md sec.2.
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
    "_partials",
    "_tools",
}
# Workspace-only docs in (2') that are never published (not "pending").
ALLOW_INDEX_ONLY = {
    "CLAUDE.md",
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


# Known locations of (2') 00_hub_zotac. The folder is named differently on the
# two machines because the SharePoint library is synced under different names.
_ONEDRIVE_CANDIDATES = (
    "Library/CloudStorage/OneDrive-株式会社ゾタック日本/00_Share Point - マーケティング/hub_zotac",
    "OneDrive - 株式会社ゾタック日本/00_Marketing NAS/00_hub_zotac",
)


def onedrive_root():
    """(2') 00_hub_zotac, or None when it cannot be located.

    Only the transition-period mirror check needs this; the canonical for the
    site itself is the deploy repo. Override with $HUB_ONEDRIVE_ROOT.
    """
    env = os.environ.get("HUB_ONEDRIVE_ROOT")
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None
    for rel in _ONEDRIVE_CANDIDATES:
        p = Path.home() / rel
        if p.is_dir():
            return p
    return None


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


def deploy_path(override=None):
    """(3) the git deploy repo.

    Resolution order: explicit override -> $HUB_DEPLOY_PATH -> the default
    layout. Path.home() covers both C:\\Users\\<user> and /Users/<user>, so the
    default is identical on Windows and macOS.
    """
    if override:
        return Path(override).expanduser()
    env = os.environ.get("HUB_DEPLOY_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Documents" / "projects" / "hub"


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
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
# "<head" alone also matches "<header", which every page has -- require the tag
# to actually end there.
_HEAD_RE = re.compile(r"<head(?=[\s>])", re.I)


def contamination(text):
    """Problems making `text` unfit to publish. Empty list == clean.

    Text-level only, so it works on a staged git blob as well as a file.
    """
    problems = []
    if any(m in text for m in MSO_MARKERS):
        problems.append("SharePoint mso metadata")
    is_document = "<html lang=" in text
    if is_document:
        m = _TITLE_RE.search(text)
        if m is None:
            problems.append("no <title>")
        elif not m.group(1).strip():
            problems.append("empty <title>")
        if len(_HEAD_RE.findall(text)) > 1:
            problems.append("duplicate <head> (a contaminated partial was inlined)")
    return problems


def contamination_of_bytes(data):
    """Same check for raw bytes; non-UTF-8 / non-HTML payloads are ignored."""
    try:
        return contamination(data.decode("utf-8"))
    except UnicodeDecodeError:
        return []
