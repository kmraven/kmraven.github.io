# このリポジトリの運用方針

- 日英のHome・CV・Misc.と、Misc.から開ける音楽遍歴（`/music/`・`/en/music/`）を掲載する。業績一覧はHomeの自己紹介・研究紹介の下に掲載し、CVと同じ公開用データを参照する。
- 配色は初回に端末設定に従い、ヘッダーの太陽・月ボタンで変更できる。手動選択はブラウザに保存し、日英・ページ間で共有する。CVの印刷は白背景を使用する。

- 経歴・学歴・業績・研究分野・公開識別子はresearchmapで編集する。`src/data/researchmap.public.json` は生成物として扱い、直接編集しない。研究紹介の文章・図はサイト側で管理する。
- 手で管理する研究室名・外部リンク・写真・日英の自己紹介や研究紹介は [`content/`](content/README.md) にまとめる。研究室名やリンクの空欄、下書きの文章はサイトに表示しない。researchmapの再取り込みでこのフォルダは変更しない。
- 取り込みには全項目を含む完全なJSONLエクスポートを使う。`npm run import:researchmap -- <JSONLのパス>` は公開用JSON全体を置き換えるため、差分エクスポートは使わない。
- 原本のJSONL・ZIPには非公開情報が含まれるため、Gitに登録せず、`public/` にも置かない。データとしてコミットするのは公開用JSONのみ。
- `.github/workflows/deploy.yml` で検証・ビルド後にGitHub Pagesへ公開する。`main`へのpushと手動実行で公開し、pull requestでは検証のみを実行する。

## 音楽遍歴を更新する

Appleの「データとプライバシー」で新しいエクスポートを取得し、完全に展開した **Apple Music Activity** フォルダを指定する。Python は `uv` で実行する。元CSV・ZIPは公開ディレクトリとGitの外に置く。

### 配信ジャンルとアーティストの作風を取り込む

掲載中の地図と同じ集計には以下を使う。最初のコマンドは、MusicBrainzのアーティストと録音の公式スナップショット（今回合計約4.2 GB）を取得し、SHA-256を検証して `private/musicbrainz/` に保存する。取得には `curl`、集計には `tar` と `zstd` を使用する。名義は手元で照合し、追加のメタデータ取得時にはApple日本ストアに曲ID、WikidataにMusicBrainzのアーティストIDを送る。再生日時・再生時間は送信しない。

```sh
activity_dir="/path/to/Apple Music Activity"
uv run scripts/fetch-musicbrainz.py
uv run scripts/import-music.py "$activity_dir" --musicbrainz-dir private/musicbrainz \
  --genre-sources private/music-genre-sources.json --update-genres
```

同じ入力フォルダで新しいCSVの展開を待つときは、最後のコマンドに `--watch` を加える。新しい曲名や名義が増えたら、必要な索引をダンプから作り直し、未照会のIDだけを追加取得して全名義のタグ類似度を再計算する。取得結果と該当なしの応答は非公開キャッシュに保存し、通信失敗時には前回の公開用データを維持して再試行する。取得済みの入力からオフラインで再集計するには `--update-genres` を外す。MusicBrainzの新しい登録を取り込むには再度 `fetch-musicbrainz.py` を実行する。Appleへの履歴開示申請とGitHub Pagesへの反映は別の手順になる。

照合にはMusicBrainzに登録されたAppleのアーティストIDを優先する。名前で探す場合は、名義または別名と、そのアーティストの録音タイトルの両方を照合する。Appleの曲IDをキーに、履歴・ライブラリ・Identifier Information・最近の再生・お気に入り・任意のカタログから別題を集める。たとえば「花に亡霊」と “Ghost In A Flower” は同じ曲として日英両方で検索できる。同名アーティストが複数いる場合は、一候補だけで独立した2曲以上の一致を求める。同じ曲の別題は1件の証拠として扱う。共演録音を証拠に使う場合は、元の共演名義全体と曲名が一致し、候補のアーティストIDがその録音の参加者に含まれていることも確認する。名義の照合根拠・MBID・得票数は手元の `matches.json` に残る。

同じMusicBrainzアーティストIDに確認できた名義は、再生時間が最長の表記を代表にして一つのノードに集計する。検索では履歴中の別表記と、MusicBrainzの正式名・日英の優先表記を利用する。綴りや大文字・小文字が似た名前でも、本人と確認できない名義は別に残す。

共演曲は先頭のアーティストに再生時間を1回だけ計上する。名義中の区切り、参加者の単独表記、MusicBrainzに登録されたグループ名、曲IDに対応するAppleカタログの名義を参照する。グループ名自体に記号が含まれる場合や区切りを特定できない場合は名義全体を保つ。`history.json` の曲ごとの `credit` に集約前の共演名義、`titleAliases` に別題が入り、検索と曲詳細に使われる。Appleの情報から大分類が定まらない場合は、アルバムの名義とジャンル、MusicBrainzのジャンル別得票、単一名義の再生コンテナを利用する。

曲詳細には、Apple日本ストアで同じ曲IDについて取得できた配信ジャンルを表示する。アーティストの配置はMusicBrainzと、MBIDが一意に一致したWikidata項目のジャンル（P136）を使う。トゲナシトゲアリには公式プロフィールのバンド紹介と作品情報も添える。複数資料に共通するタグは最大の票数を採用し、大分類の得票が並ぶ場合は裏付ける出典数、細分類数、聴いた曲のジャンル分布を順に見る。作風から分類できるときは、アニメなどの媒体を表すタグより音楽的な分類を優先する。

