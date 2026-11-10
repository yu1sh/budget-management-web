# 家計簿・医療費記録

個人・世帯向けの、GitHubからクローンして自分のサーバーだけで使う家計簿／医療費記録アプリです。データはDockerの永続ボリューム内のSQLiteとCSVに保存され、アプリは第三者サービスへ家計情報・医療費情報を送信しません。

## 機能

- 月別家計簿（日付、種別、店名、内訳、金額、支払い元、備考）と当月合計。共通の日付・店名・支払い元に対して複数の「内訳＋金額」行を追加し、1回でまとめて登録できます。
- カード・コード決済・ポイント・銀行・交通系（Suica/PASMO等）など支払い元別の読取専用集計。コード決済はカード・銀行・現金を必須で、カードは銀行を任意で引き落とし元として設定できます。入力時には直接／最終引き落とし元と経路を保存し、「引き落とし元別」では最終引き落とし元ごとに一度だけ集計します。
- 支払い元ごとのイメージカラー（厳密な`#RRGGBB`）を支払い元設定・銀行管理で指定できます。支払い元別カードと詳細画面へ淡い配色を反映し、履歴のある支払い元の削除は設定・履歴を壊さず非表示化します。
- 「クレジットカード引落明細」では支払月を選び、カードごとの締め日・支払い日・当月／翌月／翌々月設定から利用期間を算出します。28〜31日・月末は月末に丸め、直接カード利用とカード連携コード決済を重複なく表示・印刷・CSV出力します。未設定カードは未設定として案内します。
- 銀行は専用の「銀行を管理」画面でも追加・編集・利用停止・メモ管理できます。支払い元設定の銀行と同じデータを使うため、重複登録は発生しません。
- 支払い元を「フリマ」として選ぶと、家計簿の通常入力内で利益または出金を指定して登録できます。フリマ明細も同じ一覧・CSV・範囲選択印刷で確認でき、当月の家計簿支出合計には含めません。旧フリマ台帳の記録は更新時に共通明細へ引き継がれます。
- 人別・年別の医療費記録。医療費から対象者を選び、既存病院を選択または新規追加してから、病院専用ページで受診日・病院費用・薬局・交通費を入力します。薬局・交通費は選択した病院に付随する明細として保存されます。人別／全員合計とCSV出力にも対応します。
- サーバー内CSVミラー、月別・年別CSVダウンロード、毎日03:00の30世代バックアップ
- 任意の表範囲を選択してブラウザーの印刷／PDF保存
- 管理者パスワードによるログイン

医療費機能は簡易な記録・集計です。国税庁の明細書に必要な区分や補てん額は扱わないため、そのまま申告書へ取り込めるものではありません。

旧版から更新する場合、既存の医療費明細は削除されません。旧明細には受診日や関連する病院の情報がないため、各行を記録年の1月1日の単独受診記録として移行します。旧薬局・交通費は病院名を推測せず、単独記録として保持します。

## 導入

必要なものは、Docker Compose、独自ドメイン、外部から到達できる80/443番ポートです。DNSのA/AAAAレコードをサーバーに向けてから実行してください。

```bash
git clone https://github.com/YOUR_ACCOUNT/budget-management-web.git
cd budget-management-web
chmod +x setup.sh scripts/*.sh
./setup.sh
```

セットアップはドメインと管理者パスワードを端末で対話入力します。パスワードはコマンド履歴、`.env`、コンテナログには保存されません。CaddyがHTTPS証明書を取得した後、表示された `https://` アドレスを開いてください。

ローカル開発では `.env.example` を `.env` にコピーして、必ず固有の`DJANGO_SECRET_KEY`を設定したうえで `DEBUG=1` と `SECURE_SSL_REDIRECT=0` に変更し、`docker compose up --build` を使えます。`DEBUG=0`で秘密鍵が未設定または初期値の場合、アプリは安全のため起動を拒否します。実運用でHTTPのまま公開しないでください。

## 日常運用

