# YouTube ショート動画 自動生成

毎日自動で **縦型ショート動画（1分以内）** を作って YouTube に投稿する仕組みです。
**すべて無料**で動きます（API の有料プランは使いません）。

```
ネタ集め ──▶ 台本 ──▶ 読み上げ音声 ──▶ スライド＋字幕 ──▶ mp4 ──▶ YouTube 投稿
Wikipedia      自動      Edge TTS         Pillow + ffmpeg              YouTube Data API
（今日は何の日）                                                  GitHub Actions で毎日実行
```

## 作れる動画

| ネタ (`source`) | 内容 |
|---|---|
| `today` | Wikipedia「○月○日」から出来事3つを選んで「何年？」3択クイズ動画（`config.yaml` の `today.format: list` で紹介形式に戻せます） |
| `topics` | `topics.yaml` に書いた雑学ネタを日替わりで動画化 |
| `auto`（既定） | まず `today`、失敗したら `topics` |

## 1. 自分の PC で試す

必要なもの: Python 3.10 以上、ffmpeg、日本語フォント

```bash
pip install -r requirements.txt
python main.py                     # 今日の「今日は何の日」
python main.py --source topics     # 雑学ネタ
python main.py --date 2026-12-25   # 日付を指定
```

`output/` に mp4（と、タイトル・説明文が入った json）ができます。

## 2. 毎日自動で動かす（GitHub Actions）

このリポジトリを GitHub に置くだけで、`.github/workflows/daily-short.yml` が
**毎日 15:40（日本時間）** に動画を作り始め、16時ごろに投稿されます。時刻は `cron` の行で変えられます。

- 手動実行: GitHub の **Actions → 毎日ショート動画を作って投稿 → Run workflow**
- できた動画は各実行ページの **Artifacts** からダウンロードできます
- YouTube の設定（次の手順）をしていなければ、動画を作るところまでで止まります

## 3. YouTube への自動投稿を設定する（1回だけ）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作る
2. 「API とサービス → ライブラリ」で **YouTube Data API v3** を有効にする
3. 「OAuth 同意画面」を作成（ユーザーの種類: 外部）し、**テストユーザーに自分の Google アカウントを追加**
   - 公開ステータスを **「本番環境」** にしておくとトークンが 7 日で切れません（未審査の警告は出ますが自分用なら問題なし）
4. 「認証情報 → OAuth クライアント ID」で **デスクトップアプリ** を作り、JSON をダウンロード →
   `client_secret.json` としてこのフォルダに置く（Git には上がりません）
5. 自分の PC で実行:
   ```bash
   pip install google-auth-oauthlib
   python scripts/get_youtube_token.py
   ```
   ブラウザでチャンネルのアカウントを選んで許可すると 3 つの値が表示されます
6. GitHub のリポジトリ → **Settings → Secrets and variables → Actions** に登録
   - `YT_CLIENT_ID` / `YT_CLIENT_SECRET` / `YT_REFRESH_TOKEN`

### ⚠️ 公開設定について
Google の審査（API 監査）を通していないプロジェクトから API で投稿した動画は、
**自動的に「非公開」になります**。そのため最初は `config.yaml` の `upload.privacy: private` にしています。

