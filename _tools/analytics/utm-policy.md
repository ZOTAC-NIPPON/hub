# utm-policy.md — UTM パラメータ規約（正本）

最終更新: 2026-08-14

> **正本マップ = `②' 00_hub_zotac\HUB.md`**（OneDrive 側）。
> 本ファイルは hub.zotac.co.jp へ向かう**外部リンクに付ける UTM の唯一の正本**。
> 値の登録簿は [`utm-taxonomy.json`](utm-taxonomy.json) と [`campaigns.json`](campaigns.json)、
> 検査は [`_tools/check-utm.py`](../check-utm.py)。**規約・登録簿・検査の3点セットで1組**なので、
> どれか1つだけ直さないこと。

---

## 0. なぜこの規約があるか（2026-08 の実測）

2026-07-15〜08-13 の GA4 で、**セッションの 23%（162/711）が Unassigned**（チャネル判定不能）
だった。原因は X 投稿に付けていた UTM の値である。

```
utm_source=x           ← Google のソースカテゴリ一覧に "x" も "x.com" も無い
utm_medium=article     ← GA4 のどのチャネル定義にも一致しない
```

GA4 が Organic Social と判定する条件は次の **OR** で、現行値は両方を外していた。

```
ソースが GA4 のソーシャルサイト一覧に一致
  OR
メディアが ^(social|social-network|social-media|sm|social network|social media)$ に一致
```

Google 公式「GA4 Source Categories」一覧（819 エントリ）を 2026-08-14 に照合した結果:

| ソース名 | 掲載 | カテゴリ |
|---|---|---|
| `twitter` | あり | SOURCE_CATEGORY_SOCIAL |
| `twitter.com` | あり | SOURCE_CATEGORY_SOCIAL |
| `t.co` | あり | SOURCE_CATEGORY_SOCIAL |
| `x` | **なし** | — |
| `x.com` | **なし** | — |

つまり **UTM を丁寧に付けた投稿ほど Unassigned に落ち、UTM を付けていない X 流入は
`t.co` のリファラ経由で正しく Organic Social に入る**という逆転が起きていた。
PC Watch 掲載で流入が跳ねた月に、その効果検証ができない状態だったということ。

**この事故は「値を1つ間違えた」だけで起きる。**だから閉じたリスト＋検査で縛る。

---

## 1. ハードルール

1. **`utm_medium` は §2 の閉じたリストからしか選ばない。**
   medium は「チャネルの種類」であって、クリエイティブの形式ではない。
2. **内部リンク（ハブのページからハブのページ）に UTM を付けない。**
   セッションが途中で分断され、本来の流入元が失われる。
3. **`utm_source` / `utm_medium` / `utm_campaign` は必須。**1つでも欠けると判定が崩れる。
4. **`utm_campaign` は [`campaigns.json`](campaigns.json) に登録済みのものだけ。**
   未登録の値は検査で落ちる。キャンペーン開始時にまず登録する。
5. **小文字 ASCII のみ。**単語区切りは `_`。全角・空白・大文字は禁止。
6. **X のソースは `x` ではなく `twitter`。**（§0 の理由）
7. **個人情報・メールアドレス・問い合わせ内容を UTM に入れない。**
   UTM は URL に露出し、リファラとして外部に渡り、GA4 に平文で保存される。

---

## 2. `utm_medium` の閉じたリスト

**この7つ以外は使用禁止。**GA4 デフォルトチャネルグループでの落ち先を併記する。

| 値 | 使う場面 | GA4 のチャネル |
|---|---|---|
| `social` | 自社 X などの無償 SNS 投稿 | Organic Social |
| `email` | メールマガジン・案内メール | Email |
| `referral` | UTM を付けてもらえるメディア・パートナー | Referral |
| `link` | PDF 内リンク／QR コード／紙資料 | Referral |
| `paid_social` | X・Facebook 等の有料 SNS 広告 | Paid Social |
| `cpc` | 検索広告 | Paid Search |
| `display` | ディスプレイ・バナー広告 | Display |

**medium に置いてはいけない語**（すべて過去に候補として出たもの）:

```
article  thread  summary  newsletter  qr  pdf  print  offline  post  tweet
```

`article` / `thread` / `summary` はクリエイティブ形式なので **`utm_content` に移す**。

> ⚠ **GA4 には「Offline」チャネルが存在しない。**展示会 QR のようなオフライン起点は
> `utm_medium=link`（＝Referral に落ちる）とし、`utm_source` に `offline_` 接頭辞を付ける。
> 社内分析ではカスタムチャネルグループで `offline_` を「Offline」に再分類する（§6）。

---

## 3. 各パラメータの命名規則

### `utm_source` — 媒体・送信主体・物理的な起点

[`utm-taxonomy.json`](utm-taxonomy.json) の `sources` に登録済みの値のみ。新しい媒体を使うときは
**先に登録する**（登録＝「この source で GA4 のチャネル判定がどうなるか確認した」という宣言）。

```
twitter              自社 X（x や x.com は不可）
zotac_newsletter     メールマガジン
pc_watch             PC Watch（先方が UTM を受け入れた場合のみ）
owned_pdf            自社 PDF 資料内のリンク
```

