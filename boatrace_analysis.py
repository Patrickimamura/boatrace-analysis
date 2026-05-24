from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry


DEFAULT_START_DATE = "2026-04-01"
DEFAULT_THRESHOLD = 5100

BASE_URLS = {
    "results": "https://boatraceopenapi.github.io/results/v3/{year}/{ymd}.json",
    "programs": "https://boatraceopenapi.github.io/programs/v3/{year}/{ymd}.json",
    "previews": "https://boatraceopenapi.github.io/previews/v3/{year}/{ymd}.json",
}

CACHE_DIR = Path("cache_json")
OUT_DIR = Path("output")

STADIUM_MAP = {
    1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
    7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
    13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
    19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村",
}

# BoatraceOpenAPI programs の racer_class_number を表示用に変換。
# raw値もCSVに残すので、仕様差異があっても後で検証できます。
CLASS_MAP = {
    1: "A1",
    2: "A2",
    3: "B1",
    4: "B2",
}


def jst_today() -> dt.date:
    return (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()


def parse_date(value: str) -> dt.date:
    v = value.strip().lower()
    if v == "today":
        return jst_today()
    if v == "yesterday":
        return jst_today() - dt.timedelta(days=1)
    return dt.date.fromisoformat(v)


def daterange(start: dt.date, end: dt.date) -> Iterable[dt.date]:
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def ymd(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "boatrace-analysis/1.0"})
    return session


def fetch_json(
    session: requests.Session,
    kind: str,
    d: dt.date,
    *,
    use_cache: bool = True,
    sleep_sec: float = 0.15,
) -> Optional[Any]:
    year = d.strftime("%Y")
    ymd_str = ymd(d)
    cache_path = CACHE_DIR / kind / year / f"{ymd_str}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if use_cache and cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    url = BASE_URLS[kind].format(year=year, ymd=ymd_str)
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if sleep_sec:
            time.sleep(sleep_sec)
        return data
    except Exception as exc:
        print(f"[WARN] fetch failed kind={kind} date={ymd_str}: {exc}", file=sys.stderr)
        return None