本番コードの更新は GitHub Actions が行います。サーバー上で `git pull` や `docker compose up --build` を実行すると旧配置のコードを起動するため、手動更新には使わないでください。状態と直近ログは次のコマンドで確認できます。

```bash
cd /path/to/your/deployment
docker compose ps
docker compose logs --tail=100 app
```

復元する場合は、先に対象バックアップを安全な場所へコピーし、サーバー上で `./scripts/restore.sh /absolute/path/to/backup` を実行します。復元中はアプリが一時停止します。

## GitHub Actions による自動デプロイ

`main` への push 時、テストと secret/data チェックが両方成功した後に GitHub-hosted runner から本番へデプロイします。runner は Tailscale の OIDC 連携で一時的に tailnet へ接続し、SSH のポートをインターネットに公開しません。デプロイは Git commit SHA ごとの不変ディレクトリで行い、既存の本番 `.env` と Docker ボリュームを再利用します。

デプロイ前にアプリとバックアップサービスを停止して `app_runtime` 全体と整合性確認済み SQLite バックアップを保存します。バックアップはサーバー上の専用ディレクトリに蓄積し、自動削除しません。起動後の応答確認に失敗すると直前のアプリコードを再起動します。データの自動復元は行わず、バックアップを保持します。古いリリースとイメージも自動削除しません。

GitHub リポジトリの **Settings → Environments → production** で、デプロイ可能なブランチを `main` に制限し、次の値を設定します。

| 種類 | 名前 | 値 |
| --- | --- | --- |
| Variable | `DEPLOY_HOST` | 本番サーバーの Tailscale IPv4 アドレス |
| Variable | `DEPLOY_PORT` | `22` |
| Variable | `DEPLOY_USER` | 制限付きの専用SSHユーザー |
| Variable | `DEPLOY_PATH` | サーバー上の配置先の絶対パス |
| Variable | `DEPLOY_KNOWN_HOSTS` | 別経路で確認した本番サーバーのホスト鍵エントリ |
| Variable | `TS_OAUTH_CLIENT_ID` | Tailscale の federated identity client ID |
| Variable | `TS_AUDIENCE` | 同 federated identity の audience |
| Secret | `DEPLOY_SSH_KEY` | デプロイ専用SSH秘密鍵（パスフレーズなし） |

Tailscale には `tag:ci` と、本リポジトリの `production` 環境だけを信頼する GitHub OIDC federated identity を設定します。ACL はユーザー端末の接続を維持しつつ、`tag:ci` から本番サーバーの TCP/22 だけを許可します。専用 SSH 公開鍵は forced command に固定し、通常のシェル、ポート転送、Docker 操作権限は与えません。アプリ側のデプロイヘルパーだけが root 権限で動作します。

`DEPLOY_KNOWN_HOSTS` に設定するホスト公開鍵は本番サーバーから取得し、SHA-256 フィンガープリントを別経路で確認済みです。workflow は厳密なホスト鍵検証を行い、実行時の `ssh-keyscan` で鍵を信頼することはありません。

## データとプライバシー

- 実データはDocker名前付きボリュームの`/app/runtime`にだけ保存されます。
- SQLite、CSV、バックアップ、`.env`、ログは`.gitignore`対象です。コミット前に `git status` で確認してください。
- TLS証明書の取得・更新を除き、実行中のアプリは外部通信を行いません。外部フォント、分析、広告、クラウド保存は使いません。
- このアプリは1世帯・管理者1アカウント向けです。サーバーのOS更新、ディスク暗号化、ファイアウォールは設置者が管理してください。

## 開発・テスト

```bash
python -m pip install -r requirements-dev.txt
DJANGO_SECRET_KEY='local-test-secret' DEBUG=1 SECURE_SSL_REDIRECT=0 python manage.py migrate
DJANGO_SECRET_KEY='local-test-secret' DEBUG=1 SECURE_SSL_REDIRECT=0 pytest
```

MIT Licenseで公開しています。テストや画面例には架空のサンプル名称だけを使用してください。