作風の手掛かりが足りない名義では、Appleから取得した曲のジャンルを大分類別に数える。全期間で再生時間が正の曲IDを各1票とし、そのような曲が1曲もない名義に限って履歴にある曲IDを使う。ジャンルが取れなかった曲は分布に「記録なし」と表示し、配置の投票からは除く。

類似度には、配信ジャンルを使わず、各アーティストに出典のある作風タグを用いる。表記を統一し、アニメやサウンドトラックなど媒体だけを表すタグを除き、TF-IDFで重み付けしてアーティスト間のコサイン類似度を求める。類似度0.35以上で、2ジャンル以上を共有するか、登録が少ない細分類を共有し、互いに上位3件に入るペアを結ぶ。境界で順位を決められない同点群は除く。円の大きさと年別再生時間は元のApple履歴による。`history.json` の `coverage.musicbrainz` には表記統合後の照合・タグ取得・線が付いた各段階のアーティスト数と再生時間（ミリ秒）が入る。

直接の分類が決まらなかった名義には、類似度0.60以上の辺を最大2本たどる。各経路で最初に到達した既知の名義を集め、異なる2組以上が見つかり、全組の大分類が一致した場合にその領域に配置する。根拠に使うのは作風、曲の配信ジャンル、エクスポートの資料から直接分類できた名義。推定結果は次の推定には使わない。`history.json` の `graphGroups` に推定先と根拠名義、`unclassifiedReasons` に残った理由が入る。`coverage.graphHoldout` は既知名義を5分割し、順に分類を隠して予測が成立した数と元の分類に一致した数を集計する。`apple` はこのうち、最初のApple履歴・ライブラリ・カタログ処理で分類できた名義を表す。

アーティスト詳細に出典と分類根拠を表示する。[Wikidataのジャンル](https://www.wikidata.org/wiki/Property:P136)・[Appleのカタログ照会](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/LookupExamples.html)・[トゲナシトゲアリ公式紹介](https://www.universal-music.co.jp/togenashitogeari/biography/)

MusicBrainzのコミュニティによる共通タグと、それを加工・計算した類似関係・近隣からの推定分類には **CC BY-NC-SA 3.0** を適用する。[アーティストダンプの仕様とライセンス](https://musicbrainz.org/doc/Development/JSON_Data_Dumps) · [録音の照合データ](https://musicbrainz.org/doc/Canonical_MusicBrainz_data) · [ライセンス本文](https://creativecommons.org/licenses/by-nc-sa/3.0/)

地図・一覧の ☆ は、エクスポート時点でApple Musicのお気に入りに登録されていた曲・アーティストを示す。曲とアーティストの登録状態は独立している。年を切り替えても星は同じスナップショットを参照する。

### Appleの履歴とカタログだけで集計する

```sh
activity_dir="/path/to/Apple Music Activity"
uv run scripts/import-music.py "$activity_dir"
```

毎回、Daily Tracks 全体から `public/music/history.json` を再生成する。差分を追記しないため、同じエクスポートを再投入しても二重計上されない。同じ入力フォルダを継続監視する場合は `--watch` を付ける。手元のプレビューには更新結果が反映され、GitHub Pagesに反映する際は通常どおり公開用JSONの変更をデプロイする。

各年の集計には全AUDIO行の `Play Duration Milliseconds` を使う。ジャンルの大分類には曲のカタログ情報やライブラリのジャンル、および名義ごとの代表ジャンルを利用する。特定できない名義・曲・分類も残す。各再生の日時、端末、アカウント情報は公開用JSONに含めない。

Apple Musicカタログの類似関係は任意。Apple Developer Program加入済みのAccount HolderまたはAdminは、[Appleの手順](https://developer.apple.com/jp/help/account/capabilities/create-a-media-identifier-and-private-key/)に従ってMusicKitを有効にしたMedia IDとMedia Services鍵を作成し、秘密鍵（.p8）はプロジェクト外に保存する。Team IDとKey IDを指定し、12時間有効なDeveloper Tokenを手元で署名して取得バッチに渡す。本人の再生履歴はエクスポートから読むので Music User Token は不要。

```sh
APPLE_MUSIC_DEVELOPER_TOKEN="$(node scripts/music-token.mjs TEAM_ID KEY_ID /path/to/AuthKey.p8)" \
  uv run scripts/music-catalog.py "$activity_dir/Apple Music - Play History Daily Tracks.csv"
uv run scripts/import-music.py "$activity_dir" --catalog private/music-catalog-jp.json
```

カタログは曲IDをまとめて照会し、対応するアーティストの `similar-artists` を取得する。キャッシュはGit管理外の `private/` に置く。中断時は同じコマンドで再開できる。以前の取得分も更新するには `music-catalog.py` に `--refresh` を付ける。API呼び出しは手元の更新時だけで、閲覧者の認証は不要。[Apple Musicの認証](https://developer.apple.com/musickit/)・[類似アーティストの仕様](https://developer.apple.com/documentation/applemusicapi/artists/views-data.dictionary)

Apple Musicの類似アーティスト情報を履歴の名義間で照合できた場合は、その関係を表示する。該当するペアがない場合は、ライブラリやカタログの楽曲に付いたジャンルから名義ごとの構成を比べる。ジャンルの大分類を一つに特定できた曲名を各1票とし、3曲以上・2分類以上の名義を対象にする。2分類以上を共有し、曲数ベクトルのコサイン類似度が0.8以上で、互いに上位3候補に入る名義だけを結ぶ。同点では共有する分類の数、次に名義の表記順で順位を決める。同じアーティストとして照合できる別表記の組は除く。条件を満たすペアがなければ線は表示しない。
