# utm-policy.md — UTM パラメータ規約（正本）

最終更新: 2026-08-15（v2）

> **正本マップ = `②' 00_hub_zotac\HUB.md`**（OneDrive 側）。
> 本ファイルは hub.zotac.co.jp へ向かう**外部リンクに付ける UTM の唯一の正本**。
> 値の登録簿は [`utm-taxonomy.json`](utm-taxonomy.json) と [`campaigns.json`](campaigns.json)、
> 検査は [`_tools/check-utm.py`](../check-utm.py)。**規約・登録簿・検査の3点セットで1組**なので、
> どれか1つだけ直さないこと。

---

## 0. 一番大事なルール — 迷ったら付けない

**UTM は「付けるほど正確になる」ものではない。**むしろ逆で、付け方を間違えると
referrer による正しい判定を上書きして壊す。実際 2026-08 に、**丁寧に UTM を付けた流入ほど
Unassigned（チャネル判定不能）に落ちる**という逆転が起きていた。

この規約は**一人で運用される**。だから守るべき対象を増やさないことが最優先で、
規約の価値の半分は「付けなくていい場面を明示すること」にある。

---

## 1. まず層を判定する（§2 の型より先に、これ）

```
そのリンクは、普通の Web ページの中にある <a> か？
├─ はい → referrer が届く    → 【層A】UTM を付けない
└─ いいえ（QR・PDF・メール・アプリ内） → referrer が落ちる
    ├─ 版や実施回を区別したい  → 【層B】3点セット・campaign は dated
    └─ 差し替え不能で終わりもない → 【層C】3点セット・campaign は stable
```

| 層 | UTM | campaign | 例 |
|---|---|---|---|
| **A** | **付けない** | — | 本家 zotac.com / zotac.co.jp の製品ページ、メディア記事、他社サイト |
| **B** | 3点必須 | `dated`（`yyyymm_name`） | 夏企画、展示会、**改訂版カタログPDF** |
| **C** | 3点必須 | `stable`（日付なし） | 製品同梱物のQR、メール署名 |

### 層A を「付けない」にする理由

`zotac.com` は自社ドメインだが、hub とは別の GA4 プロパティで測っている。UTM を付けなければ
`zotac.com / referral` として自動的に Referral に入る。**付けたせいで壊れていた**のが
2026-08 の 14 セッションだった。

決定的なのは、**hub の CI は本家サイトを検査できない**こと。あちらに規約を敷いても違反を
検知する手段が永久に無いので、「付けない」と決めておくのが唯一の再発防止になる。
`utm-taxonomy.json` の `no_utm_hosts` に対象ドメインを列挙してある。

掲出位置（製品ページ／フッター／バナー）を区別したくなった時点で初めて層B へ上げる。
現状は着地ページがすべて製品固有なので、区別する必要が無い。

### 部分UTM は最悪

`source` と `medium` だけ付けて `campaign` を省くと、**referrer を上書きしたうえで
campaign が `(not set)` になり、タグ欠落による `(not set)` と区別できなくなる**。
付けるなら3点、付けないなら0点。中間は禁止。

---

## 2. 型

区切りは**半角パイプ・前後スペース** ` | `（タイトル規約と共通）。

```
?utm_source={登録済みの source}
&utm_medium={§3 の閉じたリスト}
&utm_campaign={campaigns.json に登録済み}
&utm_content={掲出面・クリエイティブ。任意だが実質必須}
```

### ケース別（現に運用しているもの）

```
自社 X
  ?utm_source=twitter&utm_medium=social&utm_campaign=202607_power_limit&utm_content=article_5090

カタログPDF の QR
  ?utm_source=catalog&utm_medium=link&utm_campaign=202605_b2b_catalog&utm_content=qr_cover

メールマガジン
  ?utm_source=zotac_newsletter&utm_medium=email&utm_campaign=<campaign>&utm_content=mail_header

本家 zotac.com / zotac.co.jp からのリンク
  （何も付けない）
```

