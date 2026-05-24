# 更新版の入れ替え手順

## 入れ替えるファイル

GitHubで以下を上書きしてください。

- `boatrace_analysis.py`
- `.github/workflows/update_boatrace_analysis.yml`
- `tests/test_boatrace_analysis.py`
- `README.md`

## 不要なら削除してよいもの

- `__pycache__`
- `TEST_RESULT.txt`

## 確認

Actions画面から `Run workflow` を押して、緑のチェックになればOKです。