def as_race_list(data: Any) -> List[Dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("races", "data", "results", "programs", "previews"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
        out: List[Dict[str, Any]] = []
        for value in data.values():
            if isinstance(value, dict):
                out.append(value)
            elif isinstance(value, list):
                out.extend([x for x in value if isinstance(x, dict)])
        return out
    return []


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        return int(float(value))
    except Exception:
        return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("F", "-").replace("L", "")
        return float(value)
    except Exception:
        return default


def normalize_exhibition_time(value: Any) -> Optional[float]:
    """展示タイムが 683 のような整数なら 6.83 に変換する。"""
    v = to_float(value)
    if v is None:
        return None
    if v > 100:
        return round(v / 100.0, 2)
    return v


def race_key(race: Dict[str, Any]) -> Tuple[str, int, int]:
    return (
        str(race.get("date")),
        to_int(race.get("stadium_number"), -1) or -1,
        to_int(race.get("number"), -1) or -1,
    )


def boat_map(race: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    if not race:
        return {}
    boats = race.get("boats") or []
    if not isinstance(boats, list):
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    for boat in boats:
        if not isinstance(boat, dict):
            continue
        no = to_int(boat.get("racer_boat_number"))
        if no is not None:
            out[no] = boat
    return out


def get_trifecta_payout(result_race: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    payouts = result_race.get("payouts") or {}
    trifecta = payouts.get("trifecta") or []
    if not isinstance(trifecta, list) or not trifecta:
        return None, None
    first = trifecta[0]
    if not isinstance(first, dict):
        return None, None
    combination = first.get("combination")
    amount = to_int(first.get("amount"))
    return str(combination) if combination else None, amount


def parse_combination(combination: Optional[str]) -> List[Optional[int]]:
    if not combination:
        return [None, None, None]
    s = str(combination).strip().replace(" ", "")
    for sep in ("-", "=", "－", "ｰ"):
        if sep in s:
            parts = s.split(sep)
            break
    else:
        parts = list(s)
    nums: List[Optional[int]] = []
    for p in parts[:3]:
        nums.append(to_int(p))
    while len(nums) < 3:
        nums.append(None)
    return nums


def class_label(raw: Any) -> Optional[str]:
    n = to_int(raw)
    if n is None:
        return None
    return CLASS_MAP.get(n, str(n))


def add_program_preview_features(
    row: Dict[str, Any],
    prefix: str,
    boat_no: int,
    program_boats: Dict[int, Dict[str, Any]],
    preview_boats: Dict[int, Dict[str, Any]],
) -> None:
    pb = program_boats.get(boat_no, {})
    vb = preview_boats.get(boat_no, {})

    row[f"{prefix}_racer_number"] = pb.get("racer_number")
    row[f"{prefix}_racer_name"] = pb.get("racer_name")
    row[f"{prefix}_class_number_raw"] = pb.get("racer_class_number")
    row[f"{prefix}_class_label_est"] = class_label(pb.get("racer_class_number"))
    row[f"{prefix}_branch_number"] = pb.get("racer_branch_number")
    row[f"{prefix}_birthplace_number"] = pb.get("racer_birthplace_number")
    row[f"{prefix}_age"] = pb.get("racer_age")
    row[f"{prefix}_weight_program"] = pb.get("racer_weight")
    row[f"{prefix}_flying_count"] = pb.get("racer_flying_count")
    row[f"{prefix}_late_count"] = pb.get("racer_late_count")
    row[f"{prefix}_average_start_timing"] = pb.get("racer_average_start_timing")
    row[f"{prefix}_national_top1"] = pb.get("racer_national_top_1_percent")
    row[f"{prefix}_national_top2"] = pb.get("racer_national_top_2_percent")
    row[f"{prefix}_national_top3"] = pb.get("racer_national_top_3_percent")
    row[f"{prefix}_local_top1"] = pb.get("racer_local_top_1_percent")
    row[f"{prefix}_local_top2"] = pb.get("racer_local_top_2_percent")
    row[f"{prefix}_local_top3"] = pb.get("racer_local_top_3_percent")
    row[f"{prefix}_motor_no"] = pb.get("racer_assigned_motor_number")
    row[f"{prefix}_motor_top2"] = pb.get("racer_assigned_motor_top_2_percent")
    row[f"{prefix}_motor_top3"] = pb.get("racer_assigned_motor_top_3_percent")
    row[f"{prefix}_assigned_boat_no"] = pb.get("racer_assigned_boat_number")
    row[f"{prefix}_boat_top2"] = pb.get("racer_assigned_boat_top_2_percent")
    row[f"{prefix}_boat_top3"] = pb.get("racer_assigned_boat_top_3_percent")
    row[f"{prefix}_preview_course_no"] = vb.get("racer_course_number")
    row[f"{prefix}_preview_start_timing"] = vb.get("racer_start_timing")
    row[f"{prefix}_preview_weight"] = vb.get("racer_weight")
    row[f"{prefix}_weight_adjustment"] = vb.get("racer_weight_adjustment")
    row[f"{prefix}_exhibition_time_raw"] = vb.get("racer_exhibition_time")
    row[f"{prefix}_exhibition_time"] = normalize_exhibition_time(vb.get("racer_exhibition_time"))
    row[f"{prefix}_tilt"] = vb.get("racer_tilt_adjustment")


def make_flat_row(
    result_race: Dict[str, Any],
    program_race: Optional[Dict[str, Any]],
    preview_race: Optional[Dict[str, Any]],
    threshold: int,
) -> Dict[str, Any]:
    date, stadium_no, race_no = race_key(result_race)
    combination, payout = get_trifecta_payout(result_race)
    order = parse_combination(combination)

    result_boats = boat_map(result_race)
    program_boats = boat_map(program_race)
    preview_boats = boat_map(preview_race)

    row: Dict[str, Any] = {
        "date": date,
        "stadium_number": stadium_no,
        "stadium_name": STADIUM_MAP.get(stadium_no, str(stadium_no)),
        "race_no": race_no,
        "closed_at": program_race.get("closed_at") if program_race else None,
        "day_label": program_race.get("day_label") if program_race else None,
        "grade_label": program_race.get("grade_label") if program_race else None,
        "grade_number": program_race.get("grade_number") if program_race else None,
        "title": program_race.get("title") if program_race else None,
        "subtitle": program_race.get("subtitle") if program_race else None,
        "distance": program_race.get("distance") if program_race else None,
        "has_program": bool(program_race),
        "has_preview": bool(preview_race),
        "trifecta_combination": combination,
        "trifecta_payout": payout,
        "net_profit_100yen": payout - 100 if payout is not None else None,
        "is_high_payout": bool(payout is not None and payout >= threshold),
        "technique_number": result_race.get("technique_number"),
        "result_wind_speed": result_race.get("wind_speed"),
        "result_wind_direction_number": result_race.get("wind_direction_number"),
        "result_wave_height": result_race.get("wave_height"),
        "result_weather_number": result_race.get("weather_number"),
        "result_air_temperature": result_race.get("air_temperature"),
        "result_water_temperature": result_race.get("water_temperature"),
        "preview_wind_speed": preview_race.get("wind_speed") if preview_race else None,
        "preview_wind_direction_number": preview_race.get("wind_direction_number") if preview_race else None,
        "preview_wave_height": preview_race.get("wave_height") if preview_race else None,
        "preview_weather_number": preview_race.get("weather_number") if preview_race else None,
        "preview_air_temperature": preview_race.get("air_temperature") if preview_race else None,
        "preview_water_temperature": preview_race.get("water_temperature") if preview_race else None,
    }

    place_courses: List[str] = []
    place_starts: List[str] = []
    place_classes: List[str] = []

    for pos, boat_no in enumerate(order, start=1):
        prefix = f"place{pos}"
        row[f"{prefix}_boat_no"] = boat_no
        if boat_no is None:
            continue

        rb = result_boats.get(boat_no, {})
        row[f"{prefix}_course_no_result"] = rb.get("racer_course_number")
        row[f"{prefix}_start_timing_result"] = rb.get("racer_start_timing")
        row[f"{prefix}_place_number_result"] = rb.get("racer_place_number")
        row[f"{prefix}_racer_number_result"] = rb.get("racer_number")
        row[f"{prefix}_racer_name_result"] = rb.get("racer_name")

        add_program_preview_features(row, prefix, boat_no, program_boats, preview_boats)

        place_courses.append(str(rb.get("racer_course_number")) if rb.get("racer_course_number") is not None else "")
        place_starts.append(str(rb.get("racer_start_timing")) if rb.get("racer_start_timing") is not None else "")
        place_classes.append(str(row.get(f"{prefix}_class_label_est") or ""))

    for boat_no in range(1, 7):
        prefix = f"boat{boat_no}"
        rb = result_boats.get(boat_no, {})
        row[f"{prefix}_boat_no"] = boat_no
        row[f"{prefix}_place_result"] = rb.get("racer_place_number")
        row[f"{prefix}_course_no_result"] = rb.get("racer_course_number")
        row[f"{prefix}_start_timing_result"] = rb.get("racer_start_timing")
        add_program_preview_features(row, prefix, boat_no, program_boats, preview_boats)

    row["boat_order"] = "-".join(str(x) for x in order if x is not None)
    row["course_order_result"] = "-".join(place_courses)
    row["start_order_result"] = "-".join(place_starts)
    row["class_order_est"] = "-".join(place_classes)
    return row


def load_joined(start_date: dt.date, end_date: dt.date, threshold: int, use_cache: bool = True) -> pd.DataFrame:
    session = make_session()
    rows: List[Dict[str, Any]] = []
    dates = list(daterange(start_date, end_date))

    for d in tqdm(dates, desc="fetch/analyze"):
        results = as_race_list(fetch_json(session, "results", d, use_cache=use_cache))
        programs = as_race_list(fetch_json(session, "programs", d, use_cache=use_cache))
        previews = as_race_list(fetch_json(session, "previews", d, use_cache=use_cache))

        program_map = {race_key(r): r for r in programs}
        preview_map = {race_key(r): r for r in previews}

        for result_race in results:
            key = race_key(result_race)
            rows.append(make_flat_row(result_race, program_map.get(key), preview_map.get(key), threshold))

    return pd.DataFrame(rows)


def write_sqlite(df: pd.DataFrame, threshold: int, out_dir: Path) -> None:
    db_path = out_dir / "boatrace_analysis.sqlite"
    with sqlite3.connect(db_path) as con:
        df.to_sql("all_races_flat", con, if_exists="replace", index=False)
        df[df["is_high_payout"] == True].to_sql(f"high_payout_{threshold}_over", con, if_exists="replace", index=False)


def summarize(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    high = df[df["is_high_payout"] == True].copy()
    summaries: Dict[str, pd.DataFrame] = {}

    if high.empty:
        return summaries

    summaries["pattern_by_boat_order"] = (
        high.groupby("boat_order", dropna=False)
        .agg(
            races=("boat_order", "size"),
            avg_payout=("trifecta_payout", "mean"),
            max_payout=("trifecta_payout", "max"),
            avg_net_profit=("net_profit_100yen", "mean"),
        )
        .reset_index()
        .sort_values(["races", "avg_payout"], ascending=[False, False])
    )

    summaries["pattern_by_course_order"] = (
        high.groupby("course_order_result", dropna=False)
        .agg(
            races=("course_order_result", "size"),
            avg_payout=("trifecta_payout", "mean"),
            max_payout=("trifecta_payout", "max"),
        )
        .reset_index()
        .sort_values(["races", "avg_payout"], ascending=[False, False])
    )

    summaries["winner_features_summary"] = (
        high.groupby(["place1_boat_no", "place1_class_label_est"], dropna=False)
        .agg(
            races=("trifecta_payout", "size"),
            avg_payout=("trifecta_payout", "mean"),
            max_payout=("trifecta_payout", "max"),
            avg_motor_top2=("place1_motor_top2", "mean"),
            avg_motor_top3=("place1_motor_top3", "mean"),
            avg_avg_st=("place1_average_start_timing", "mean"),
            avg_age=("place1_age", "mean"),
            avg_weight=("place1_weight_program", "mean"),
        )
        .reset_index()
        .sort_values(["races", "avg_payout"], ascending=[False, False])
    )

    summaries["stadium_high_payout_summary"] = (
        high.groupby(["stadium_number", "stadium_name"], dropna=False)
        .agg(
            high_payout_races=("trifecta_payout", "size"),
            avg_payout=("trifecta_payout", "mean"),
            max_payout=("trifecta_payout", "max"),
        )
        .reset_index()
        .sort_values(["high_payout_races", "avg_payout"], ascending=[False, False])
    )

    return summaries


def write_csv_outputs(df: pd.DataFrame, threshold: int, summaries: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "all_races_flat.csv", index=False, encoding="utf-8-sig")
    df[df["is_high_payout"] == True].to_csv(out_dir / f"high_payout_{threshold}_over.csv", index=False, encoding="utf-8-sig")

    for name, sdf in summaries.items():
        sdf.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8-sig")


def _top_lines(summaries: Dict[str, pd.DataFrame], name: str, key_col: str, limit: int = 10) -> List[str]:
    sdf = summaries.get(name)
    if sdf is None or sdf.empty:
        return ["- データなし"]
    lines = []
    for _, r in sdf.head(limit).iterrows():
        lines.append(f"- {r[key_col]}: {int(r['races'])}件 / 平均払戻 {r['avg_payout']:.0f}円 / 最大 {int(r['max_payout'])}円")
    return lines


def write_markdown_outputs(df: pd.DataFrame, threshold: int, start_date: dt.date, end_date: dt.date, summaries: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    high = df[df["is_high_payout"] == True].copy()
    total = len(df)
    high_count = len(high)
    high_rate = high_count / total * 100 if total else 0

    lines: List[str] = []
    lines.append("# 競艇 高配当反省ルール")
    lines.append("")
    lines.append("## 集計条件")
    lines.append("")
    lines.append(f"- 対象期間: {start_date.isoformat()} 〜 {end_date.isoformat()}")
    lines.append(f"- 抽出条件: 3連単払戻 {threshold:,}円以上")
    lines.append(f"- 全レース数: {total:,}件")
    lines.append(f"- 高配当レース数: {high_count:,}件")
    lines.append(f"- 高配当率: {high_rate:.2f}%")
    lines.append("")
    lines.append("## 艇番パターン上位")
    lines.extend(_top_lines(summaries, "pattern_by_boat_order", "boat_order"))
    lines.append("")
    lines.append("## 実進入コースパターン上位")
    lines.extend(_top_lines(summaries, "pattern_by_course_order", "course_order_result"))
    lines.append("")
    lines.append("## 次回予想の強制チェック")
    checks = [
        "2号艇の差し残り・2着・3着を、機力だけで安易に切らない。",
        "4カド攻めは、攻めた4号艇自身の2着・3着残りまで評価する。",
        "5号艇は展開差し・まくり差し・2着浮上・3着残りを必ず比較する。",
        "6号艇はA1/A2、平均ST良、展示良、良モーターなら頭・2着・3着すべてを見る。",
        "1号艇は逃げ固定にせず、2着残り・飛びの条件を確認する。",
        "展示最速艇は頭固定ではなく、2着・3着候補としても扱う。",
        "良モーターでもB1/B2の場合は、その足を操れるかを級別・年齢・体重・ST・当地勝率で確認する。",
        "A1/A2の外枠良機は、6号艇でも頭・2着・3着の全候補で比較する。",
        "3連単3艇BOXに無理に絞らず、3着候補が広い時はフォーメーションまたは見送りにする。",
        f"払戻{threshold:,}円以上の自然候補を切る場合は、展示・ST・機力・選手力・進入・水面の反証を明記する。",
        "過去傾向は補助情報であり、今回レースの公式直前情報・展示・オッズを最優先する。",
    ]
    for c in checks:
        lines.append(f"- {c}")
    (out_dir / "high_payout_lesson_rules.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    prompt = f"""# 競艇予想依頼プロンプト

## 入力条件

- 日付：
- 場：
- R：
- 予算：
- 目標純利益：

## 最初に確認すること

まずGitHubのこのリポジトリにある以下のファイルを確認してください。

- `output/high_payout_lesson_rules.md`
- `output/high_payout_{threshold}_over.csv`
- `output/pattern_by_boat_order.csv`
- `output/pattern_by_course_order.csv`
- `output/winner_features_summary.csv`
- `output/stadium_high_payout_summary.csv`

これらは、2026年4月以降の日次更新済みの競艇高配当分析結果です。
3連単払戻{threshold:,}円以上の高配当傾向、艇番、実進入、ST、級別、年齢、体重、モーター、ボート、展示気配を参考にしてください。

ただし、過去傾向は補助情報です。
今回レースでは、必ずBOAT RACE公式・競艇場公式の出走表、直前情報、展示、進入、オッズを最優先してください。
結果判明済みレースを予想扱いしないでください。

## 必須確認

- 出走表
- 級別：A1 / A2 / B1 / B2
- 期別
- 年齢
- 体重
- 全国勝率
- 当地勝率
- 平均ST
- モーター2連対率・3連対率
- ボート2連対率・3連対率
- 直前情報
- 展示タイム
- 展示ST
- スタート展示
- 実進入
- チルト
- 部品交換
- 風向・風速
- 波高
- 天候
- 気温・水温
- 潮位
- 3連単、3連複、2連単、2連複オッズ

取得できない情報は推測で埋めず、「未取得」「暫定」「確定不可」と明記してください。

## 予想手順

1. まずオッズ抜きで展開予想してください。
2. 進入、ST、1M展開、逃げ、差し、まくり、まくり差しを見てください。
3. 2着残り、3着残り、攻め艇、差し艇、内枠残り、外枠浮上を見てください。
4. 次にオッズを確認してください。
5. 自然な展開の中に、3連単払戻{threshold:,}円以上を狙える買い目があるか確認してください。
6. 2号艇残り、4カド攻め、5号艇展開差し、6号艇良機絡み、1号艇飛び/2着残りを必ず再確認してください。
7. 高配当でも根拠が弱ければ見送りにしてください。
8. 安い本線しか自然でない場合は、無理に穴へ寄せず見送りにしてください。

## 券種

3連単、3連複、2連単、2連複を必ず券種別に提示してください。
ただし、実際に買う券種は最後に1つだけ選んでください。

3連単3艇BOXは、1〜3着候補が本当に3艇で足りる場合だけ採用してください。
3着候補が広い場合は、フォーメーションまたは見送りを優先してください。

## 出力

iPhoneで見やすく、表形式中心で出してください。
1表は最大4列までにしてください。
説明は短く、ただし判断根拠は省略しないでください。

最後に必ず以下を出してください。

- 買い / 見送り
- 推定的中率
- 最終券種
- 最終買い目
- 点数
- 1点金額
- 合計金額
- 推定払戻
- 推定純利益
- 見送りの場合の理由
"""
    (out_dir / "next_prediction_prompt.md").write_text(prompt, encoding="utf-8")


def validate(df: pd.DataFrame, start_date: dt.date, end_date: dt.date) -> None:
    if df.empty:
        raise RuntimeError("No races were loaded. Check network/API availability.")
    required_columns = ["date", "stadium_number", "race_no", "trifecta_combination", "trifecta_payout"]
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing required columns: {missing}")

    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if not dates.empty:
        min_d = dates.min().date()
        max_d = dates.max().date()
        if min_d < start_date or max_d > end_date:
            raise RuntimeError(f"Loaded dates out of range: {min_d} - {max_d}")


def run(start_date: dt.date, end_date: dt.date, threshold: int, use_cache: bool = True, out_dir: Path = OUT_DIR) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("start_date must be <= end_date")

    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_joined(start_date, end_date, threshold, use_cache=use_cache)
    validate(df, start_date, end_date)
    summaries = summarize(df)
    write_csv_outputs(df, threshold, summaries, out_dir)
    write_sqlite(df, threshold, out_dir)
    write_markdown_outputs(df, threshold, start_date, end_date, summaries, out_dir)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="BOAT RACE high payout analysis")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default="yesterday", help="YYYY-MM-DD, today, or yesterday")
    parser.add_argument("--threshold", default=DEFAULT_THRESHOLD, type=int, help="Trifecta payout threshold")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cache and fetch again")
    args = parser.parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    df = run(start_date, end_date, args.threshold, use_cache=not args.no_cache, out_dir=OUT_DIR)
    high_count = int(df["is_high_payout"].sum())
    print(f"DONE: all={len(df):,}, high_payout={high_count:,}, output={OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