### `utm_campaign` — `yyyymm_campaign_name`

開始年月6桁 ＋ `_` ＋ 施策名。**同じ施策なら X・メール・QR で同じ値を使う**
（媒体の違いは `utm_source` が持つ。campaign を媒体ごとに分けると横断集計ができない）。

```
202607_power_limit
```

### `utm_content` — `形式_対象_掲出位置` / バリアント

同じキャンペーン内でクリエイティブを識別する。**A/B や出し分けの評価はここで行う。**

```
article_5090      X の記事形式・RTX 5090 向け
thread_day1       X のスレッド・初日
summary_day7      X のまとめ投稿・7日目
mail_header       メールのヘッダーリンク
qr_panel_a        ブースパネル A の QR
report_v1_p12     PDF レポート v1 の 12 ページ目
```

### `utm_term` — 有料検索のキーワード専用

それ以外では**付けない**。Google 広告では原則として自動タグ設定（`gclid`）を優先する。

---

## 4. ケース別サンプル

```
自社 X
  ?utm_source=twitter&utm_medium=social&utm_campaign=202607_power_limit&utm_content=thread_day1

メールマガジン
  ?utm_source=zotac_newsletter&utm_medium=email&utm_campaign=202607_power_limit&utm_content=mail_header

UTM を依頼できるメディア掲載
  ?utm_source=pc_watch&utm_medium=referral&utm_campaign=202607_power_limit&utm_content=article_body

展示会 QR（source は掲出ごとに offline_<場所> を先に登録する）
  ?utm_source=offline_<場所>&utm_medium=link&utm_campaign=<yyyymm_name>&utm_content=qr_panel_a

PDF 資料内リンク
  ?utm_source=owned_pdf&utm_medium=link&utm_campaign=202607_power_limit&utm_content=report_v1_p12
```

### UTM を依頼できないメディア掲載（PC Watch 等）

**何も付けず、自然な Referral として計測する。**後から `utm_campaign` を復元することは
できないので、評価は次の組み合わせで行う。

- セッションの参照元（`pc.watch.impress.co.jp / referral`）
- ランディングページ
- 掲載日（**GA4 のアノテーションに掲載日を必ず残す**。これを忘れると後から追えない）

---

## 5. hub → 問い合わせフォーム（別ドメイン）のパラメータ

**現状、hub 側の生成器は `utm_*` を CTA に一切付与していない**（2026-08-14 に
`inject.py` / `build_pages.py` / `_gpu_gen.py` / `build_enterprise.py` の4本を確認）。
付くのは `sku` / `pname` / `series` / `line` / `intent` / `from` のみで、フォーム側
WPForms の `utm_*` hidden は実運用では常に空。規約は ②' の `_forms\README.md` §3 が正本。

将来「訪問者の流入時 UTM をフォームまで引き継ぐ」を実装する場合、
**パラメータ名は `utm_*` ではなく `lead_source` / `lead_medium` / `lead_campaign` /
`lead_content` にすること。**フォーム側ドメインの GA4 は URL 上の `utm_*` を
イベントスコープの流入情報として拾うため、社内導線の情報を `utm_*` に入れると
フォーム側のアトリビューションを汚す。

---

## 6. 過去データの救済（GA4 カスタムチャネルグループ）

2026-07〜08 に発生済みの Unassigned は、GA4 のカスタムチャネルグループで後から拾える
（**カスタムチャネルグループのディメンションは過去データにも遡及適用される**）。

```
チャネル名: Organic Social - Legacy X (v1)

  Source     完全一致     : x
  AND Medium 正規表現一致 : ^(article|thread|summary)$
  AND Campaign 完全一致   : powerlimit2026
```

**`utm_campaign` まで条件に入れるのが要点。**こうしておくと、将来また同じ誤った medium が
使われたときに自動で救済されず、規約違反として検知できる。

注意点:

- デフォルトチャネルグループ側の Unassigned は**変わらない**（公式基準は従来どおり）。
- カスタムグループを「メイン」に切り替えた場合、メインとしての記録は切替後のデータから。
- オーディエンスには遡及しない。BigQuery Export にも出力されない。
- 「Organic Social が増えた」のが実流入増かルール変更か分からなくならないよう、
  **グループ名に `v1` を付け、作成日とルールを本ファイルに追記する**。

---

## 7. 逸脱を防ぐ仕組み

| 手段 | 内容 |
|---|---|
| 検査 | `python3 _tools/check-utm.py` — `hub.py check` / `publish` の検査群に組み込み済み |
| 自己テスト | `python3 _tools/test_guards.py` — 検査器が退化していないかを CI で確認 |
| 登録簿 | 未登録の source / campaign、閉じたリスト外の medium はすべて検査で落ちる |
| 手順 | キャンペーン開始時に `campaigns.json` へ登録 → §4 の形で URL を作る → 投稿前に `--both` で検査 |

**X の投稿文に URL を手入力しない。**必ず本ファイルの形をコピーし、投稿前に
`python3 _tools/check-utm.py --both` を通す。

---

## 8. 変更履歴

| 日付 | 変更 |
|---|---|
| 2026-08-14 | 新規作成。`utm_source=x` / `utm_medium=article` による Unassigned 23% を受けて規約化 |
