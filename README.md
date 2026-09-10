# wikibase-registry-sync

Wikibase SuiteとCustom Wikibaseへのバッチ投入・継続更新に向けた汎用ツールです。医療固有の処理を含まず、ほかのベースレジストリでも共通形式を利用できる設計とします。

Custom Wikibaseの通常APIと専用バッチ入口を比較し、必要な互換性・性能・再開機能を検証することを開発目的に含めます。

## 現在の実装（0.1）

- bundleの型・キー・対応バージョン検証
- Wikidata Property/Itemから対象ローカルIDへの明示mapping
- 出典・限定子と確認済みWikidataリンクを保持したオフライン投入計画

**サーバーへの書込みは未実装です。** `plan`は対象サーバーを読まず、現在値との差分や対象Propertyの型を検証しません。Suite/Customの両方とも実接続の互換性試験は未実施です。

## ローカル実行

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
wikibase-registry-sync validate /tmp/medical-bundle.json
wikibase-registry-sync plan /tmp/medical-bundle.json examples/registry.json
python -m unittest discover -s tests -v
```

bundleは [jp-medical-registry](https://github.com/hirokiu/jp-medical-registry) の例で生成できます。registry内のP番号は説明用の仮値で、実サーバーのPropertyではありません。WikidataリンクにはURL型の専用ローカルPropertyを指定します。

[設計と次の実装](docs/architecture.md)。MIT。旧WikibaseSyncのソースコードは現段階ではコピーしていません。
