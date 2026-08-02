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
  python3 _tools/hub.py publish      # 反映 → 検査 → commit → push

終了コード: 0 = OK / 1 = 検査違反・作業未完了 / 2 = 環境エラー

設計方針:
  - 最後の 1 歩（commit / push）の直前まで、何も書き換えない
  - 失敗したら止まる。勝手に直さない
  - git を隠さない。何を実行したかは常に表示する
"""

import argparse
import json
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
        warns.append("OneDrive 側の制作フォルダが見つかりません")
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
    return 2 if problems else 0


def cmd_sync(args):
    hr("GitHub から最新を取得")
    st = collect_status()
    if st["dirty"]:
        print(f"  ✗ 未保存の変更が {st['dirty_count']} 件あります。")
        print("     取得すると衝突するおそれがあるため中止しました。")
        print("     先に公開（メニュー 5）を済ませるか、変更内容を確認してください。")
        return 1
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

    # 公開時は「未保存の変更がある」のが正常なので dirty は止めない。
    # 止めるのは「GitHub 側に自分が持っていない変更がある」場合だけ。
    # そのまま進めると他の端末での作業を上書きする形になるため。
    st = collect_status()
    if st["behind"]:
        print(f"\n  ✗ GitHub 側に {st['behind']} 件の新しい変更があります。")
        print("     先に取得（メニュー 3）してから公開してください。")
        if st["dirty"]:
            print("     ※ 未保存の変更があるため自動では取得できません。報告してください。")
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

    if not args.yes:
        print()
        try:
            if input("  この内容で公開しますか？ [y/N]: ").strip().lower() not in ("y", "yes"):
                print("  中止しました。何も変更していません。")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n  中止しました。")
            return 0

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
    print("\n  ✓ 公開しました。反映まで 1〜2 分かかります。")
    print("     確認: https://hub.zotac.co.jp/")
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
    ("5", "公開する", "反映 → 検査 → 記録 → 送信（アップロード）", cmd_publish),
    ("6", "用語をみる", "②' や 正本 などの言葉の意味", cmd_glossary),
]


def menu():
    ns = argparse.Namespace(json=False, yes=False, message=None)
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
                     ("check", cmd_check), ("publish", cmd_publish), ("glossary", cmd_glossary)):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true", help="機械可読な出力")
        p.set_defaults(func=fn)
        if name == "publish":
            p.add_argument("--yes", action="store_true", help="確認を省略")
            p.add_argument("-m", "--message", help="変更内容の説明")
    args = ap.parse_args()
    if not args.cmd:
        return menu()
    for a in ("yes", "message"):
        if not hasattr(args, a):
            setattr(args, a, None if a == "message" else False)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
