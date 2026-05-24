# boatrace-analysis

GitHub private リポジトリで、競艇・ボートレースの高配当反省を毎日朝5時に自動更新するための一式です。

## 何をするものか

- BoatraceOpenAPI の results / programs / previews JSON を取得
- 3連単払戻 5,100円以上のレースを抽出
- 1着/2着/3着の艇番、実進入、本番ST、展示、級別、年齢、体重、モーター、ボートを結合
- 次回の競艇予想で使う反省ルールを Markdown / CSV として出力
- GitHub Actions で毎日 **日本時間 朝5:00** に自動更新

## 料金について

- private リポジトリでも GitHub Free の Actions 無料枠内で動かす想定です。
- 1日1回、Linuxランナーで実行します。
- 大きな中間ファイルやActions Artifactは保存しません。
- ただし、無料枠を超える使い方をした場合は課金対象になる可能性があります。

## 重要

BoatraceOpenAPI は非公式データです。最終判断は BOAT RACE 公式で照合してください。

## ローカル実行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python boatrace_analysis.py --start-date 2026-04-01 --end-date yesterday --threshold 5100
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python boatrace_analysis.py --start-date 2026-04-01 --end-date yesterday --threshold 5100
```

## GitHub Actions

`.github/workflows/update_boatrace_analysis.yml` が毎日朝5時JSTに自動実行します。

手動実行も可能です。

## 出力ファイル

- `output/high_payout_lesson_rules.md`
- `output/next_prediction_prompt.md`
- `output/high_payout_5100_over.csv`
- `output/pattern_by_boat_order.csv`
- `output/pattern_by_course_order.csv`
- `output/winner_features_summary.csv`
- `output/stadium_high_payout_summary.csv`
- `output/boatrace_analysis.sqlite`