---

## 3. `utm_medium` の閉じたリスト

**この7つ以外は使用禁止。**

| 値 | 使う場面 | GA4 のチャネル |
|---|---|---|
| `social` | 自社 X などの無償 SNS 投稿 | Organic Social |
| `email` | メールマガジン・案内メール・営業の個別メール | Email |
| `referral` | UTM を付けてもらえるメディア・パートナー | Referral |
| `link` | QR コード／PDF 内リンク／紙資料 | Referral |
| `paid_social` | 有料 SNS 広告 | Paid Social ※ |
| `cpc` | 検索広告 | Paid Search ※ |
| `display` | ディスプレイ・バナー広告 | Display |

> ⚠ **medium とチャネルは1対1ではない**（2026-08-15 に Google 公式定義で確認）。
> `referral` と `link` は**どちらも Referral**。`cpc` と `paid_social` は
> **source 側の条件（検索サイト一覧／ソーシャル一覧）との AND** で決まるので、
> 未知の source と組むと Paid Other 等に落ちる。

**medium に置いてはいけない語**（すべて実際に候補として出たもの）:

```
article  thread  summary  post  tweet  product_page
newsletter  qr  pdf  print  offline  webinar  partner  signage  business_card
```

共通するのは「**チャネルの種類ではないものを medium に書いた**」こと。クリエイティブ形式・
掲出形態・関係性・施策の種類は、それぞれ `utm_content` / `utm_source` / `utm_campaign` へ置く。

**足りなくなったら足す（先回りしない）。** 将来の候補は `video`（Organic Video）、
`affiliate`（成果報酬型の提携のみ）、`paid_other`（記事広告等）。使う時点で登録する。

---

## 4. `utm_campaign` の命名 — `naming_mode` で分岐

**`yyyymm` は「登録した月」ではなく「施策の開始月／版の発行月」**（`effective_month` フィールドが
その意味を明示する）。ここを取り違えると、同じ導線を直すたびに `202608_` `202609_` と増えて
分裂する。

| naming_mode | 命名 | 対象 | 例 |
|---|---|---|---|
| `dated` | `yyyymm_name` | 実施回・版を区別するもの | `202607_power_limit` / `202605_b2b_catalog` |
| `stable` | `name`（日付なし） | 差し替え不能で終わりも版もないもの | （現在なし） |

**カタログPDF は `stable` ではなく `dated`。**年数回改訂される版物なので、束ねると5月版と
12月版を比較できない。版をまたいで見たいときは `family` で寄せる。

`stable` は**逃げ先になりやすい**ので入場条件を厳しくする ―― referrer が使えない **かつ**
終了日も版もない **かつ** 既存の dated に寄せられない。展示会・季節企画・カタログは、
たとえ「これから何年も使う」でも `dated`。

---

## 5. 登録簿に持つもの（一人運用向けに削ってある）

`campaigns.json` の各エントリ:

| フィールド | 必須 | 意味 |
|---|---|---|
| `naming_mode` | ✅ | `dated` / `stable` |
| `effective_month` | dated のみ | 施策の開始月／版の発行月。接頭辞と一致すること |
| `allowed_sources` / `allowed_mediums` | ✅ | 不正な組み合わせを防ぐ（値を個別に許可するだけでは防げない） |
| **`placement`** | ✅ | **どこに貼ったか。**半年後の自分が思い出せるように書く |
| **`fixable`** | ✅ | `yes`＝差し替えで訂正できる／`no`＝配布済みで訂正不能 |
| `family` | 任意 | 版をまたいで束ねるグループ名 |

**入れなかったもの**（`owner` / `status` / `last_checked` / `placement_id` / `asset_version`）。
一人運用では `owner` は常に自分で、`last_checked` は定期棚卸しの儀式が前提になり、忙しい月に
必ず途切れて古い日付だけが残る。**埋まらないフィールドを持つ登録簿は、検査を黙らせる逃げ先に
なる。**チームで運用する日が来たら足す。

