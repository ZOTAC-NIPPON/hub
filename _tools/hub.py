#!/usr/bin/env python3
"""hub.py -- hub.zotac.co.jp の取得・検査・公開をまとめた入口。

引数なしで起動すると対話メニュー（用語の説明つき）。バッチ／コマンドファイル
からダブルクリックで叩かれるのはこの形。
AI エージェントから叩くときはサブコマンド（+ 任意で --json）を使う。

  python3 _tools/hub.py              # 対話メニュー
  python3 _tools/hub.py status       # 今の状態
  python3 _tools/hub.py doctor       # この端末の設定が正しいか
  python3 _tools/hub.py sync         # GitHub から最新を取得
  python3 _tools/hub.py check        # 検査だけ（何も書き換えない）
  python3 _tools/hub.py publish [パス]  # 取り込み → 反映 → 検査 → commit → push
  python3 _tools/hub.py publish -n      # 上記のうち commit/push だけしない（確認用）

終了コード: 0 = OK / 1 = 検査違反・作業未完了 / 2 = 環境エラー

設計方針:
  - 最後の 1 歩（commit / push）の直前まで、何も書き換えない
  - 失敗したら止まる。勝手に直さない
  - git を隠さない。何を実行したかは常に表示する
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hublib  # noqa: E402

ROOT = hublib.hub_root()
PY = sys.executable or "python3"

# 用語集。メニューで表示するほか、状態表示のラベルにも使う。
GLOSSARY = [
    ("③ / deploy リポジトリ",
     "このフォルダのこと。GitHub の ZOTAC-NIPPON/hub と同じ中身で、\n"
     "     ここに push したものが hub.zotac.co.jp として公開される。"),
    ("②' / OneDrive 側",
     "OneDrive(SharePoint) 上の作業ツリー。記事やカタログの制作はここ。\n"
     "     ただし SharePoint が HTML を勝手に書き換えるため、共通パーツと\n"
     "     検査ツールの正本は ③ 側へ移した（2026-08-02）。"),
    ("正本（せいほん）",
     "「これが正しい」と決めた唯一の置き場所。同じものが 2 か所にあると\n"
     "     必ずどちらかが古くなるので、領域ごとに 1 つだけと決めている。"),
    ("共通パーツ / partials",
     "全ページの上部に入る共通ヘッダーと、アクセス解析タグ。\n"
     "     正本は ③ の _partials/。inject で全ページへ配る。"),
    ("inject（インジェクト）",
     "共通パーツを全ページへ反映する処理。ページ側のヘッダー部分は\n"
     "     自動生成なので、直接編集せずここから配る。"),
    ("sitemap（サイトマップ）",
     "検索エンジンに「どのページがあるか」を伝える一覧。手書きすると\n"
     "     載せ忘れ・消し忘れが必ず起きるので自動生成している。"),
    ("汚染（おせん）",
     "SharePoint が HTML に書き込む余計なデータのこと。ページの\n"
     "     <title> が空にされるため、そのまま公開すると検索順位に響く。"),
    ("drift（ドリフト）",
     "②' と ③ の中身がずれること。片方だけ直すと起きる。"),
    ("フック / pre-commit",
     "commit しようとしたとき自動で走る検査。問題があれば commit を\n"
     "     止める。端末ごとに導入が必要（doctor で確認できる）。"),
]

CHECKS = [
    ("ガードの自己テスト", ["_tools/test_guards.py"],
     "検査そのものが壊れていないか"),
    ("SharePoint 汚染検査", ["_tools/check-contamination.py", "--all"],
     "余計なデータや空タイトルが混ざっていないか"),
    ("共通パーツの反映確認", ["_partials/inject.py", "--check"],
     "ヘッダーが全ページへ行き渡っているか"),
    ("sitemap の整合確認", ["_tools/gen-sitemap.py", "--check"],
     "ページ一覧が最新か"),
    ("不変条件の確認", ["_tools/check-invariants.py"],
     "CNAME など消えたら困るものが消えていないか"),
    ("UTM の規約確認", ["_tools/check-utm.py", "--both"],
     "計測用パラメータが GA4 で判定できる値になっているか"),
]


# ── 小道具 ────────────────────────────────────────────────────────────
def git(*args, check=False):
    r = subprocess.run(["git", "-C", str(ROOT), *args],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r


def run_script(rel_args, quiet=False):
    """_tools/*.py を実行して (ok, 出力) を返す。"""
    cmd = [PY, str(ROOT / rel_args[0]), *rel_args[1:]]
    if not quiet:
        print(f"  $ {Path(rel_args[0]).name} {' '.join(rel_args[1:])}".rstrip())
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def hr(title=""):
    print("\n" + (f"── {title} " + "─" * max(0, 56 - len(title)) if title else "─" * 60))


def current_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def device_id():
    """作業ブランチ名に入れる端末名。どの端末からの変更か一目で分かるように。"""
    import re
    import socket
    name = socket.gethostname().split(".")[0].lower()
    return re.sub(r"[^a-z0-9-]+", "-", name).strip("-") or "device"


def new_work_branch():
    from datetime import datetime
    return f"work/{device_id()}/{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def repo_web_url():
    """git@github.com:owner/repo.git → https://github.com/owner/repo"""
    url = git("remote", "get-url", "origin").stdout.strip()
    if url.startswith("git@"):
        url = "https://" + url[4:].replace(":", "/", 1)
    return url[:-4] if url.endswith(".git") else url


def is_work_branch(name):
    return name.startswith("work/")


def branch_is_merged(branch):
    """この作業ブランチの変更が origin/main に取り込まれているか。

    祖先判定（git branch --merged）は使えない。PR をスカッシュマージすると
    枝のコミットは main の祖先にならないため、常に「未マージ」と判定される。
    内容の完全一致も使えない。他の PR が先に入って main が進んでいると差分が
    出る。

    そこで「この枝が触ったファイルが、いま main と同じ内容になっているか」で
    判定する。枝の仕事が main に入っていれば真になり、main 側でその後さらに
    変更されていれば偽（＝安全側に倒れる）。
    """
    if git("merge-base", "--is-ancestor", "HEAD", "origin/main").returncode == 0:
        return True                      # 通常のマージコミットの場合
    base = git("merge-base", "origin/main", "HEAD").stdout.strip()
    if not base:
        return False
    files = [f for f in git("diff", "--name-only", base, "HEAD").stdout.splitlines() if f]
    if not files:
        return True                      # 枝が何も変えていない
    return git("diff", "--quiet", "origin/main", "HEAD", "--", *files).returncode == 0


# ── 状態 ──────────────────────────────────────────────────────────────
def collect_status():
    st = {}
    st["repo"] = str(ROOT)
    st["branch"] = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    st["dirty"] = bool(git("status", "--porcelain").stdout.strip())
    st["dirty_count"] = len([l for l in git("status", "--porcelain").stdout.splitlines() if l])

    git("fetch", "--quiet", "origin")
    ab = git("rev-list", "--left-right", "--count", "origin/main...HEAD").stdout.split()
    st["behind"], st["ahead"] = (int(ab[0]), int(ab[1])) if len(ab) == 2 else (0, 0)

    hook = ROOT / ".git" / "hooks" / "pre-commit"
    tracked = ROOT / "_tools" / "hooks" / "pre-commit"
    st["hook_installed"] = hook.is_file()
    st["hook_current"] = (st["hook_installed"] and tracked.is_file()
                          and hook.read_bytes() == tracked.read_bytes())

    od = hublib.onedrive_root()
    st["onedrive"] = str(od) if od else None
    st["last_commit"] = git("log", "-1", "--format=%h %ad %s", "--date=short").stdout.strip()
    return st


def print_status(st):
    hr("いまの状態")
    print(f"  作業フォルダ : {st['repo']}")
    print(f"  ブランチ     : {st['branch']}")
    print(f"  最新の記録   : {st['last_commit']}")
    print()
    if st["dirty"]:
        print(f"  ● 未保存の変更が {st['dirty_count']} 件あります（まだ GitHub に送られていません）")
    else:
        print("  ○ 未保存の変更はありません")
    if st["behind"]:
        print(f"  ● GitHub 側に {st['behind']} 件の新しい変更があります（取得が必要）")
    else:
        print("  ○ GitHub の最新に追いついています")
    if st["ahead"]:
        print(f"  ● 手元に {st['ahead']} 件の未送信の記録があります")
    if not st["hook_installed"]:
        print("  ▲ 自動検査（フック）が入っていません → メニュー 2 で確認")
    elif not st["hook_current"]:
        print("  ▲ 自動検査（フック）が古い版です → メニュー 2 で確認")
    else:
        print("  ○ 自動検査（フック）は最新版が入っています")
    print(f"  {'○' if st['onedrive'] else '▲'} OneDrive 側: "
          f"{st['onedrive'] or '見つかりません（制作フォルダが同期されていない可能性）'}")


# ── サブコマンド ──────────────────────────────────────────────────────
def cmd_status(args):
    st = collect_status()
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0
    print_status(st)
    return 0


def cmd_doctor(args):
    st = collect_status()
    problems, warns = [], []

    if st["branch"] != "main":
        warns.append(f"ブランチが main ではありません: {st['branch']}")
    if not st["hook_installed"]:
        problems.append("自動検査（フック）が入っていません")
    elif not st["hook_current"]:
        problems.append("自動検査（フック）が追跡版と違います（古い可能性）")
    if st["onedrive"] is None:
        # 警告ではなく問題として扱う。ここが解決しないと pre-commit ガードが
        # fail-closed で commit を止める（Windows 機で実際に起きた）。
        found = hublib.discover_onedrive_roots()
        if len(found) > 1:
            problems.append("OneDrive 側の候補が複数見つかり、どれか判断できません:\n"
                            + "\n".join(f"       {p}" for p in found))
        else:
            problems.append("OneDrive 側の制作フォルダが見つかりません"
                            "（この状態では commit がガードで止まります）")
    if st["behind"]:
        warns.append(f"GitHub 側に {st['behind']} 件の新しい変更があります")

    r = git("config", "--get", "user.email")
    if not r.stdout.strip():
        problems.append("git のメールアドレスが未設定です（commit できません）")
    if sys.version_info < (3, 8):
        problems.append(f"Python が古すぎます: {sys.version.split()[0]}")

    if args.json:
        print(json.dumps({"problems": problems, "warnings": warns, "status": st},
                         ensure_ascii=False, indent=1))
        return 2 if problems else 0

    hr("この端末の設定を確認")
    print(f"  Python       : {sys.version.split()[0]}")
    print(f"  git ユーザー : {git('config','--get','user.name').stdout.strip()} "
          f"<{r.stdout.strip()}>")
    print()
    for p in problems:
        print(f"  ✗ {p}")
    for w in warns:
        print(f"  ▲ {w}")
    if not problems and not warns:
        print("  ✓ 問題ありません")
    if not st["hook_installed"] or not st["hook_current"]:
        print("\n  【直し方】次のコマンドで自動検査を入れ直せます:")
        print(f"    cd {ROOT}")
        print("    cp _tools/hooks/pre-commit .git/hooks/    （Windows は copy）")
    if st["onedrive"] is None:
        print("\n  【直し方】制作フォルダの場所を環境変数で指定できます:")
        print("    macOS   : export HUB_ONEDRIVE_ROOT=\"/path/to/00_hub_zotac\"")
        print("    Windows : setx HUB_ONEDRIVE_ROOT \"C:\\path\\to\\00_hub_zotac\"")
        print("    ※ 恒久的に必要になる場合は、パスを報告して hublib.py 側へ")
        print("       登録してください（端末ごとの設定を増やさないため）")
    return 2 if problems else 0


def cmd_sync(args):
    hr("GitHub から最新を取得")
    st = collect_status()
    branch = st["branch"]

    if st["dirty"]:
        print(f"  ✗ 未保存の変更が {st['dirty_count']} 件あります。")
        print("     取得すると衝突するおそれがあるため中止しました。")
        print("     先に公開（メニュー 5）を済ませるか、変更内容を確認してください。")
        return 1

    git("fetch", "--prune", "--quiet", "origin")

    # 作業ブランチにいる場合、取り込み済みなら main へ戻して片付ける。
    # 放置すると次の公開が古い枝から分岐してしまう。
    if is_work_branch(branch):
        if not branch_is_merged(branch):
            print(f"  ▲ いま作業ブランチ {branch} にいます（まだ取り込まれていません）。")
            print("     PR がマージされてからもう一度実行してください。")
            print("     マージ済みなのにこう出る場合は、この枝が触ったファイルが")
            print("     その後 main 側でさらに変更されています。報告してください。")
            return 1

        print(f"  作業ブランチ {branch} は GitHub 側へ取り込み済みです。")
        print("  main へ戻して片付けます…")
        r = git("checkout", "main")
        if r.returncode != 0:
            print("  ✗ main へ戻れませんでした: " + (r.stderr or "").strip())
            return 1
        git("merge", "--ff-only", "origin/main")
        # -d ではなく -D。スカッシュマージだと枝のコミットは main の祖先に
        # ならないため、-d は「未マージ」と判断して拒否する。
        git("branch", "-D", branch)
        rm = git("push", "origin", "--delete", branch)
        print(f"  ✓ main に戻り、{branch} を削除しました"
              + ("（リモートも削除）" if rm.returncode == 0 else "（リモートは既に削除済み）"))
        return 0

    if not st["behind"]:
        print("  ○ すでに最新です。取得するものはありません。")
        return 0
    print(f"  GitHub 側の新しい変更 {st['behind']} 件を取得します…")
    r = git("merge", "--ff-only", "origin/main")
    print("  " + (r.stdout or r.stderr).strip().replace("\n", "\n  "))
    if r.returncode != 0:
        print("\n  ✗ 自動で取り込めませんでした（手元と GitHub の両方に変更がある状態）。")
        print("     この状態は自力で直さず、内容を報告してください。")
        return 1
    print("  ✓ 取得しました")
    return 0


def cmd_check(args):
    if not args.json:
        hr("検査（何も書き換えません）")
    results, ok_all = [], True
    for name, rel, why in CHECKS:
        ok, out = run_script(rel, quiet=True)
        results.append({"name": name, "ok": ok, "output": out})
        ok_all &= ok
        if not args.json:
            print(f"  {'✓' if ok else '✗'} {name} … {why}")
            if not ok:
                for line in out.strip().splitlines()[-12:]:
                    print(f"        {line}")
    if args.json:
        print(json.dumps({"ok": ok_all, "results": results}, ensure_ascii=False, indent=1))
    elif ok_all:
        print("\n  ✓ すべて問題なし")
    else:
        print("\n  ✗ 問題が見つかりました。自力で直さず、上の出力を報告してください。")
    return 0 if ok_all else 1


def cmd_publish(args):
    hr("公開の準備")
    if cmd_doctor(argparse.Namespace(json=False)) == 2:
        print("\n  ✗ 端末の設定に問題があります。先にそちらを解決してください。")
        return 2

    # 過去の作業ブランチに残っていたら main へ戻す（PR 方式だった頃の名残）。
    # 未保存の変更は checkout をまたいで保持される。
    st = collect_status()
    if is_work_branch(st["branch"]) and branch_is_merged(st["branch"]):
        old = st["branch"]
        print(f"\n  前回の作業ブランチ {old} は取り込み済みです。main へ戻します…")
        # 切り替える前にローカル main を origin/main へ進めておく。古いままだと
        # 「作業中のファイルが checkout で上書きされる」と言われて切り替えられない
        # （その差分は既に取り込み済みの内容なので、進めてから移るのが正しい）。
        if git("merge-base", "--is-ancestor", "main", "origin/main").returncode == 0:
            git("branch", "-f", "main", "origin/main")
        if git("checkout", "main").returncode != 0:
            print("  ✗ main へ戻れませんでした（変更が衝突している可能性）。報告してください。")
            return 1
        git("branch", "-D", old)
        git("push", "origin", "--delete", old)
        print(f"  ✓ main に戻り、{old} を片付けました")
        st = collect_status()

    # 公開時は「未保存の変更がある」のが正常なので dirty は止めない。
    # 止めるのは「GitHub 側に自分が持っていない変更がある」場合だけ。
    # そのまま進めると他の端末での作業を上書きする形になるため。
    if st["behind"]:
        print(f"\n  ✗ GitHub 側に {st['behind']} 件の新しい変更があります。")
        print("     先に取得（メニュー 3）してから公開してください。")
        if st["dirty"]:
            print("     ※ 未保存の変更があるため自動では取得できません。報告してください。")
        return 1

    # 取り込みを publish に内包する。手コピーの余地を残すと、規約でしか
    # 「import が唯一の経路」を担保できない（Codex 指摘）。経路が 1 本になれば
    # ②'↔③ のずれ自体が起きにくくなり、drift 検査を持つ必要がなくなる。
    if args.paths:
        if cmd_import(argparse.Namespace(paths=args.paths, json=False,
                                         verbose=args.verbose,
                                         delete=getattr(args, "delete", False))) != 0:
            return 1

    hr("共通パーツと sitemap を反映")
    for rel in (["_partials/inject.py"], ["_tools/gen-sitemap.py"]):
        ok, out = run_script(rel)
        tail = [l for l in out.strip().splitlines() if l.strip()][-1:]
        print("    " + (tail[0] if tail else ""))
        if not ok:
            print("  ✗ 反映に失敗しました。報告してください。")
            return 1

    if cmd_check(argparse.Namespace(json=False)) != 0:
        return 1

    hr("公開する内容")
    st = collect_status()
    if not st["dirty"] and not st["ahead"]:
        print("  ○ 公開するものはありません（すでに最新の状態です）")
        return 0
    if st["dirty"]:
        print(git("status", "--short").stdout.rstrip())
        print()
        print(git("diff", "--stat").stdout.rstrip())
    if st["ahead"]:
        print(f"\n  未送信の記録 {st['ahead']} 件:")
        print(git("log", "--oneline", f"-{st['ahead']}").stdout.rstrip())

    if getattr(args, "dry_run", False):
        print("\n  （--dry-run）ここで終了します。commit も push もしていません。")
        print("      取り込みと反映は実行済みなので、作業ツリーには変更が残ります。")
        # 以前ここは `git checkout -- . && git clean -fd` を案内していたが、
        # 作業ツリーは複数セッションで共有される。2026-08-14 に、この案内どおりの
        # 操作が別セッションの未コミット作業（ガード1本＋10ページの清掃）を
        # 巻き添えで消した。追跡外のファイルは clean で消えるため git からも
        # 復旧できない。退避（stash）なら取り違えても戻せるので、こちらを案内する。
        print("      戻すには: git stash -u   （破棄せず退避。git stash pop で戻せる）")
        print("      ⚠ 作業ツリーは他のセッションと共有です。まず git status で")
        print("         自分以外の変更が無いか確認してください（破棄する操作は案内しません）。")
        return 0

    if not args.yes:
        print()
        try:
            if input("  この内容で公開しますか？ [y/N]: ").strip().lower() not in ("y", "yes"):
                print("  中止しました。何も変更していません。")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n  中止しました。")
            return 0

    # main へ直接 push する。2026-08-03 に Pages の配信を「CI 通過後の deploy
    # job だけ」へ移したため、PR を挟まなくても未検査のものは公開されない。
    # ブランチ保護の PR 必須もこれに合わせて解除済み。
    if st["branch"] != "main":
        print(f"\n  ✗ いま main にいません（{st['branch']}）。")
        print("     メニュー 3（最新を取得）で main へ戻してから実行してください。")
        return 1

    if st["dirty"]:
        msg = args.message or input("  変更内容の説明を一行で: ").strip() or "content: 更新"
        git("add", "-A")
        r = git("commit", "-m", msg)
        print("  " + (r.stdout or r.stderr).strip().replace("\n", "\n  "))
        if r.returncode != 0:
            print("\n  ✗ 自動検査が commit を止めました。上の理由を確認してください。")
            print("     ※ 検査を迂回する操作（--no-verify）は絶対に使わないでください。")
            return 1

    hr("GitHub へ送信")
    r = git("push", "origin", "main")
    print("  " + (r.stdout or r.stderr).strip().replace("\n", "\n  "))
    if r.returncode != 0:
        print("  ✗ 送信できませんでした。報告してください。")
        return 1

    print("\n  ✓ 送信しました。この後 GitHub 側で検査が走り、")
    print("    通過した場合だけ公開されます（通常 1〜3 分）。")
    print(f"    実行状況: {repo_web_url()}/actions")
    print("    公開の確認: https://hub.zotac.co.jp/")
    return 0


def cmd_import(args):
    """②' OneDrive から ③ へ取り込む。HTML は取り込み時に清浄化する。"""
    import shutil
    from sanitize import to_hub

    hr("②' から取り込み")
    od = hublib.onedrive_root()
    if od is None:
        print("  ✗ OneDrive 側の制作フォルダが見つかりません（doctor を実行してください）")
        return 2
    src_root, dst_root = od / "index", ROOT

    targets = []
    for spec in args.paths:
        s = src_root / spec
        if not s.exists():
            print(f"  ✗ ②' に見つかりません: {spec}")
            return 1
        targets += [s] if s.is_file() else [p for p in sorted(s.rglob("*")) if p.is_file()]

    copied = cleaned = skipped = 0
    blocked = []
    for s in targets:
        rel = s.relative_to(src_root).as_posix()
        if not hublib.in_published_scope(rel):
            skipped += 1
            continue
        d = dst_root / rel
        if s.suffix.lower() in hublib.MARKUP_SUFFIXES:
            text = s.read_text(encoding="utf-8", errors="replace")
            previous = d.read_text(encoding="utf-8", errors="replace") if d.is_file() else None
            out, fixes, unresolved = to_hub(text, previous)
            if unresolved:
                blocked.append((rel, unresolved))
                continue
            if fixes:
                cleaned += 1
                if args.verbose:
                    print(f"  ○ {rel}")
                    for x in fixes:
                        print(f"       {x}")
            d.parent.mkdir(parents=True, exist_ok=True)
            with open(d, "w", encoding="utf-8", newline="") as fh:
                fh.write(out)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            # copy2 ではなく copyfile。copy2 は OneDrive 側のパーミッション
            # （rwx------）まで複製し、git が 216 件のモード変更として拾って
            # しまった。持ってくるのは中身だけでよい。
            shutil.copyfile(s, d)
        copied += 1

    # ②' で消したファイルが ③ に残り続ける問題への対処。取り込みは「②' に
    # 今あるもの」しか見ないため、削除が伝播しない。消したはずのページが公開
    # され続け、sitemap も ③ の実体から作るので検査も通ってしまう。
    # 取り込んだ範囲に限って、②' に無い ③ のファイルを候補として挙げる。
    stale = []
    for spec in args.paths:
        d = dst_root / spec
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(dst_root).as_posix()
            if not hublib.in_published_scope(rel) or hublib.is_deploy_only(rel):
                continue
            if not (src_root / rel).is_file():
                stale.append(rel)

    print(f"\n  取り込み: {copied} 件（うち清浄化 {cleaned} 件）"
          f" / 対象外 {skipped} 件")

    if stale:
        print(f"\n  ②' に無いのに ③ に残っているファイル: {len(stale)} 件")
        for rel in stale:
            print(f"     {rel}")
        if getattr(args, "delete", False):
            for rel in stale:
                (dst_root / rel).unlink()
            print(f"  → {len(stale)} 件を削除しました（--delete 指定）")
            print("     ※ 公開停止するページはリダイレクトの要否も確認すること")
        else:
            print("  → 削除していません。②' で意図的に消したものなら --delete を")
            print("     付けて再実行してください（このままでは公開され続けます）。")

    if blocked:
        print(f"\n  ✗ 取り込めなかったファイル {len(blocked)} 件"
              "（title が空で復元元が無い。公開すると SEO 上の損失になる）:")
        for rel, why in blocked:
            print(f"     {rel}  [{', '.join(why)}]")
        print("\n     これらは報告してください。生成し直すか、別の復元元が要ります。")
        return 1
    print("\n  次は 公開（メニュー 5 / hub.py publish）で反映・検査・送信まで行えます。")
    return 0


def cmd_glossary(args):
    hr("用語")
    for term, desc in GLOSSARY:
        print(f"\n  ■ {term}")
        print(f"     {desc}")
    return 0


# ── 対話メニュー ──────────────────────────────────────────────────────
MENU = [
    ("1", "いまの状態をみる", "何が同期されていて、何が未送信かを表示します", cmd_status),
    ("2", "この端末の設定を確認する", "自動検査が入っているか等を調べます（doctor）", cmd_doctor),
    ("3", "GitHub から最新を取得する", "他の端末での変更を受け取ります（ダウンロード）", cmd_sync),
    ("4", "検査だけ実行する", "何も書き換えずに問題がないか調べます", cmd_check),
    ("5", "公開する", "取り込み → 反映 → 検査 → 送信。検査を通ったものだけが公開されます", cmd_publish),
    ("6", "用語をみる", "②' や 正本 などの言葉の意味", cmd_glossary),
]


def menu():
    ns = argparse.Namespace(json=False, yes=False, message=None, verbose=False,
                            paths=None, delete=False, dry_run=False)
    print("=" * 60)
    print("  hub.zotac.co.jp  取得・検査・公開ツール")
    print("=" * 60)
    print("\n  ※ 通常は Claude に依頼すれば同じことをやってくれます。")
    print("     これは自分で状況を確かめたいとき用の入口です。")
    try:
        print_status(collect_status())
    except Exception as e:
        print(f"\n  状態を取得できませんでした: {e}")

    while True:
        hr("メニュー")
        for key, label, desc, _ in MENU:
            print(f"  {key}. {label}")
            print(f"     {desc}")
        print("  0. 終了")
        try:
            sel = input("\n  番号を入力: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  終了します。")
            return 0
        if sel in ("0", "q", ""):
            print("  終了します。")
            return 0
        for key, label, _, fn in MENU:
            if sel == key:
                try:
                    fn(ns)
                except Exception as e:
                    print(f"\n  エラー: {e}")
                break
        else:
            print("  その番号はありません。")
        try:
            input("\n  Enter で メニューに戻ります…")
        except (EOFError, KeyboardInterrupt):
            return 0


def main():
    hublib.use_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    for name, fn in (("status", cmd_status), ("doctor", cmd_doctor), ("sync", cmd_sync),
                     ("check", cmd_check), ("publish", cmd_publish),
                     ("import", cmd_import), ("glossary", cmd_glossary)):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true", help="機械可読な出力")
        p.set_defaults(func=fn)
        if name == "publish":
            p.add_argument("paths", nargs="*", help="②' index/ から取り込むパス（省略可）")
            p.add_argument("--delete", action="store_true",
                           help="②' に無い ③ のファイルを削除する（公開停止）")
            p.add_argument("--yes", action="store_true", help="確認を省略")
            p.add_argument("-m", "--message", help="変更内容の説明")
            p.add_argument("-v", "--verbose", action="store_true", help="取り込みを1件ずつ表示")
            p.add_argument("-n", "--dry-run", action="store_true",
                           help="検査と変更内容の確認まで。commit も push もしない")
        if name == "import":
            p.add_argument("paths", nargs="+", help="②' index/ からの相対パス")
            p.add_argument("-v", "--verbose", action="store_true", help="1件ずつ表示")
            p.add_argument("--delete", action="store_true",
                           help="②' に無い ③ のファイルを削除する（公開停止）")
    args = ap.parse_args()
    if not args.cmd:
        return menu()
    for a, default in (("yes", False), ("message", None), ("verbose", False),
                       ("paths", None), ("delete", False), ("dry_run", False)):
        if not hasattr(args, a):
            setattr(args, a, default)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
