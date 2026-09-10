# 全件Snapshotの初回投入

## 入力とモード

現在のモードは `initial-load` のみ。Snapshotに含まれる全レコードについて、`dataset:record_key` をローカルItemの「レジストリレコードキー」で照合する。

|状況|initial-loadの動作|
|---|---|
|同じキーがない|新しいItemを作成し、読み戻して確認|
|同じキーが1件で内容が一致|既存Itemを記録。書き込まない|
|同じキーが複数件|投入開始前に停止|
|同じキーがあるが内容が異なる|conflictとして記録し停止。既存値を上書きしない|
|今回の入力にない既存Item|変更しない|
|書込みの結果が不明|uncertainとして停止。無条件で再送しない|

名称や医療機関コードをキーの代わりに推測しない。別方式で作られたItemを継承する場合は、先にレコードキーの対応を確認する。datasetにコロンは使用できない。

入力はbundle schema 0.1。`schema_version`、`dataset`、`entities`、`validation_status: "complete"` が必要。空Snapshot、不完全Snapshot、重複キー、型不整合、未対応Property、確認されていないQIDはジョブ確定前に拒否する。完全性フラグはproducerの検証結果を引き継ぐ契約であり、実際の全国網羅性を投入側だけで証明するものではない。

Property値はstring / external-id / url / monolingualtextに対応。item型を含む実投入は、外部ItemからローカルItemへの対応管理を実装するまで拒否する。出典・限定子も明示的にProperty変換する。

## 1. Property準備

Wikidataから取得し確認したEntity JSONを、PIDをキーにした `definitions.json` にまとめる。例：`{"P13179": {"id":"P13179","type":"property","datatype":"external-id","labels":{...},"descriptions":{...}}}`。外部定義の取得時刻・revision・元ファイルは別途保存する。

認証情報は環境変数 `WIKIBASE_USER` / `WIKIBASE_PASSWORD` に、実行環境の秘密情報管理から設定する。ソースコード・registry・ジョブに埋め込まない。

```sh
wikibase-registry-sync bulk bootstrap definitions.json \
  --registry state/registry.json \
  --api http://127.0.0.1:8180/api.php --wikiid japan_wikibase
```

このコマンドはPropertyを書き込む。既存の対応PIDがあれば再利用する。既存の `state/local-test/registry.json` も使用できる。ローカルP番号は環境ごとに異なる。

現実装は明示的なAction API URLを使う。Custom Wikibaseのruntime discovery自動接続は未実装。remoteはHTTPS必須、証明書検証を無効にせず、リダイレクトを拒否する。wikiidとserverを照合し、ジョブにはendpoint・wikiid・concept URIを固定する。DBを作り直した場合は同じURLでも新しいジョブとregistryを用意する。

## 2. 全件検査・ジョブ生成

```sh
wikibase-registry-sync bulk prepare bundle.json \
  --registry state/registry.json \
  --job state/jobs/initial.sqlite --mode initial-load
```

入力JSONを逐次処理し、変換済み文をSQLiteに格納する。元ファイル全体をメモリ展開しない。全件検査が成功した場合だけジョブファイルを確定する。入力SHA-256を保存し、準備の前後で変化がないことを確認する。以後はジョブ内の確定済み内容を使用する。既存ジョブの上書きは拒否する。

入力bundleと原ファイル・provenance manifestはジョブとは別に保存する。ジョブ内のSHA-256で入力を追跡する。今回の全国bundleは約290 MiB、生成ジョブは約894 MiBだった。作業用一時ファイルとバックアップを含むディスク空間を確保する。

## 3. 投入と途中再開

```sh
# 全件を処理する（件数上限なし）
wikibase-registry-sync bulk run --job state/jobs/initial.sqlite

# 小さい単位で区切る場合。次回も同じジョブを指定する
wikibase-registry-sync bulk run --job state/jobs/initial.sqlite --max-records 1000
wikibase-registry-sync bulk status --job state/jobs/initial.sqlite
```

run開始時に対象Propertyの型・対応PIDを再確認する。Item一覧はページ単位で列挙し、50件ずつ取得してキー索引をSQLiteに作る。各レコードについて全Itemを検索し直す処理にはしていない。新規Itemは1件のAction API書込みに文と出典をまとめ、1件ずつ読み戻す。100件ごとに進捗を標準エラーへ出し、最後の結果を標準出力へ出す。

`--interval` はAPI呼び出し間隔（秒）、既定0.25。書込みにはmaxlag=5を指定する。性能試験に基づく自動調整は未実装。並列書込みを増やす方式は採用していない。

