# 公示由来の機種カタログ

毎週月曜日12:23（日本時間）、福井・静岡・山形県公安委員会の公示一覧から掲載中の検定PDFを発見し、型式名・製造業者・種別・検定番号・公示日（静岡県は検定日）を抽出します。

取得元：https://www.pref.fukui.lg.jp/kenkei/doc/kenkei/yuugikikenteikouji.html

静岡県：https://www.pref.shizuoka.jp/police/shinse/seikatsu/fueiho/yugiki.html

山形県：https://www.pref.yamagata.jp/800028/kensei/police/procedures/kentei-yuugi.html

公式告示本文の情報と、島図エディターが独自に補う商品名・略称を分けて管理します。公式本文は著作権法13条を根拠に利用し、独自補足はCC0-1.0で提供します。画像・ロゴ・他社の機種データベースは取り込みません。

これは検定公示の型式候補であり、発売済み・現行設置・全国全機種の一覧ではありません。2021年以降の山形県の過去公示と、2023年度以降の静岡県の累積一覧も対象です。同じ製造業者・型式は県をまたいで重複排除します。公示日・検定日は導入日とは異なります。申請者の住所や代表者氏名は取り込みません。

## 自動更新

`python scripts/build_notice_catalog.py` で `docs/machines.json` を生成します。依存関係は `scripts/machine-catalog-requirements.txt` を使用します。

- 公示一覧にある公式ホストの検定PDFだけを取得します。
- robots.txtを確認し、PDF取得の間隔を空けます。
- PDF内容のSHA-256を保存し、変更されていないPDFの解析結果はキャッシュします。
- 行番号の連続性・表の列・種別・検定番号・日付を検証します。
- 原文の型式名と出典PDF・ページを残します。
- 空の結果や解析エラーでは公開ファイルを書き換えません。
- アーカイブ入れ替え時にも、過去に取得した型式を保持します。
- 公示の種別とL/S/P/e接頭辞が矛盾した場合、絞り込みは接頭辞を使用し、原文の種別と判定根拠も保持します。

## 商品名・略称の追加

`data/machine-name-overrides.json` に独自補足を追加します。製造業者と型式名の完全一致で適用し、記号を機械的に削って別スペックを混同しないようにします。

`name` は表示・選択に使う名前、`reading` は読み、`aliases` は検索用の略称です。元の `modelName` は変更しません。補足がない型式も原文由来の名前で自動掲載されます。

検証：`python -m unittest discover -s scripts -p 'test_notice_catalog.py'`

## メーカー商品名の自動照合

公示生成後に `python scripts/match_manufacturer_names.py` を毎週実行します。現在の対応先は北電子と山佐系（山佐・山佐ネクスト・セブンリーグ）です。他メーカーの自動照合は未対応です。

- 北電子：公式の[製品一覧](https://www.kitadenshi.co.jp/slot/)と[検定一覧](https://www.kitadenshi.co.jp/slot-kentei/?expired=1)を製品ページの識別子で結び、公示の製造業者・型式名を完全一致で照合します。
- 山佐系：公式の[機種一覧](https://yamasa-next.co.jp/slots)をページ送りも含めて取得します。メーカー、商品名の主要部分、シリーズ番号が一致し、残りが検定コードの形式に収まる候補が一つの場合に照合します。ローマ数字の表記差を正規化します。BTの商品表記はLB型式だけで対応づけます。
- 別のシリーズ番号や30φの違いを末尾コードとして削りません。複数候補・未発表・未対応は変更せず保留します。山佐系の方式は公式の型式対照表ではなく、名称の整合条件による自動照合です。
- 商品名は公式ページの文字を使い、ロゴ・画像・説明文は取得しません。外部の製品サイトは巡回せず、必要な場合は公式一覧ページを出典にします。
- 照合後も元の型式、機種ID、読み・略称を保持します。表示名はメーカー情報を優先し、型式名でも検索できます。
- 照合した出典・方法・取得日時は各機種の `manufacturerMatch` に保存します。
- 取得失敗・構造変更時は `data/manufacturer-products.json` の前回取得分を使い、`stale` を付けます。新しく確認できたとは扱いません。
- `docs/machine-name-match-report.json` に対応数、取得元の状態、保留理由を出力します。候補を推測だけで確定する処理や外部AIサービスへの送信はありません。

検証：`python -m unittest discover -s scripts -p 'test_*.py'`
