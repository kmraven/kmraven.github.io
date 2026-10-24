# このリポジトリの運用方針

- 経歴・学歴・業績・研究分野・公開識別子はresearchmapで編集する。`src/data/researchmap.public.json` は生成物として扱い、直接編集しない。研究紹介の文章・図はサイト側で管理する。
- 取り込みには全項目を含む完全なJSONLエクスポートを使う。`npm run import:researchmap -- <JSONLのパス>` は公開用JSON全体を置き換えるため、差分エクスポートは使わない。
- 原本のJSONL・ZIPには非公開情報が含まれるため、Gitに登録せず、`public/` にも置かない。データとしてコミットするのは公開用JSONのみ。
- 公開は一時停止中。`.github/workflows/deploy.yml` の `deploy` ジョブを意図的に無効にしており、`main` へのpushでは検証とビルドだけを実行する。再開時は `deploy.if` を `${{ github.event_name != 'pull_request' }}` に戻す。
