# GitHub private リポジトリ構築手順

## 1. GitHubアカウントを作る

1. GitHub を開く
2. Sign up を押す
3. メールアドレス、パスワード、ユーザー名を登録する
4. メール認証を済ませる

## 2. private リポジトリを作る

1. 右上の `+` を押す
2. `New repository` を押す
3. Repository name に `boatrace-analysis` と入れる
4. `Private` を選ぶ
5. `Add a README file` はオンでもオフでもよい
6. `Create repository` を押す

## 3. ZIPの中身をアップロードする

1. このZIPを解凍する
2. GitHubの `boatrace-analysis` リポジトリを開く
3. `Add file` → `Upload files` を押す
4. 解凍した中身を全部ドラッグする
   - `.github` フォルダも必ず含める
   - `boatrace_analysis.py`
   - `requirements.txt`
   - `tests` フォルダ
   - `README.md`
5. `Commit changes` を押す

## 4. GitHub Actions を有効にする

1. リポジトリ上部の `Actions` タブを押す
2. 初回だけ確認画面が出たら有効化する
3. `Update BOAT RACE analysis` が表示されればOK

## 5. 手動で1回実行する

1. `Actions` タブを押す
2. 左側の `Update BOAT RACE analysis` を押す
3. `Run workflow` を押す
4. start_date は `2026-04-01`
5. end_date は `yesterday`
6. threshold は `5100`
7. 緑のチェックが出るまで待つ

## 6. 毎朝5時に自動実行されるか確認する

この設定では、毎日朝5時JSTに自動実行します。

GitHubのcronはUTCなので、ファイル内では次のようになっています。

```yaml
- cron: "0 20 * * *"
```

これは日本時間の朝5時です。

## 7. 出力を見る

実行後、`output` フォルダに以下ができます。

- `high_payout_lesson_rules.md`
- `next_prediction_prompt.md`
- `high_payout_5100_over.csv`
- `pattern_by_boat_order.csv`
- `pattern_by_course_order.csv`
- `winner_features_summary.csv`
- `stadium_high_payout_summary.csv`

## 8. 次回ChatGPTに競艇予想を頼むとき

プロンプトに以下を書きます。

```text
まずGitHubの private リポジトリ `あなたのユーザー名/boatrace-analysis` を確認してください。
`output/high_payout_lesson_rules.md` と `output/next_prediction_prompt.md` を読んでから予想してください。
ただし、今回レースの公式直前情報・展示・オッズを最優先してください。
```