---

## 6. 検査でできること・できないこと

`_tools/check-utm.py`（`hub.py check` / CI に組み込み済み）が見るのは **hub リポジトリと
②' OneDrive の中だけ**。

**検査できない場所** ―― 本家 zotac.com、別ドメインの問い合わせフォーム、配布済みPDF、
展示会資材、X の投稿済みポスト。ここは**規約と手順でしか守れない**。だから §1 の層A
（付けない）を既定にして、守る対象そのものを減らしてある。

**投稿・掲出の前に必ず通す:**

```bash
python3 _tools/check-utm.py --both
```

---

## 7. 過去データの救済（GA4 カスタムチャネルグループ）

既に GA4 に記録された誤った値は書き換えられない。カスタムチャネルグループで**分析上だけ**
救済する（**過去データにも遡及適用される**）。対象は `utm-taxonomy.json` の `legacy_values`。

```
Organic Social - Legacy X (v1)
  Source 完全一致 x  AND  Medium 正規表現 ^(article|thread|summary)$  AND  Campaign 完全一致 powerlimit2026

Referral - Legacy Owned (v1)
  Source 完全一致 zotac.com  AND  Medium 完全一致 product_page

Referral - Legacy QR (v1)
  Source 完全一致 catalog  AND  Medium 完全一致 qr
```

**campaign やホストまで条件に入れるのが要点。**こうしておくと、将来また同じ誤った値が
使われたときに自動で救済されず、規約違反として検知できる。

注意点:

- デフォルトチャネルグループ側の Unassigned は**変わらない**（公式基準は従来どおり）
- カスタムグループを「メイン」に切り替えた場合、メインとしての記録は切替後のデータから
- オーディエンスには遡及しない。BigQuery Export にも出力されない
- グループ名に `v1` を付け、作成日とルールを本ファイルに追記する

---

## 8. hub → 問い合わせフォーム（別ドメイン）

**本規約は inbound（外部 → hub）専用。**hub からフォームへの outbound は別の話で、現状
hub 側の生成器は `utm_*` を CTA に一切付与していない（2026-08-14 に `inject.py` /
`build_pages.py` / `_gpu_gen.py` / `build_enterprise.py` を確認）。付くのは
`sku` / `pname` / `series` / `line` / `intent` / `from` のみ。規約は ②' の
`_forms\README.md` §3 が正本。

将来「訪問者の流入時 UTM をフォームまで引き継ぐ」を実装する場合、**パラメータ名は `utm_*`
ではなく `lead_source` / `lead_medium` / `lead_campaign` / `lead_content`**。フォーム側
ドメインの GA4 が URL 上の `utm_*` をイベントスコープの流入情報として拾い、アトリビューションを
汚すため。

---

## 9. 未解決

- **`(not set)` 13 セッション**（2026-08 実測）は `session_start` の欠落で、UTM 規約では直らない。
  同意モード・タグ発火順・ブロッカーの調査が要る。Unassigned 170 のうち 13 がこれ
- `zotac.co.jp` から hub へのリンクは 2026-08-15 時点で**まだ無い**。張るときは層A（付けない）

---

## 10. 変更履歴

| 日付 | 変更 |
|---|---|
| 2026-08-14 | 新規作成。`utm_source=x` / `utm_medium=article` による Unassigned 23% を受けて規約化 |
| 2026-08-15 | v2。GA4 実測で想定漏れ2件（本家クロスリンク・カタログQR）が判明したのを受けて全面改訂。①層A/B/C の判定を導入し**既定を「付けない」に変更** ②`yyyymm` 強制をやめ `naming_mode` + `effective_month` へ ③medium とチャネルが1対1という誤った説明を修正（`referral` と `link` は両方 Referral、`cpc`・`paid_social` は source との AND） ④登録簿に `placement` / `fixable` を追加（一人運用で機能する2つに絞り、`owner`・`last_checked` 等は入れない） |
