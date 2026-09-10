# wikibase-registry-sync

Wikibase SuiteとCustom Wikibaseへの汎用バッチ投入ツールです。医療機関固有の取得・正規化・名寄せは [jp-medical-registry](https://github.com/hirokiu/jp-medical-registry) に分離しています。

## 現在の実装（0.2）

**全件Snapshotの初回投入フロー**に対応しました。

1. `bulk bootstrap`：Wikidata Property定義からローカルPropertyと対応PIDを準備
2. `bulk prepare`：全入力の検査とSQLite投入ジョブの生成（サーバー書込みなし）
3. `bulk run`：レコードキーで既存確認、未登録Itemの作成、途中再開
4. `bulk verify`：投入内容の読み戻し検査
5. `bulk export`：処理結果・差異をCSVに出力

既存の内容が一致すれば作成を省略し、不一致は要確認として停止します。現在値の更新・削除はしません。月次の `upsert` とSnapshot入れ替えは、将来の別モードとして設計しています。

全国医療機関224,517件の投入ジョブ生成と、稼働中のローカルCustom Wikibase開発用coreへの21件の投入・再開・再照合を検証しました。全国全件の実投入、最新版Custom Wikibase製品runtimeとSuiteの実機互換検証は未実施です。

## バッチ投入の確認方針

**通常の投入では、存在確認と現在値の差分確認を必須とします。** 新規なら作成、一致なら書込みを省略し、差分があればモードに従って扱います。確認なしの一括作成を標準動作にはしません。

現在の `initial-load` も存在・差分を確認し、既存値の差分は報告して停止します。今後の `upsert` は同じ確認を行ったうえで管理対象の変更点だけを更新する方針です。確認を省略する高速初期投入モードは実装していません。

確認にはAction APIを使います。対象一覧をまとめて取得してキーを索引化し、該当Itemの現在値を読みます。ローカルの投入済み記録だけで一致とは判定しません。同一ジョブの再開では完了分を省略するため、最終確認には `bulk verify` を実行します。詳細は [確認ポリシー](docs/FULL_IMPORT.md#存在確認差分確認のポリシー) を参照してください。

## 導入

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests
```

[全件投入の実行手順・再開・運用上の範囲](docs/FULL_IMPORT.md) に、準備から検証までのコマンドを記載しています。

```sh
wikibase-registry-sync bulk prepare bundle.json \
  --registry state/registry.json --job state/jobs/initial.sqlite
wikibase-registry-sync bulk run --job state/jobs/initial.sqlite
wikibase-registry-sync bulk verify --job state/jobs/initial.sqlite
wikibase-registry-sync bulk export --job state/jobs/initial.sqlite \
  --output artifacts/initial-report.csv
```

認証情報は `WIKIBASE_USER` と `WIKIBASE_PASSWORD` 環境変数で渡します。サーバーURL・wikiid・Property対応はbootstrapで作るregistryに保存します。資格情報、原データ、投入ジョブ、実行結果はGit管理しません。

## 互換性と資料

- 標準Action APIを使用し、SPARQLサービスに依存しません。HTTPSサーバーとloopbackのHTTP接続を受け付けます。
- Wikidata PIDはローカルProperty自身の文に、確認済みQIDは医療機関Itemの文に保存します。ローカル採番とは区別します。
- `validate` / `plan` は従来のオフライン検証・計画コマンドです。`plan` はサーバー上の差分を取得しません。
- [全件投入の検証記録](docs/FULL_IMPORT_TEST_20260910.md)
- [初回3件の表示・PID/QID確認記録](docs/LOCAL_IMPORT.md)
- [Custom Wikibase API調査と並行開発の境界](docs/custom-wikibase-integration.md)
- [初期アーキテクチャ案](docs/architecture.md)

MIT。旧WikibaseSync・Custom Wikibaseのソースコードはコピーしていません。
