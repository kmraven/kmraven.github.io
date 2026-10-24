# Ryota Kimura — Research profile

木村亮太の個人サイトです。Astroで日英のホーム・業績一覧・Web CVを静的生成し、GitHub Pagesで公開します。

公開先: https://kmraven.github.io/

**現在は公開を一時停止しています。** GitHub PagesをUnpublishし、ワークフローの公開ジョブも無効にしています。`main`へのpushでは検証とビルドだけが実行されます。

## ローカルで開く

Node.js **24.x** とnpmを使用します。`.nvmrc` にも指定しています。

```sh
npm ci
npm run dev
```

ターミナルに表示されるローカルURLを開いてください。検証と本番ビルドは `npm run verify`、ビルド後の確認は `npm run preview` です。

## researchmapから更新する

経歴・学歴・業績・研究分野・公開識別子の編集元はresearchmapです。サイト用のJSONを直接編集しません。

1. researchmapを更新し、全項目を含むJSON形式でエクスポートします。ZIPを展開するとJSONLファイルが得られます。
2. ローカルで変換します。

   ```sh
   npm run import:researchmap -- /path/to/rm_researchers.jsonl
   ```

3. 採用件数・除外件数・未対応の種別を確認します。
4. `git diff -- src/data/researchmap.public.json` で掲載内容を確認し、`npm run verify` を実行します。
5. 公開用JSONの変更をコミットして `main` にpushします。

変換は毎回、完全なスナップショットから全体を再生成します。差分エクスポートは使用しないでください。削除や非公開化も再エクスポートと取り込みで反映されます。検証に失敗した場合、直前の公開用JSONは置き換えません。

### 公開範囲

- 業績は `display: disclosed` の項目だけを採用します。公開設定が欠けた項目も除外します。
- 所属と職名、ORCIDはそれぞれの個別公開設定を確認します。外部リンク経由でも非公開識別子を拾いません。
- 原本のJSONLとZIP、`private/` はGit管理対象外です。公開用JSONだけをコミットします。原本を `public/` に置かないでください。
- 現在の対応種別は基本情報、研究分野、経歴、学歴、論文、発表です。未対応の種別は掲載せず、変換時に通知します。
- 年月のみの日付はそのまま保持します。終了日 `9999` は「現在／Present」に変換します。
- 翻訳がない題目・著者名は元の言語で表示し、その部分のHTMLにも原文の言語を設定します。

公開用データの契約は `src/data/schema.ts` で検証します。内部ID、メール、研究者限定の識別子、非公開学歴、所属区分、エフォート率は出力しません。テスト用の原本には架空の値を使用しています。

## 研究紹介を追加する

- 日本語: `src/content/research/ja.md`
- 英語: `src/content/research/en.md`

Markdown本文を書き、先頭の `published: false` を `published: true` に変更すると、その言語のホームに研究紹介が表示されます。未公開・本文が空の場合は欄ごと非表示になります。紹介文や図はサイト側で管理し、研究業績を再入力する必要はありません。

画像は `public/images/` に置き、Markdownから `![説明](/images/example.png)` のように参照できます。公開可能な画像だけを置いてください。

GitHubプロフィールのURLは `src/data/index.ts` で管理します。氏名や所属、ORCIDは公開用データから参照します。

## ページとCV

| 日本語 | English |
|---|---|
| `/` | `/en/` |
| `/publications/` | `/en/publications/` |
| `/cv/` | `/en/cv/` |

CVの「印刷」ボタンかブラウザの印刷機能で、A4用の印刷レイアウトを利用できます。専用のPDF生成処理は含めていません。

## GitHub Pagesに公開する

公開を再開するときは、`.github/workflows/deploy.yml` の `deploy.if` を `github.event_name != 'pull_request'` に戻してpushします。以下は公開を有効にした場合の動作です。

1. `kmraven/kmraven.github.io` リポジトリを使用します。公開用データとソースだけをpushします。
2. GitHubの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
3. `main` へのpushで検証・ビルド・公開が実行されます。Pull Requestでは検証とビルドだけを実行します。

公開処理は元のエクスポート、researchmap認証情報、外部APIを必要としません。失敗したビルドは公開せず、直前のサイトを維持します。取り消すときは対象コミットをrevertしてpushします。

## 検証

`npm run verify` で以下を実行します。

- AstroとTypeScriptの型検査。
- 公開範囲、原題の保持、日付、リンク、削除・非公開化を含む変換テスト。
- 架空の非公開データを含む入力から6ページをビルドし、非公開値がHTMLに含まれないことを確認。
- 本番ビルドと、生成HTMLの件数・メタ情報・言語切替・内部リンク・サイトマップ・Git追跡対象の確認。

表示の変更後は、スマートフォン表示、キーボード操作、日英CVの印刷プレビューも確認してください。
