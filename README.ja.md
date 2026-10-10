[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

# MusicScore v1 個人用楽譜クライアント

Windows のローカルアプリです。MuScriptor による採譜、楽譜ライブラリ、移調、音符編集、ピアノ／ギターのコード表記、試聴、MuseScore での編集に対応します。

[MuScriptor](https://github.com/muscriptor/muscriptor)、[MuseScore](https://github.com/musescore/MuseScore)、[AccoMontage2](https://github.com/billyblu2000/AccoMontage2) を基盤とし、ネイティブ画面には PySide6 を使用しています。現在のソースは **v1（1.0.0）** で、個人利用向けの実験版です。全機能の安定動作を示すものではありません。

## v1 の状態と既知の問題

音声の読み込み後、音源分離、採譜、コード解析、譜式変換、編集、履歴、再生の連携で多くの不具合が発生していました。未対応のコード名による後処理失敗、音高のない打楽器音符による楽譜の表示失敗、履歴文字の重複、長いタイトルでレイアウトが再帰して終了する問題などを修正しました。**今後も多くの不具合が残っていると考えられます。** すべての互換性問題が解決したわけではなく、生成した楽譜は手作業で校正してください。

**和声編曲は、まだ完全に利用できる機能ではありません。** AccoMontage2 の画面と生成処理は接続済みで、通常の和声生成は動作した実績がありますが、スタイル指定時に「長さの一致する素材がない」というエラーが残っています。完全な伴奏モードは追加モデル資源が不足しているため無効です。スタイルは標準ポップ、複雑なポップ、ダーク、R&B ですが、問題の修正まで指定スタイルでの生成成功は保証しません。現在の入力条件は単旋律、4/4 拍子、一定のテンポ、4 または 8 小節のフレーズです。失敗時も元の旋律バージョンを保持します。

v1 のソースは 56 件のテストを通過しました。ローカル採譜、CUDA 音源分離、楽譜プレビュー、編曲の一部を過去に確認していますが、テスト数は全場面での利用を保証しません。

## ブランチ構成

`main` は統合アプリ全体、`v1` はアップロード時の版を保存します。各機能ブランチは同じ v1 ソースから作成し、共通依存を維持して後でマージします。独立した縮小アプリではありません。各機能ブランチの `docs/BRANCH_SCOPE.md` に保守範囲を記載しています。

| ブランチ | 主な範囲 | 主なファイル |
| --- | --- | --- |
| `feature/native-client` | Qt 画面、プレイヤー、録音、起動 | `qt_client.py`、`desktop.py`、起動スクリプト、`static/icons/` |
| `feature/transcription` | ローカル／リモート MuScriptor 採譜、モデル取得 | `transcribe_worker.py`、`model_download.py`、`app.py` の採譜 API |
| `feature/audio-separation` | 音声／動画入力、任意の音源分離、分離音の試聴 | `separation_worker.py`、`separator-requirements.txt`、メディア API |
| `feature/score-editing` | MuseScore、移調、音符編集、コード、派生譜式 | `music.py`、`notation.py`、編集 API |
| `feature/library-export` | 楽譜一覧、履歴、ごみ箱、書き出し | `app.py` のプロジェクト／版 API、`qt_client.py` の対応画面 |
| `feature/ai-assistant` | OpenAI、DeepSeek 等の互換 API を使う AI アシスタント | `app.py` の AI API、`qt_client.py` の AI 画面 |
| `feature/harmony-arrangement` | 未完成の AccoMontage2 和声編曲 | `arrangement.py`、`arrangement_worker.py`、編曲 API と画面 |

収録するのはアプリのソース、テスト、アイコン、依存関係の説明です。**個人の楽譜、録音、分離音、書き出したファイル、モデル重み、PC 設定、認証情報、ログ、仮想環境はアップロードしません。**

## ソース実行環境の準備

Windows に Python 3.12、Git、MuseScore 4 をインストールし、リポジトリのルートで環境を作成します。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -r arrangement-requirements.txt
git submodule update --init --depth 1
git -C tools/AccoMontage2 apply ../../patches/accomontage2-chord-pipeline.patch
```

GPU 版 PyTorch は GPU と CUDA の互換性に応じて別途選択してください。標準の依存インストールだけで CUDA 推論が可能になるとは限りません。MuseScore 本体と MuScriptor の重みは別途導入・取得し、各ライセンスに同意する必要があります。AccoMontage2 はコミットを固定したサブモジュール参照で、データやモデルをこのリポジトリへコピーしません。ただし、サブモジュール自体に大きな参考データが含まれる場合があります。パッチは和声のみの処理で欠けていた引数を修正します。完全伴奏の資源不足とスタイル指定の問題は未解決です。

音源分離には `.separator-venv` を別途作り、`separator-requirements.txt` をインストールします。元の PC 環境では主環境の CUDA PyTorch を共有し、互換バージョンを固定しています。詳細は下記のとおりです。新しい PC 向けの依存分離を一括設定するスクリプトはまだありません。ソースリポジトリは、そのまま実行できるパッケージ版インストーラーではありません。

## 起動

デスクトップまたはアプリフォルダの `MusicScore.lnk` をダブルクリックするか、`Start.ps1` を実行します。PySide6 Qt Widgets のネイティブ画面を使い、WebView2 や埋め込み Web ページは使用しません。楽譜プレビューは QtPdf、下部固定プレイヤーは QtMultimedia です。最小化、最大化、サイズ変更、サイドバーの折りたたみ、録音に対応し、再起動すると既存のウィンドウを前面に出します。旧 Web クライアントは `work/webview-client-legacy.py` のバックアップとして説明されており、標準の起動経路では使いません。

ウィンドウを閉じてもローカルのバックグラウンド処理は残り、採譜・ダウンロードを続行します。実行中のタスクがあれば確認を表示します。自動起動の設定や Windows システムサービスの導入は不要です。完全に停止するには、タスク完了後に `StopService.ps1` を実行します。再度開くとローカル処理を起動または再利用し、モデルを重複して読み込みません。

標準ポートは `8765` で、使用中なら後続の空きポートを選びます。`127.0.0.1` のみで待ち受け、LAN に公開しません。Hugging Face のライセンスページなどの外部リンクは標準ブラウザで開きます。

元の PC での導入先は `G:\codex\MusicScore` です。既存 API キーを維持するため、Windows 資格情報のサービス名は `ScoreDesk` のままです。`CreateShortcut.ps1` で起動ショートカットを再作成できます。導入先を移動する際は、実行環境の起動スクリプトとショートカットを修正してください。

## ローカルパスと書き出し

設定の「アプリインストール先」は実際の導入先を表示し、隣のフォルダボタンで開けます。「楽譜の書き出し先」を並べて表示し、元の環境では `G:\codex\MusicScore\exports` が標準です。フォルダボタンで別の場所を選ぶか、絶対パスを入力して保存できます。

MusicXML、MIDI、MSCZ、PDF、現在の譜式の PDF を選ぶと、書き出し先へ直接保存し、実際のパスを表示します。曲名、プロジェクト ID、版ごとの構成で、繰り返し書き出す場合は番号を付け、既存ファイルを上書きしません。ライブラリ、元の入力、版データは導入先の `library/` に残り、書き出し先変更では移動しません。

## 初回設定

1. Hugging Face にログインし、公式 [medium](https://huggingface.co/MuScriptor/muscriptor-medium) と [small](https://huggingface.co/MuScriptor/muscriptor-small) のライセンスに同意します。
2. 設定に Hugging Face の read Token を入力・保存し、medium と small を取得します。認証情報は Windows 資格情報マネージャーに保存します。
3. MuseScore の実行ファイルは通常自動検出します。手動で `MuseScore4.exe` の絶対パスを選ぶこともできます。

重みのキャッシュは `models/`、楽譜と元の入力は `library/` です。削除内容は Windows のごみ箱に移し、ローカルの `trash/` は使いません。取得に失敗したモデルはキャッシュ済み表示になりません。small、medium、large を選択でき、標準は medium、CUDA float16、batch size 1、GPU タスクは直列です。large は公式ページで別途ライセンスに同意し、設定から取得します。VRAM 使用量や速度は自分の PC で測定し、メモリ不足なら小さいモデルを選んでください。

設定と制作状況に small、medium、large のダウンロード進捗を表示します。主ステータス欄は実際の取得バイト数、総容量、割合、最近の速度を表示します。ファイル情報取得中は待機表示とし、仮の割合を示しません。完了時のみ 100% と表示します。連続クリックで同一モデルの重複タスクは作りません。再試行は Hugging Face のキャッシュと途中再開を利用できます。

401/403 は Hugging Face のアクセス拒否であり、裏で取得が続いている状態ではありません。Token に対応するアカウントにログインし、そのモデルのライセンスに同意して、アクセス可能な有効 Token を使用してください。

## リモート API と AI アシスタント

用途が異なる 2 種類の API があります。

- **リモート MuScriptor**：small、medium、large それぞれの重みを動かす公式互換 MuScriptor サービスの URL を設定します。`/transcribe/midi` に multipart の `file` と任意の `instruments` を送り、標準 MIDI を受け取ります。モデルは事前にサーバーへ展開する必要があります。ChatGPT／DeepSeek の URL は音楽モデルの代わりになりません。ローカル以外の URL には HTTPS が必要です。
- **AI アシスタント**：OpenAI、DeepSeek、OpenAI 互換 API の `/chat/completions` に対応します。サービス URL、利用可能なモデル ID、API Key を設定します。楽譜の音符から助言し、MuScriptor を実行したり、音声を聞いたと装ったり、自動で楽譜を書き換えたりしません。送信する音符イベントは最大 1000 件です。

アプリ自体も `POST /api/transcribe` を提供します。フォームは `file`、`mode`（local/remote）、`model`、`instruments` です。job/project ID を返し、`/api/status` で進捗を確認できます。詳細は `/docs` を参照してください。

## 利用と版管理

音声／動画を読み込むと、FFmpeg が最初の音声トラックをモノラル 24 kHz WAV に変換し、元ファイルを保持します。MIDI、MusicXML、MSCZ の読み込みも可能です。編集ごとに新版を作成し、書き出し失敗で現在の版を置き換えません。

QtMultimedia によるマイク録音、一時停止／再開、停止に対応します。停止後はライブラリに取り込み、試聴、音源分離、直接の採譜ができます。マイク権限は Windows の設定で管理し、録音失敗は通知します。すべての音声ドライバーで自動ゲインやシステム音響効果を無効化できるとは限りません。

## 任意の音源分離

音声／動画の読み込み後、FFmpeg がステレオの元ミックスを抽出します。そのまま採譜するか、先に分離できます。nomadkaraoke/python-audio-separator 0.47.0 を使い、htdemucs_6s の 6 トラック、htdemucs の 4 トラック、UVR_MDXNET_KARA_2 のボーカル／伴奏 2 トラックを提供します。6 トラックはボーカル、ドラム、ベース、ギター、ピアノ、その他です。独立したバイオリントラックはなく、アコースティック／エレキギターの完全な分離も保証しません。下部プレイヤーで各トラックを試聴、シーク、書き出しでき、選んだ音を採譜して MuseScore で編集します。

分離は `.separator-venv/` で実行し、モデルは `models/separator/`、音源は各プロジェクトの `stems/` に保存します。rotary-embedding-torch の競合を避けるため MuScriptor と依存を分離し、CUDA torch 2.11.0+cu128 は主環境から共有します。ONNX Runtime GPU は CUDA 12 互換の 1.23.2 に固定しています。更新時に CPU torch を自動導入して共有 CUDA 環境を上書きしないでください。分離と採譜は直列キューを共有し、一時停止、再開、取消に対応します。初めて使う分離モデルは自動取得します。元ファイルは変更せず、曲の削除では分離音とプロジェクト記録も Windows のごみ箱へ移します。

下部の「楽譜試聴」は音符の合成音で、元の録音や MuseScore の完全な楽器音源ではありません。編集、移調、コード解析、版切替、AI、モデル取得、書き出し先は既存のローカルサービスを引き続き利用します。

分離機能の出典・謝辞：[nomadkaraoke/python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator)、上流の Ultimate Vocal Remover / UVR、Demucs の作者。コードとモデルはそれぞれのライセンスに従います。

ライブラリは検索、PDF 表示、MusicXML/MIDI/MSCZ/PDF の書き出し、音符編集、移調、コード再認識、版切替、アーカイブに対応します。内蔵再生は基本的な合成試聴で、楽器音や演奏の詳細は MuseScore を使用します。

各曲の右に削除ボタンがあり、開かずに操作できます。確認後、元の入力、楽譜、全履歴、プロジェクト記録を Windows のごみ箱へ移します。失敗時はエラーを表示し、完全削除に切り替えません。他の場所へ書き出した独立コピーは残ります。採譜・編集中の曲は削除できません。

MuseScore ボタンは現在の版の `edited.mscz` コピーを開きます。保存後に隣の同期ボタンでライブラリに新版を作成します。自動編集は MusicXML で交換するため、複雑な奏法や細かいレイアウトが変化することがありますが、元の MSCZ 編集コピーは保持します。移調／音符変更後は古い弦・フレット注記を保持しないため、MuseScore で TAB を確認・調整してください。

自動コードは piano/guitar パートで同時に鳴る音を music21 で識別し、Harmony として記入します。あくまで候補で、アルペジオ、欠けたコード音、装飾音、複雑なジャズ和声、採譜誤りにより抜けや誤判定が生じます。バイオリンなどのパートにはギターコードを自動追加しません。

## ギターとピアノの譜式

- **ギター**：旋律の数字譜、コード名、TAB を同じページに生成し、PDF と MSCZ を開けます。旋律は各音符イベントの最高音を取り、旋律分離モデルではありません。複雑なフィンガースタイルや多声部は校正が必要です。MuseScore 標準の 6 弦調弦を用い、自動運指が最適とは限りません。
- **ピアノ**：両手の五線譜と数字譜をメニューで切り替えます。既存の左右 Staff は保持し、単旋律を初めて取り込む際は中央 C で分けて自動割当と表示します。手の交差や声部の交差は主楽譜で調整します。
- 主楽譜の MusicXML を共有し、音声の再採譜はしません。移調、音符編集、主楽譜の同期後に各譜式を再生成します。元の音高、音価、左右手情報を保持し、画像や PDF からの音符抽出には対応しません。
- 数字譜は実験的な変換層で、MuseScore の完全なネイティブ機能ではありません。見える数字で音高を表し、基礎の音符は残します。数字、変化記号、オクターブ点、休符、一般的な音価に対応します。多声部、タイ、特殊なリズム、複雑な組版は未検証部分があり、出版品質は保証しません。短調の 1 は平行長調の主音です。
- 「譜式を開く」は派生 MSCZ、「MuseScore」は同期できる主楽譜コピーを開きます。主楽譜を編集・同期してから譜式を再生成し、派生した数字テキストを直接編集して音高を変えないでください。ギター派生譜の旋律は MuseScore でミュートし、TAB との二重再生を避けます。

MuseScore のネイティブ数字譜については[開発議論](https://github.com/orgs/musescore/discussions/22698)が続いています。五線譜と TAB は維持し、数字譜表示で上書きしません。

## 検証

`.venv/Scripts/python.exe -m pytest -q` を実行します。実際の採譜には許諾済みの公式モデル重みが必要です。有効な API キーがない場合、外部 AI サービスは呼び出しません。

依存プロジェクト：[MuScriptor](https://github.com/muscriptor/muscriptor)、[MuseScore](https://github.com/musescore/MuseScore)、[AccoMontage2](https://github.com/billyblu2000/AccoMontage2)、[music21](https://github.com/cuthbertLab/music21)、[Lucide](https://github.com/lucide-icons/lucide)、[python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator)。MuScriptor の重みは CC BY-NC 4.0 に従います。依存コード、参考データ、モデルはそれぞれの上流ライセンスに従い、このリポジトリは許諾を変更しません。
