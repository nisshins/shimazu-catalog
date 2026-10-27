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
