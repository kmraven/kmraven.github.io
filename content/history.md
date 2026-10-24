---
entries:
  # 東京大学・2026年4月〜
  - id: "utokyo-2026"
    category: education
    match:
      organization: "東京大学"
      start: "2026-04"
    lab:
      name:
        ja: "生命知能システム研究室（高橋・白松研究室）"
        en: "Bio-Intelligence Systems Lab (Takahashi–Shiramatsu Lab)"
      url: "https://www.ne.t.u-tokyo.ac.jp/"

  # 慶應義塾大学大学院・2024年4月〜2026年3月
  - id: "keio-graduate-2024"
    category: education
    match:
      organization: "慶應義塾大学"
      start: "2024-04"
    lab:
      name:
        ja: "システム生物学研究室（舟橋研究室）"
        en: "Systems Biology Laboratory (Funahashi Laboratory)"
      url: "https://fun.bio.keio.ac.jp/"

  # 慶應義塾大学・2019年4月〜2024年3月
  - id: "keio-undergraduate-2019"
    category: education
    match:
      organization: "慶應義塾大学"
      start: "2019-04"
    lab:
      name:
        ja: "システム生物学研究室（舟橋研究室）"
        en: "Systems Biology Laboratory (Funahashi Laboratory)"
      url: "https://fun.bio.keio.ac.jp/"

  # 慶應義塾高等学校・2016年4月〜2019年3月（補足がなければ空欄のまま）
  - id: "keio-high-school-2016"
    category: education
    match:
      organization: "慶應義塾高等学校"
      start: "2016-04"
    lab:
      name:
        ja: ""
        en: ""
      url: ""

  # 日本学術振興会 特別研究員（DC2）・2027年4月〜2029年3月
  - id: "jsps-dc2-2027"
    category: experience
    match:
      organization: "独立行政法人日本学術振興会"
      start: "2027-04"
    lab:
      name:
        ja: ""
        en: ""
      url: ""
---

学歴・経歴ごとの研究室情報を管理します。`lab.name.ja`、`lab.name.en`、`lab.url` を記入してください。
研究室名が空欄なら、その略歴には研究室の行を表示しません。

- `id`: このファイル内で一意の管理名。ホームに出す研究室は `profile.md` の `current_lab` にこの値を指定します。
- `category`: 学歴は `education`、経歴は `experience`。
- `match.organization` / `match.start`: researchmapの大学・機関名と開始年月。略歴の対応付けに使います。
- `lab.name`: その時期の研究室名。日本語か英語の片方だけでも掲載できます。
- `lab.url`: その研究室のURL。URLなしで名前だけの掲載も可能です。

並び順ではなく、種別・大学や機関名・開始年月で対応付けます。
researchmapの名称や開始年月を変更した場合は、ここの `match` も合わせてください。
非公開化・削除された略歴の研究室情報は、ホームを含めてサイトに表示しません。
このファイル自体はresearchmapの再取り込みで上書きされません。
