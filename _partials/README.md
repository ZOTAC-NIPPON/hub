# _partials — hub 共通パーツの単一ソース（正本）

hub.zotac.co.jp の全ページに共通の塊（ヘッダー・計測タグ・配色）をここ1か所に集約する。
**ヘッダーを直すときは、このフォルダのファイル（標準は `header.html`、バリアントは `header-<variant>.html`）だけを編集**し、下の方法で全ページへ反映する。
ページ個別にヘッダーを手書き・改変しない（ページごとにずれて「毎回おかしくなる」原因になる）。

## ファイル
| ファイル | 役割 |
|---|---|
| `header.html` | 共通ヘッダーの正本。**CSS・JS を同梱した自己完結型**（ダーク／幅1100px）。ページ側 CSS に依存しない |
| `header-<variant>.html` | バリアント（例 `header-light.html`＝白ベースのキャンペーン用）。必要になったら作る（2026-09-25 時点で無し） |
| `analytics.html` | GA4 / Clarity 計測タグの正本 |
| `design-tokens.md`・`zotac-tokens.css` | **既定の配色・タイポの正本**（指定がない場合の HTML/LP/企画書の基調） |
| `inject.py` | 各ページのマーカー区間へ注入するスクリプト。**このリポジトリの中でだけ動かす** |

## 反映方法
- **手書きのページ**（②' `index/` の top・reviews 一覧・press・catalogs/index・trial-program・case-studies・キャンペーン LP など）:
  `hub.py publish` が取り込むたびに、このリポジトリ全体へ `inject.py` を実行して注入する。
  このフォルダだけを直したときの手順は、リポジトリ直下の `README.md`「共通パーツ（`_partials/`）だけを直したとき」。
  **②' や OneDrive では `inject.py` を実行しない**（2026-08-02 の HTML 汚染事故の原因。経緯は制作ツリー側の `HUB_HISTORY.md`）。
- **生成ページ**（② `hub-zotac-production` の `_brochure_poc` にある `build_pages.py`・`build_enterprise.py`・`_gpu_gen.py`）:
  生成器が `_partials_src.py` 経由でこのフォルダの `header.html` を読み、同じ形のマーカーで埋め込む。汚染されたパーツを掴んだら例外で止まる。再生成で反映される。

## 仕組み・約束
- ページ内を `<!-- @partial:header START ... -->` 〜 `<!-- @partial:header END -->` で囲って管理する（何度実行しても同じ結果）。
- `is-active`（現在地ハイライト）は**注入側がページ階層から自動付与**する。正本には書かない。
  - `inject.py` … パスの先頭セグメントで判定（reviews → /reviews/ など）
  - 生成器 … カタログ面なので一律 `/catalogs/`
- バリアント … ページ側マーカーに `variant=light` があれば `header-light.html` を使う。
- ルート相対パス（`/assets/...`）が前提。ページは hub と同じ web ルートに展開すること。
