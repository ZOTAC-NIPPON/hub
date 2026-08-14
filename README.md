# hub.zotac.co.jp — 公開リポジトリ

[hub.zotac.co.jp](https://hub.zotac.co.jp/) の**公開物**と、その公開を担う仕組み。
GitHub Pages で配信している。

## このリポジトリの位置づけ

サイトの記事・カタログは **OneDrive(SharePoint) 上の制作ツリー（②'）** で作り、
ここへ取り込んで公開する。**このリポジトリはその派生物**で、単純なコピーではない。
取り込みの際に次の変換が入る。

1. SharePoint がHTMLへ書き込む列メタデータの除去（後述）
2. 失われた `<title>` の復元
3. 共通ヘッダー・計測タグの注入（`_partials/`）
4. `sitemap.xml` の再生成

一方、**`_partials/` と `_tools/` はこのリポジトリが正本**。OneDrive 側には置かない。

## 使い方

```bash
cd ~/Developer/hub                      # Windows は %USERPROFILE%\Documents\projects\hub
python3 _tools/hub.py publish catalogs/gpu -m "何を変えたか"
```

引数のパスは **②' の `index/` からの相対パス**。これ 1 本で
取り込み → 清浄化 → 共通パーツ反映 → sitemap 更新 → 検査 → commit → push まで通る。
push 後は GitHub 側で検査が走り、**通過した場合だけ公開される**（1〜3 分）。

| コマンド | 用途 |
|---|---|
| `hub.py`（引数なし） | 対話メニュー。用語の説明つき。`hub.command` / `hub.bat` をダブルクリックでも開く |
| `hub.py status` | いまの状態（未送信の有無・同期状況・フックの導入状況） |
| `hub.py doctor` | この端末の設定が正しいか。問題があれば直し方も出る |
| `hub.py sync` | GitHub から最新を取得 |
| `hub.py check` | 検査だけ（何も書き換えない） |
| `hub.py publish [パス]` | 取り込み → 検査 → 公開 |
| `hub.py glossary` | 用語 |

AI エージェントから叩く場合は `--json` を付けると機械可読な出力になる。

## 公開されるまで

```
publish → push → GitHub Actions
                   ├ hub-validate  … 6 検査
                   ├ build         … 成果物を組み立て（hub-validate 成功が前提）
                   └ deploy        … Pages へ配信（build 成功が前提）
```

**検査に落ちたものは配信されない。** そのため main への直接 push を許している。
壊れたものが記録に残ることはあっても、公開されることはない。

`_` と `.` で始まるものは成果物から除外する（`_partials/` `_tools/` `.github/` 等）。
※ただし**このリポジトリは public なので、それらは GitHub 上では誰でも読める**。
「サイトで 404」＝「非公開」ではない。機密情報は置かないこと。

## 検査の中身

| 検査 | 何を見るか |
|---|---|
| `test_guards.py` | 検査そのものが壊れていないか（既知の異常サンプルを検出できるか） |
| `check-contamination.py` | SharePoint 由来のメタデータ混入・空タイトル・`<head>` 重複 |
| `inject.py --check` | 共通ヘッダーが全ページへ行き渡っているか |
| `gen-sitemap.py --check` | ページ一覧が最新か |
| `check-invariants.py` | CNAME 等、消えると壊れるものが消えていないか／共通ヘッダーの CSS がページ側に複製されていないか |
| `check-utm.py` | 計測用パラメータが GA4 で判定できる値か（規約は `_tools/analytics/utm-policy.md`） |

`.git/hooks/pre-commit` も同種の検査を commit 時に行う（未導入なら `hub.py doctor` が指摘）。

### UTM は閉じたリストからしか選べない（2026-08-14 追加）

外部から hub へ送るリンクの `utm_*` は `_tools/analytics/utm-policy.md` が正本で、
値の登録簿は同ディレクトリの `utm-taxonomy.json`（medium の閉じたリスト・source の
登録簿）と `campaigns.json`（キャンペーン登録簿）。**規約・登録簿・検査の3点で1組**
なので、どれか1つだけ直さない。

2026-07〜08 の GA4 で**セッションの 23%（162/711）が Unassigned**（チャネル判定不能）
になっていた。X 投稿の UTM が `utm_source=x` / `utm_medium=article` で、GA4 の
ソースカテゴリ一覧に `x` が無く `article` もどのチャネル定義にも一致しないため、
**UTM を丁寧に付けた投稿ほど計測できなくなっていた**（付けていない X 流入は `t.co`
のリファラで正しく Organic Social に入る、という逆転）。値を1つ間違えるだけで起きる
ので機械で止める。

ローカルの `hub.py check` は `--both` で ②' の投稿下書きまで見る。CI は ②' に到達
できないので ③ の公開物だけ（内部リンクへの UTM 混入）を見る。投稿済みで訂正できない
記録は `utm-taxonomy.json` の `legacy_records` に列挙してあり、**減らす方向にしか
変えない**（新しい項目を足したくなったら、それは直すべき違反）。

### 共通ヘッダーの CSS をページに書かない（2026-08-14 追加）

ヘッダーの見た目を決める CSS は `_partials/header.html` だけに置く。ページ側の
`<style>` に `.site-header` / `.site-nav` / `.nav-toggle` 等を書くと
`check-invariants.py` が公開を止める。

`inject.py` が差し替えるのはマークアップだけなので、制作時のプレビュー用に書いた
ヘッダー CSS は注入後もページに残る。公開版では partial 側
（`.site-header .site-header-inner` ＝クラス2個）が詳細度で勝つため見た目は正常で、
30 ページで気づかれないまま残っていた。実害は「②' のプレビューが本番と違う幅で出る」
ことと、「partial のセレクタを 1 段浅くした瞬間に全ページが静かに壊れる」こと。

制作時にヘッダー付きでプレビューしたいときは、②' のページに
`<!-- @partial:header START … END -->` ブロックごと持たせる（注入で毎回上書きされる
生成物として扱う）。ページごとにヘッダーの見た目を変えたい場合は、ページ CSS で
上書きせず `header-<variant>.html` を作る。

移行が済んでいないページは `check-invariants.py` の `HEADER_CSS_LEGACY` に列挙してある。
**この名簿は減らす方向にしか変えない**（新しいページを足したくなったら、それは直すべき複製）。

## SharePoint による HTML の書き換えについて

制作ツリーが置かれている SharePoint ドキュメントライブラリは、格納された HTML に
列メタデータを書き込むことがある。`<html>` への `xmlns:mso` 属性、`</head>` 直前の
`<!--[if gte mso 9]><xml>…` ブロック、そして **`<title>` の中身が空になる**。

2026-08-02 に 185 件で確認し、対処済み。取り込み時に自動で除去・復元するため、
公開物には影響しない。詳細と経緯は制作ツリー側の `HUB.md` §4。

## 守ること

- **このリポジトリのサイト内容を直接編集しない。** 編集は ②' 側で行い `hub.py publish` で取り込む
  （`_partials/` と `_tools/` はここが正本なので直接編集してよい）
- **`inject.py` や生成器を ②' に対して実行しない。** 実行するのはこのリポジトリの中だけ
- **共通ヘッダーの CSS をページ側に書かない**（→ 「検査の中身」節）
- **`git commit --no-verify` を使わない。** フックが止めたら理由がある
- **`git push --force` を使わない**（サーバ側でも禁止している）
- **`.nojekyll` を作らない**

## 新しい端末で使い始める

```bash
git clone git@github.com:ZOTAC-NIPPON/hub.git ~/Developer/hub
cd ~/Developer/hub
cp _tools/hooks/pre-commit .git/hooks/ && chmod +x .git/hooks/pre-commit
python3 _tools/hub.py doctor
```

リポジトリの置き場所は端末ごとに違ってよい（`~/Developer/hub` か
`~/Documents/projects/hub`。ツールは中身で探索する）。
**クラウド同期フォルダの配下には置かないこと** — `.git` は多数の小ファイルの集合体で、
同期と併用すると競合コピーでリポジトリが壊れる。

Python 3.8 以上が必要。`doctor` が「問題ありません」になれば準備完了。

## 制作側のドキュメント

サイトの作り方・記事の制作手順・数値の正本などは、OneDrive 側の `HUB.md`
（全体の索引）と各フォルダの `CLAUDE.md` を参照。