各レコードを `pending → inflight → done` と保存する。途中で終了してもdoneは再投入しない。書込み直前にinflightを確定し、成功応答と読み戻し後にdoneにする。クラッシュ時にinflightが残ると次回はuncertainとして扱う。

同じジョブの二重起動と、**同じジョブディレクトリ**にある同じtarget/datasetの二重実行をファイルロックで拒否する。POSIX環境（macOS/Linux）対象。同一target/datasetのwriterは一つにし、別ディレクトリ・別ホスト・人手から同じキーのItemを並行作成しない。標準APIに一意キー付きcreateがないため、分散環境のexactly-onceを保証する仕組みではない。SQLite・ロックの動作を保証できるローカルディスクにジョブを配置し、同期フォルダの別端末から同時に開かない。

`complete: true` はジョブの全レコードが処理済みであること。後日の手修正・削除まで保証するフラグではない。現在状態はverifyで確認する。

## 4. 再照合・報告

```sh
wikibase-registry-sync bulk verify --job state/jobs/initial.sqlite
wikibase-registry-sync bulk export --job state/jobs/initial.sqlite \
  --output artifacts/initial-report.csv
```

verifyはサーバーを書き換えず、全件のキー・ラベル・対象文・出典・限定子を読み戻して検査する。検査結果はジョブに保存する。CSVにキー、ローカルID、revision、状態、作成／既存／応答不明からの回復、差異を出す。verify未実行のCSVではverification_errorが空でも検証済みとは限らない。statusのlast_verificationで実行有無・件数を確認する。

sourceで扱うPropertyの追加値・変更値も差異として扱う。無関係な人手のPropertyは残す。既存の確認済みWikidata QIDは、今回の入力にQIDがないことを理由に削除しない。新しいQIDはbundleの同じQIDに対する `match_decision.status=confirmed` を必要とする。

## 要確認で停止した場合

- `conflict`：exportでラベル・Property単位の差異を確認する。正当な元データ更新なら、初回投入で強制上書きせず、今後のupsertへ回す。
- `uncertain`：同じrunを再開すると、索引上に同じキーと内容が見つかった場合だけreconciledとして回復する。見つからなくても再送しない。処理継続中・結果の可視化遅延の可能性があるため、サーバーで処理が終わり未作成であることを運用者が確認する。

確認後、未作成の1件だけを解除する場合：

```sh
wikibase-registry-sync bulk retry-uncertain --job state/jobs/initial.sqlite \
  --key 'dataset:record-key' --confirmed-not-created
wikibase-registry-sync bulk run --job state/jobs/initial.sqlite
```

通信・APIの失敗は自動再送せず保守的に止める。認証切れやmaxlagも運用者が原因を解消して再開する。runは要確認時、verifyは差異検出時に終了コード2を返す。`--max-records` による正常な途中終了は0だが `complete:false` となる。

## 月次更新への拡張方針

|モード|今後の意図|今回の実装|
|---|---|---|
|initial-load|全件の存在確認と新規登録|実装・検証済み|
|upsert|既存レコードの管理対象文を更新、なければ新規登録|未実装|
|replace-snapshot|新Snapshotを別世代に投入・検証して公開対象を切替|未実装の設計案|

医療機関では、安定したレコードキーとローカルItemを維持するupsertを基本とし、入力に存在しないだけで廃止と判断しない。廃止・辞退・取消等の公式変更情報を利用する。所有する文、空欄の意味、発効日、Change Eventを決めてから更新を実装する。

全件入れ替えでは、全Itemを先に削除する方式を取らず、公開中世代を維持したまま新世代を検証する案とする。公開切替・ローカルID維持・旧世代の保持方法は、Custom Wikibaseのオーケストレーション側と合わせて決める。現CLIは未実装モードを受け付けない。

取得・変換はproducer、ジョブ・API・再開・結果出力は本リポジトリという境界を維持する。今回の実装から、Custom Wikibaseに追加する価値があるのは「dataset/keyの一意制約付き作成」「idempotency key」「結果照会可能な非同期ジョブ」「公開世代切替」の入口と整理できる。現段階ではCustom Wikibaseの改修を必要とせず、標準Action APIで動作する。

実装に使用した逐次JSONパーサーは [ijson公式資料](https://github.com/ICRAR/ijson)。runtime側のAPI契約は [Custom Wikibase runtime contract](https://github.com/hirokiu/custom-wikibase/blob/main/docs/japan-wikibase/runtime-contract.md) を参照。
