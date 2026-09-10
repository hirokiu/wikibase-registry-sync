# ローカル投入検証（2026-09-10）

稼働中の `wfp-jwb-m1-wikibase-1`、http://127.0.0.1:8180 を使用した。
MediaWiki 1.43.9、wikiid `japan_wikibase` の既存開発用coreであり、最新Custom Wikibase製品runtimeとの互換試験ではない。コンテナの変更・再起動はしていない。

## Wikidataとの対応

ローカルProperty自身の文として、P32（WikidataプロパティID）とP34（WikidataエンティティURL）を保存する。番号はこのインスタンスでの割当であり、他環境では自動採番と対応表を使用する。ラベルだけで既存業務Propertyを流用しない。

|用途|Wikidata|今回のローカルProperty|
|---|---|---|
|10桁保険機関コード|P13179|P36|
|正式名称|P1448|P37|
|郵便番号|P281|P38|
|住所|P6375|P39|
|電話番号|P1329|P40|
|出典URL|P854|P41|

医療機関ItemにはP33（Wikidata項目ID）、P34（リンク）、P35（datasetを含むレコードキー）を使用する。P32〜P35はローカル管理用の定義であり、対応のないWikidata PIDを捏造しない。外部QIDをローカルItem参照として扱わない。

## 結果

|医療機関|10桁コード|ローカル|Wikidata|
|---|---|---|---|
|愛全病院|0110112489|Q8|未照合・付与なし|
|JR札幌病院|0110114386|Q9|Q11226237|
|聖路加国際病院|1310270751|Q10|Q7589810|

確認済み2件は、事前選定したWikidata候補についてコードと正規化名称が一致し、存在する郵便番号・電話番号に矛盾がないことを確認した。Wikidata定義と候補は同日取得済みのPhase 1証跡を使用（今回の再取得はHTTP 403）。候補全体の網羅検索ではなく、名称のみの自動統合はしない。未照合は「Wikidataに存在しない」という意味ではない。

初回13件作成（Property 10、Item 3）、再実行0更新。既存34エンティティのrevisionに変更なし。6つのPID対応、3つのコード、2つのQIDリンク、原データへの出典をAPIで確認。Q10とP36のブラウザー表示を確認した。SPARQLは未検証。

## 実行

認証情報を `WIKIBASE_USER` / `WIKIBASE_PASSWORD` 環境変数で渡す。ログ・state・Gitに認証情報を保存しない。

```sh
python -m wikibase_registry_sync.local_cli bundle.json definitions.json \
  --state state/local/registry.json \
  --api http://127.0.0.1:8180/api.php --wikiid japan_wikibase
```

`definitions.json` はWikidata PIDをキーとしたEntity JSON辞書（datatype、labels、descriptionsを含む）。bundleはproducerの共通形式。QIDを付けるには同じQIDについて `match_decision.status=confirmed` が必要。この判定の根拠をレビュー済み入力として扱い、投入側が医療機関名寄せを行うことはない。

今回のbundle、定義、判定根拠、対応表、検証結果はローカルの `state/local-test/` に保存した。機械ごとのstateはGit管理しない。

## 範囲

現段階はloopback限定・1回10件までの追加型検証用writer。Action APIと明示的なwikiid照合、CSRF認証、revision競合検出を使用。リダイレクトを拒否し、不確かな書込みは自動再送しない。既存文の削除・置換、変更イベント、複数ホストからの同時投入、大量投入、item型の外部ID変換は未対応。

全国データを月次更新する本番同期処理では、所有する文の識別と更新・廃止方針、変更イベント、ジョブ再開、負荷制御を追加する必要がある。既存Wikibase Suiteの実機確認およびCustom Wikibase最新runtimeのAPI互換検証は別途必要。
