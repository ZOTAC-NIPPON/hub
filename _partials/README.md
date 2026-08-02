# _partials — hub 共通パーツの単一ソース（正本）

`00_hub_zotac` 配下 全プロジェクトのヘッダー等「全ページ共通の塊」をここ1か所に集約する。
**ヘッダーを直すときは `header.html` だけを編集** → 下記コマンドで全ページへ反映する。
ページ個別にヘッダーを手書き・改変しないこと（ドリフト＝「毎回おかしくなる」の元）。

## ファイル
| ファイル | 役割 |
|---|---|
| `header.html` | 共通ヘッダーの正本。**CSS・JSを同梱した自己完結型**（ダーク／幅1100px）。ページ側CSSに依存しない。 |
| `header-<variant>.html` | バリアント（例 `header-light.html`＝白ベースのキャンペーン用）。※必要時に追加。 |
| `analytics.html` | GA4 / Clarity 計測タグの正本。 |
| `design-tokens.md` | **既定の配色・タイポの正本**（指定がない場合の HTML/LP/企画書の基調）。 |
| `inject.py` | 各ページのマーカー区間へ注入するスクリプト。 |

## 反映方法（2系統）
- **手書きHTML**（`index/` 配下の top / reviews / press / catalogs/index / trial-program / case-studies 等）
  ```
  cd 00_hub_zotac
  python _partials/inject.py            # 反映
  python _partials/inject.py --check    # 差分確認のみ（CI/監査用・書き込まない）
  ```
- **生成HTML**（`build_pages.py`＝ZBOX / `build_enterprise.py`＝エンタープライズ）
  生成器が `header.html` を上方探索して読み込み、同形のマーカーで埋め込む。再ビルドで自動反映。

## 仕組み・約束
- ページ内を `<!-- @partial:header START ... -->` 〜 `<!-- @partial:header END -->` で囲って管理（冪等）。
- `is-active`（現在地ハイライト）は**注入側がページ階層から自動付与**。正本には書かない。
  - `inject.py` … パス先頭セグメントで判定（reviews→/reviews/ 等）
  - 生成器 … カタログ面なので一律 `/catalogs/`
- バリアント … ページ側マーカーに `variant=light` があれば `header-light.html` を採用。
- ルート相対パス（`/assets/...`）前提＝各プロジェクトは hub 同一 web ルートに展開すること。

## 未対応（次フェーズ）
- 兄弟プロジェクト `Reviews/` `2601_ZBOX_Trial_Campaign/` の各ソースは未取り込み（`inject.py` の `ONBOARD` に追加して取り込む。Campaign は `header-light.html` を作成のうえ variant 指定）。
- `index/_brochure_poc/catalog_zrs-*.html`（dev プレビュー）は旧ヘッダーのまま＝`build_enterprise.py` 再生成で更新。
