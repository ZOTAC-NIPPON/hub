# design-tokens.md — 既定の配色・タイポグラフィ（正本）

最終更新: 2026-08-09

> **特に指定がない場合、`00_hub_zotac` 配下で作る HTML 成果物（レビュー・LP・企画書・カタログ・社内資料）は
> この配色・タイポを既定とする。** 独自トーンを使うのは明示的な指定・意図があるときだけ
> （例: キャンペーン固有のアートディレクション）。その場合も判断を成果物側の README に残す。

出典＝実物から抽出: レビュー記事の `:root`（`Reviews\index\reviews\*\index.html`）／
`_partials\header.html`／ハブトップ `index\index.html`／ブロシュア方針（`index\_brochure_poc\README.md` §2）。

---

## 1. ベースパレット

| トークン | 値 | 用途 |
|---|---|---|
| `--yellow` | `#FFD400` | ZOTAC イエロー。唯一のアクセント。CTA・キーライン・強調に「流さず細く差す」 |
| `--yellow-hover` | `#F2C800` | イエローの hover / active |
| `--yellow-soft` | `rgba(255,212,0,.14)` | イエローの淡背景（ハイライト帯・タグ地） |
| `--dark` / `--ink` | `#2A2D2F` | グラファイト。ライト面の本文インク／ダーク面のパネル |
| `--ink-mid` | `#6D6E71` | 副次テキスト |
| `--ink-light` | `#9A9C9E` | 補足・キャプション |
| `--bg` | `#FFFFFF` | ライト面の基調背景 |
| `--bg-subtle` | `#FAFAFA` | セクション交互背景 |
| `--bg-soft` | `#F4F4F3` | カード・表ヘッダ地 |
| `--line` | `#E6E6E4` | 罫線 |
| `--line-strong` | `#C9CACB` | 強罫線・表外枠 |

**ダーク面**（ヒーロー・共通ヘッダー・フッターなど）: 背景 `#1A1B1C`（ニアブラック）／パネル `#2A2D2F`、
テキストは主 `#E5E5E6`・副 `#B1B3B6`・弱 `#7D8083`、アクセントは同じ `#FFD400`。

## 2. タイポグラフィ

- 本文: **Noto Sans JP**（`-apple-system,BlinkMacSystemFont,sans-serif` フォールバック）
- ラベル・型番・数値・等幅見出し: **JetBrains Mono**（`ui-monospace,Menlo,Consolas,monospace`）

## 3. コピペ用 `:root`（レビュー記事の実物と同一）

```css
:root{
  --yellow:#FFD400;
  --yellow-soft:rgba(255,212,0,.14);
  --dark:#2A2D2F;
  --ink:#2A2D2F;
  --ink-mid:#6D6E71;
  --ink-light:#9A9C9E;
  --bg:#FFFFFF;
  --bg-subtle:#FAFAFA;
  --bg-soft:#F4F4F3;
  --line:#E6E6E4;
  --line-strong:#C9CACB;
  --font:'Noto Sans JP',-apple-system,BlinkMacSystemFont,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;
}
```

## 4. 使い方の約束

- **黄色は1点集中**。塗り面を広げない（型番バナー・キーライン・CTA・`is-active` 等に細く）。
- **高コントラスト厳守**: ほぼ黒（`#2A2D2F`）文字 on 白。「グレー地にグレー文字」は不可
  （ブロシュア方針 §2 と同一原則）。
- ダーク面とライト面の**2面構成**を基本にし、両面ともアクセントは `#FFD400` の1系統で統一。
- 製品カタログ／ブロシュアの**シリーズ差し色**（C `#00BEC7`／E `#FFE12B`／M `#71C79C`／Pico `#F77462`／
  PRO `#515152`、明色は `--accent`＋`--accent-ink` の2分割）は上書きレイヤー。正本は
  [`..\index\_brochure_poc\README.md`](../index/_brochure_poc/README.md) §2/§9。

## 5. 配布ファイル `zotac-tokens.css`（他プロジェクトで使うとき）

**値の配布は同ディレクトリの [`zotac-tokens.css`](zotac-tokens.css) で行う**（Version 1.0.0 / 2026-08-09）。
§3 のコピペ用 `:root` は参照用として残すが、**プロジェクトへ持ち出すときは必ず CSS ファイルごと
コピー（vendoring）**し、手写しをしない（手写しは値がドリフトする — 2026-08 に EdgeTech 文書群で
`--bg-soft` の写し間違いが実際に発生）。

- ルール: コピーは**編集禁止**。プロジェクト側CSSに色・フォント・角丸の生値を書かず `var()` で参照。
- ズレ確認: `diff <コピー> ~/Developer/hub/_partials/zotac-tokens.css`（ヘッダに正本パスとVersionを記載済み
  ＝コピーだけを見ても出自と版が辿れる）。
- 値の変更は正本→Version更新→各コピー上書き、の順。
- v1.0.0 は §3 に対し次を追加収録: `--yellow-hover`・ダーク面トークン一式・状態色（`--ok/--warn/--bad`・
  LLMデモ由来、白地の本文テキストに使う場合はコントラスト確認）・`--radius`・`--shadow`・
  フォントフォールバックに `'Hiragino Kaku Gothic ProN'`。
- 既知のコピー: `~/Developer/edgetech-localai-demo/web/css/zotac-tokens.css`
  （※LLMデモ本体の `style.css` は展示凍結のため既存の `:root` 直書きのまま。機械照合の結果 `--dark-panel` のみ独自値 `#232527`（エンジンルーム用の意図的な深め設定・凍結のため維持）、他は v1.0.0 と一致）
