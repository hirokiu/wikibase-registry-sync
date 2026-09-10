# 全件投入フロー検証（2026-09-10）

## 全国データの準備

- 入力：jp-medical-registryの全国検証済みSnapshot bundle（schema 0.1、validation_status=complete）
- 224,517件を全件検査し、投入用SQLiteジョブを確定
- 入力SHA-256：`4041c23574dfc7324c40b0d9a417d5bf8d22ab3845f4354235ee202964a5943f`
- 全レコードpending。**全国全件の実投入は行っていない。**
- 準備時の逐次JSON読込み、SQLite一意キー検査、型・Property mapping・QID判定契約を通過
- 未処理取得に部分索引records_remainingが使用されることを確認。完了済みの先頭から毎回全件を走査する実装にはしていない

## ローカル実機

対象：既存 `http://127.0.0.1:8180/api.php`、wikiid `japan_wikibase`、MediaWiki 1.43.9。前回確認済みの開発用coreを使用。コンテナ・Custom Wikibaseコードは変更していない。

全国bundleから先頭20件と前回の3件を選び、重複を除いた21件を使用した。今回の入力にはQIDがないが、前回付与済みの2件のリンクを維持できることも確認した。

|検証|結果|
|---|---|
|最大7件で処理を区切る|done 7 / pending 14、新規6・既存1|
|同じジョブを再開|done 21、新規累計18・既存3|
|verifyで読み戻し|21件、差異0|
|同じ入力から別ジョブを作り再実行|既存21、新規0|
|投入前に存在したItem/Property|47件すべてrevision不変|
|新規Item|Q11〜Q28|
|出力|レコードごとの処理結果CSV|

実機試験の呼び出し間隔は0.1秒。全件処理時の性能・負荷はまだ測定しておらず、21件の試験から全国の所要時間を保証しない。

## 自動テスト

27テストを通過。主要ケース：

- 1,001件の途中再開・二重実行・全件verify
- 1,203件のAPI一覧取得（複数ページ、最大50件ずつ）
- 作成成功後の応答消失を再照合し、再作成しない
- 未作成に見える結果不明レコードを自動再送しない
- inflight状態でのプロセス終了から回復
- 入力末尾の不正、キー重複、不完全・空Snapshot、未確認QIDを拒否
- 対象wiki・Property mappingの不一致を拒否
- 既存キー重複を新規書込み前に拒否
- 既存値の不一致を上書きせず、人手追加Propertyを維持
- 入力QID空欄時に既存の確認済みQIDを保持
- 手修正による差異をverifyで検出
- 未実装のupsert / replaceモードを拒否

## ローカル成果物

このリポジトリ内のGit除外ディレクトリ `state/bulk-20260910/`：

- `national.sqlite`：全国224,517件の準備済みジョブ
- `smoke.json` / `smoke.sqlite`：21件の入力と処理済みジョブ
- `partial.json` / `resumed.json` / `verified.json`：実機確認結果
- `replay.sqlite` / `replay.json`：別ジョブでの全件既存判定
- `smoke-report.csv`：Item ID・revision・処理結果
- `baseline.json`：既存エンティティの投入前revision

資格情報はこれらに保存していない。運用時は同じtarget/datasetのwriterを一つにし、ジョブファイルを別ホストと同時共有しない。