- 投稿された動画を YouTube Studio で確認して、手動で公開する運用がおすすめ（内容チェックにもなります）
- 完全自動で公開したい場合は、Google の [YouTube API 監査フォーム](https://support.google.com/youtube/contact/yt_api_form) で申請し、
  通ったら `privacy: public` に変えてください

無料枠は 1 日 10,000 ユニットで、1 回の投稿は約 1,600 ユニット（1日数本まで OK）です。

## ⚖️ みんなの裁判（視聴者がコメントで判決を出すシリーズ）

正解のない架空のトラブルを毎日1件出し、視聴者がコメントで **A（原告の勝ち）か B（被告の勝ち）** に投票します。
次の回の冒頭で前回の判決（票の割合と、コメントから選んだ意見）を発表するので、毎回続けて見てもらえる作りです。

```
前回の動画のコメントを集計 ──▶ 新しい事件を作る ──▶ 「前回の判決」＋「今回の事件」の動画 ──▶ 投稿
 YouTube Data API              Claude API（無ければ手持ち）   Edge TTS + Pillow + ffmpeg        ＋投票案内コメント
                                                                                              ＋履歴をコミット
```

- **毎日 18:40（日本時間）** に `.github/workflows/saiban.yml` が自動で動き、19時ごろに投稿されます
- 手動実行: **Actions → みんなの裁判を作って投稿 → Run workflow**
- 自分の PC で試す: `python saiban.py`（動画を作るだけ）／ `python saiban.py --upload`（投稿まで）

### 追加で必要な設定

1. **コメント権限付きのトークンを取り直す**（投票の集計と案内コメントに必要）
   `python scripts/get_youtube_token.py` をもう一度実行し、表示された `YT_REFRESH_TOKEN` で Secrets を上書きしてください。
   取り直さなくても投稿はできますが、判決発表と案内コメントは飛ばされます。
2. **（任意）`ANTHROPIC_API_KEY` を Secrets に登録**すると、Claude が毎回新しい事件を作り、コメントから紹介する意見も選びます。
   無ければ `saiban/cases.yaml` の手持ちの事件（10件）を順番に使います。手持ちは書き足せます。
   費用の目安は 1 本あたり数円〜十数円です（`config.yaml` の `saiban.model` / `effort` で調整）。
   安全フィルターで断られたときは、別のモデルで自動的にやり直す設定にしています。

### note の記事も同時に作られます
動画と同じ事件を、「考えるヒント」付きの読み物にした note 記事が `output/` に出力されます（Actions では Artifacts に入ります）。
note には公式の投稿 API が無いので、投稿は手作業です。

1. `*_note.html` をブラウザで開く
2. 「① タイトルをコピー」→ note の「記事を書く」のタイトル欄に貼る
3. 「② 本文をコピー」→ 本文欄に貼る（見出し・太字・箇条書きはそのまま入ります）
4. 末尾のハッシュタグを note のハッシュタグ欄に入れて公開

`--upload` で投稿したときは、記事内に動画の URL が自動で入ります。

### 注意
- **動画が「公開」でないとコメントが付かず、投票できません。** 審査前の API プロジェクトから投稿すると強制的に非公開になるので、
  その場合は YouTube Studio で公開してください（上の「公開設定について」を参照）
- 投票は 1 人 1 票（最初のコメントを採用）。「A」「B」「原告」「被告」のどれか一方だけを含むコメントを数えます
- 事件はすべてフィクションで、説明文に断り書きを自動で入れています
- 投稿した事件と票数は `saiban/history.json` に記録され、ワークフローが自動でコミットします

## 声（ずんだもん）

読み上げは **VOICEVOX のずんだもん** です（`config.yaml` の `voice`）。GitHub Actions では VOICEVOX ENGINE が自動で起動します。

- 声を変える: `voice.speaker` を `ずんだもん（あまあま）` `ずんだもん（ツンツン）` `四国めたん` `春日部つむぎ` などに
- 速さ・抑揚: `voice.speed` / `voice.intonation`
- 元の声に戻す: `voice.engine: edge`
- 自分の PC で使う: [VOICEVOX](https://voicevox.hiroshiba.jp/) を起動しておけば、そのまま使われます
- VOICEVOX が起動していないときは、自動で Edge TTS の声で作ります
- **クレジット表記が必須**です。投稿時に説明文へ「音声：VOICEVOX:ずんだもん」を自動で入れています。消さないでください

## アニメ風の画面（みんなの裁判）

みんなの裁判は、1 フレームずつ描いた **動くアニメ風** の画面です（`config.yaml` の `saiban.style: anime`）。

- 絵文字のキャラクター（白フチのステッカー）が、ずんだもんの声の大きさに合わせて弾んで「しゃべる」
- 吹き出しの文字が 1 文字ずつ出る／集中線・ポップイン・画面の揺れ・「勝訴」のハンコ
- 原告は左、被告は右に立って言い合う
- 静止画のカード型に戻すときは `saiban.style: card`
- 59 秒を超えそうなときは「みんなの声」の場面を自動で外します（note の記事には残ります）

## カスタマイズ

- **`config.yaml`** … 声（女性/男性）、話す速さ、最大秒数、紹介する出来事の数、公開設定 など
- **`topics.yaml`** … 雑学ネタ帳。書き足すほどネタが増えます
- **`assets/bgm/`** … BGM。プログラムで作曲したオリジナル曲が3曲入っていて、日替わりで使われます。`python scripts/make_bgm.py` で作り直せます。好きな曲（著作権フリーのもの）の mp3 を置けば追加できます
- **`shorts/render.py`** … 色・レイアウト（`PALETTES` で配色を追加）

## 注意

- 文章は Wikipedia（CC BY-SA 4.0）をもとにしているので、説明文に出典を自動で入れています。消さないでください
- AI 音声を使っているので、投稿時に「合成コンテンツ」として申告しています
- 自動で選ばれた出来事の文章は Wikipedia の表現そのままなので、たまに不自然な読み上げになることがあります。
  気になる場合は公開前に YouTube Studio で確認してください

## ファイル構成

```
main.py                     実行の入口
config.yaml / topics.yaml   設定とネタ帳
shorts/sources.py           ネタ集め・台本作り
shorts/wikitext.py          Wikipedia の文章の整形
shorts/tts.py               音声合成（VOICEVOX / Edge TTS）
shorts/render.py            スライド描画と動画化（Pillow + ffmpeg）
shorts/anime.py             アニメ風の動く画面（みんなの裁判）
shorts/pipeline.py          全体の流れ
shorts/upload.py            YouTube 投稿・コメントの読み書き
shorts/saiban.py            みんなの裁判（事件づくり・投票集計・台本）
saiban.py                   みんなの裁判の実行の入口
saiban/cases.yaml           みんなの裁判の手持ちの事件（note 用の「考えるヒント」付き）
shorts/note.py              note の記事（md と貼り付け用 html）を作る
saiban/history.json         投稿した事件と判決の記録
scripts/get_youtube_token.py  投稿用トークン取得
.github/workflows/daily-short.yml  毎日の自動実行
.github/workflows/saiban.yml       みんなの裁判の毎日の自動実行
```
