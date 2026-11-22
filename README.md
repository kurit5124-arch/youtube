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

このリポジトリを GitHub に置くだけで、`.github/workflows/daily-short.yml` が毎日3本の動画を作って投稿します。

| 時間（日本時間） | 内容 |
|---|---|
| 朝 7時ごろ | 「今日は何の日」クイズ（記念日の説明＋何年？3択クイズ3問） |
| 夜 19時ごろ | 雑学（`topics.yaml` から） |
| 夜 21時ごろ | 雑学（`topics.yaml` の別のネタ） |

時刻は `cron` の行で変えられます（UTC で書きます）。

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

## 4. 別チャンネルでアフィリエイト（任意）

メインのクイズチャンネルとは**別の YouTube チャンネル**で、雑学ショート＋商品紹介リンクで稼ぐ仕組みです。
メインチャンネルの動画には広告リンクは入りません。

```
channels/affiliate/topics.yaml ──▶ 雑学ショート ──▶ 別チャンネルに投稿（毎日 19時ごろ）
                                       │
channels/affiliate/affiliate.yaml ─────┴─▶ 動画のテーマに合う商品リンク＋【PR】表記を説明欄に自動挿入
                                       └─▶ まとめページ（GitHub Pages）に商品一覧を公開
```

ショート動画は**説明欄やコメントのリンクを押せない**ため、視聴者には
「プロフィールのリンクから」と案内し（締めのナレーションに自動で入ります）、まとめページへ誘導します。

### 設定の手順
1. **別チャンネルを作る**: YouTube で新しいチャンネル（ブランドアカウント）を作成
2. **アフィリエイトに登録**: [Amazonアソシエイト](https://affiliate.amazon.co.jp/) や [楽天アフィリエイト](https://affiliate.rakuten.co.jp/) に登録し、
   ID（Amazon は `xxxx-22` のトラッキングID、楽天はアフィリエイトID）を確認。
   申請時のサイト欄には、このチャンネルの URL やまとめページの URL を書きます
3. **ID を登録**: GitHub の **Settings → Secrets and variables → Actions → Variables** に
   `AMAZON_ASSOCIATE_TAG` / `RAKUTEN_AFFILIATE_ID` を追加（片方だけでも OK）
4. **別チャンネル用の投稿トークン**: 自分の PC で
   ```bash
   python scripts/get_youtube_token.py client_secret.json YT2
   ```
   ブラウザで**新しいチャンネル**を選んで許可 → 表示された `YT2_REFRESH_TOKEN` を **Secrets** に登録
   （Google Cloud のプロジェクトはメインと同じでよく、`YT2_CLIENT_ID` / `YT2_CLIENT_SECRET` は省略可）
5. **まとめページを公開**: **Settings → Pages → Source** を **GitHub Actions** にする。
   `channels/affiliate/` を main に push すると `https://<ユーザー名>.github.io/<リポジトリ名>/` に公開されます
6. 新しいチャンネルの **プロフィールのリンク** にまとめページの URL を設定

### おすすめ商品を自動で選ぶ（楽天の商品検索API・任意）
キーを登録すると、`affiliate.yaml` の `search:` の商品が「レビューが多く評価の高い具体的な商品」に
自動で置き換わり、リンクはあなたの楽天アフィリエイトリンクになります（まとめページは毎日更新）。

1. [楽天ウェブサービス](https://webservice.rakuten.co.jp/) にログインし、**アプリID発行** → 新規アプリを作成
   - 許可されたWebサイト: `kurit5124-arch.github.io`（まとめページのドメイン）
2. 表示された **アプリID**（UUID 形式）と **アクセスキー**（`pk_` で始まる）を、
   GitHub の Secrets に `RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` として登録

キーが無いときや API が失敗したときは、今までどおり楽天の検索結果へのリンクになります。

### 試す
```bash
python main.py --channel affiliate                  # 日替わりのネタで1本作る
python main.py --channel affiliate --topic-index 1  # ネタを指定
python scripts/build_affiliate_site.py              # まとめページを site/ に作る
```

### 稼ぐためのコツ
- **ネタと商品をセットで増やす**: `topics.yaml` にネタを足し、`affiliate.yaml` の `themes` に合う商品を足す（`keywords` がタイトル・タグに入ると自動で選ばれます）
- `search:` は検索結果へのリンクで手軽ですが、**実際に良いと思う商品の個別リンクを `url:` で書く**ほうが売れやすいです
- 「睡眠」「コーヒー」「ペット」など**買い物につながりやすいテーマ**を多めに

### ⚠️ ルール
- 2023年10月からステマ規制があるので、説明欄とまとめページには **【PR】表記を自動で入れています。消さないでください**
- Amazon リンクを使うときは「Amazonのアソシエイトとして…」の文言も自動で入ります（規約で必須）
- 商品について事実でないこと（効果の断定など）は書かないでください

## カスタマイズ

- **`config.yaml`** … 声（女性/男性）、話す速さ、最大秒数、紹介する出来事の数、公開設定 など
- **`topics.yaml`** … 雑学ネタ帳。書き足すほどネタが増えます
- **`assets/bgm/`** … BGM。プログラムで作曲したオリジナル曲が3曲入っていて、日替わりで使われます。`python scripts/make_bgm.py` で作り直せます。好きな曲（著作権フリーのもの）の mp3 を置けば追加できます
- **`shorts/render.py`** … 色・レイアウト（`PALETTES` で配色を追加）
- **`shorts/illust.py`** … 背景イラスト（Noto Color Emoji）。言葉とイラストの対応表 `KEYWORDS` に追加できます

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
shorts/tts.py               音声合成（Edge TTS）
shorts/render.py            スライド描画と動画化（Pillow + ffmpeg）
shorts/pipeline.py          全体の流れ
shorts/upload.py            YouTube 投稿
scripts/get_youtube_token.py  投稿用トークン取得
shorts/affiliate.py         アフィリエイトリンク挿入・まとめページ作成
channels/affiliate/         アフィリエイト用チャンネルの設定・ネタ帳・商品リスト
scripts/build_affiliate_site.py   まとめページを作る
.github/workflows/affiliate-short.yml  アフィリエイト用チャンネルの毎日投稿
.github/workflows/affiliate-site.yml   まとめページの公開（GitHub Pages）
.github/workflows/daily-short.yml  毎日の自動実行
```
