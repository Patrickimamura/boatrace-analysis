from __future__ import annotations
import argparse, datetime as dt, json, sqlite3, sys, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

DEFAULT_START_DATE = "2026-04-01"
DEFAULT_THRESHOLD = 5100
DEFAULT_REFRESH_RECENT_DAYS = 14

BASE_URLS = {
    "results": "https://boatraceopenapi.github.io/results/v3/{year}/{ymd}.json",
    "programs": "https://boatraceopenapi.github.io/programs/v3/{year}/{ymd}.json",
    "previews": "https://boatraceopenapi.github.io/previews/v3/{year}/{ymd}.json",
}
CACHE_DIR = Path("cache_json")
OUT_DIR = Path("output")

STADIUM_MAP = {1:"桐生",2:"戸田",3:"江戸川",4:"平和島",5:"多摩川",6:"浜名湖",7:"蒲郡",8:"常滑",9:"津",10:"三国",11:"びわこ",12:"住之江",13:"尼崎",14:"鳴門",15:"丸亀",16:"児島",17:"宮島",18:"徳山",19:"下関",20:"若松",21:"芦屋",22:"福岡",23:"唐津",24:"大村"}
CLASS_MAP = {1:"A1",2:"A2",3:"B1",4:"B2"}

def jst_today() -> dt.date:
    return (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()

def parse_date(value: str) -> dt.date:
    v = value.strip().lower()
    if v == "today": return jst_today()
    if v == "yesterday": return jst_today() - dt.timedelta(days=1)
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
    retry = Retry(total=4, connect=4, read=4, backoff_factor=0.8,
                  status_forcelist=(429,500,502,503,504),
                  allowed_methods=("GET",), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "boatrace-analysis/1.1"})
    return session

def cache_path(kind: str, d: dt.date) -> Path:
    return CACHE_DIR / kind / d.strftime("%Y") / f"{ymd(d)}.json"

def should_fetch_remote(d: dt.date, path: Path, *, force_refresh_all: bool, refresh_cutoff_date: dt.date) -> bool:
    if force_refresh_all: return True
    if not path.exists(): return True
    return d >= refresh_cutoff_date

def read_cached_json(path: Path) -> Optional[Any]:
    if not path.exists(): return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] cache read failed: {path}: {exc}", file=sys.stderr)
        return None

def write_json_if_changed(path: Path, data: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    old_text = path.read_text(encoding="utf-8") if path.exists() else None
    if old_text == new_text: return False
    path.write_text(new_text, encoding="utf-8")
    return True

def fetch_json(session: requests.Session, kind: str, d: dt.date, *, force_refresh_all: bool, refresh_cutoff_date: dt.date, sleep_sec: float=0.15) -> Optional[Any]:
    path = cache_path(kind, d)
    if not should_fetch_remote(d, path, force_refresh_all=force_refresh_all, refresh_cutoff_date=refresh_cutoff_date):
        return read_cached_json(path)

    url = BASE_URLS[kind].format(year=d.strftime("%Y"), ymd=ymd(d))
    try:
        r = session.get(url, timeout=30)
        if r.status_code == 404:
            cached = read_cached_json(path)
            if cached is not None:
                print(f"[WARN] remote 404 but using cache: {kind} {ymd(d)}", file=sys.stderr)
            return cached
        r.raise_for_status()
        data = r.json()
        if write_json_if_changed(path, data):
            print(f"[INFO] cache updated: {kind} {ymd(d)}")
        if sleep_sec: time.sleep(sleep_sec)
        return data
    except Exception as exc:
        cached = read_cached_json(path)
        if cached is not None:
            print(f"[WARN] fetch failed, using cache: {kind} {ymd(d)}: {exc}", file=sys.stderr)
            return cached
        print(f"[WARN] fetch failed, no cache: {kind} {ymd(d)}: {exc}", file=sys.stderr)
        return None

def as_race_list(data: Any) -> List[Dict[str, Any]]:
    if data is None: return []
    if isinstance(data, list): return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("races","data","results","programs","previews"):
            if isinstance(data.get(key), list): return [x for x in data[key] if isinstance(x, dict)]
        out = []
        for v in data.values():
            if isinstance(v, dict): out.append(v)
            elif isinstance(v, list): out.extend([x for x in v if isinstance(x, dict)])
        return out
    return []

def to_int(value: Any, default: Optional[int]=None) -> Optional[int]:
    if value is None or value == "": return default
    try:
        if isinstance(value, str): value = value.replace(",", "")
        return int(float(value))
    except Exception: return default

def to_float(value: Any, default: Optional[float]=None) -> Optional[float]:
    if value is None or value == "": return default
    try:
        if isinstance(value, str): value = value.replace(",", "").replace("F", "-").replace("L", "")
        return float(value)
    except Exception: return default

def normalize_exhibition_time(value: Any) -> Optional[float]:
    v = to_float(value)
    if v is None: return None
    return round(v / 100.0, 2) if v > 100 else v

def race_key(race: Dict[str, Any]) -> Tuple[str,int,int]:
    return (str(race.get("date")), to_int(race.get("stadium_number"), -1) or -1, to_int(race.get("number"), -1) or -1)

def boat_map(race: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    if not race: return {}
    boats = race.get("boats") or []
    if not isinstance(boats, list): return {}
    out = {}
    for b in boats:
        if not isinstance(b, dict): continue
        no = to_int(b.get("racer_boat_number"))
        if no is not None: out[no] = b
    return out

def get_trifecta_payout(result_race: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    trifecta = (result_race.get("payouts") or {}).get("trifecta") or []
    if not isinstance(trifecta, list) or not trifecta: return None, None
    first = trifecta[0]
    if not isinstance(first, dict): return None, None
    comb = first.get("combination")
    amount = to_int(first.get("amount"))
    return (str(comb) if comb else None), amount

def parse_combination(combination: Optional[str]) -> List[Optional[int]]:
    if not combination: return [None,None,None]
    s = str(combination).strip().replace(" ", "")
    for sep in ("-","=","－","ｰ"):
        if sep in s:
            parts = s.split(sep); break
    else:
        parts = list(s)
    nums = [to_int(p) for p in parts[:3]]
    while len(nums) < 3: nums.append(None)
    return nums

def class_label(raw: Any) -> Optional[str]:
    n = to_int(raw)
    return None if n is None else CLASS_MAP.get(n, str(n))

def add_program_preview_features(row, prefix, boat_no, program_boats, preview_boats):
    pb, vb = program_boats.get(boat_no, {}), preview_boats.get(boat_no, {})
    fields = {
        "racer_number": pb.get("racer_number"), "racer_name": pb.get("racer_name"),
        "class_number_raw": pb.get("racer_class_number"), "class_label_est": class_label(pb.get("racer_class_number")),
        "branch_number": pb.get("racer_branch_number"), "birthplace_number": pb.get("racer_birthplace_number"),
        "age": pb.get("racer_age"), "weight_program": pb.get("racer_weight"),
        "flying_count": pb.get("racer_flying_count"), "late_count": pb.get("racer_late_count"),
        "average_start_timing": pb.get("racer_average_start_timing"),
        "national_top1": pb.get("racer_national_top_1_percent"), "national_top2": pb.get("racer_national_top_2_percent"), "national_top3": pb.get("racer_national_top_3_percent"),
        "local_top1": pb.get("racer_local_top_1_percent"), "local_top2": pb.get("racer_local_top_2_percent"), "local_top3": pb.get("racer_local_top_3_percent"),
        "motor_no": pb.get("racer_assigned_motor_number"), "motor_top2": pb.get("racer_assigned_motor_top_2_percent"), "motor_top3": pb.get("racer_assigned_motor_top_3_percent"),
        "assigned_boat_no": pb.get("racer_assigned_boat_number"), "boat_top2": pb.get("racer_assigned_boat_top_2_percent"), "boat_top3": pb.get("racer_assigned_boat_top_3_percent"),
        "preview_course_no": vb.get("racer_course_number"), "preview_start_timing": vb.get("racer_start_timing"),
        "preview_weight": vb.get("racer_weight"), "weight_adjustment": vb.get("racer_weight_adjustment"),
        "exhibition_time_raw": vb.get("racer_exhibition_time"), "exhibition_time": normalize_exhibition_time(vb.get("racer_exhibition_time")),
        "tilt": vb.get("racer_tilt_adjustment"),
    }
    for k, v in fields.items(): row[f"{prefix}_{k}"] = v

def make_flat_row(result_race, program_race, preview_race, threshold):
    date, stadium_no, race_no = race_key(result_race)
    comb, payout = get_trifecta_payout(result_race)
    order = parse_combination(comb)
    rbm, pbm, vbm = boat_map(result_race), boat_map(program_race), boat_map(preview_race)

    row = {
        "date": date, "stadium_number": stadium_no, "stadium_name": STADIUM_MAP.get(stadium_no, str(stadium_no)), "race_no": race_no,
        "closed_at": program_race.get("closed_at") if program_race else None,
        "day_label": program_race.get("day_label") if program_race else None,
        "grade_label": program_race.get("grade_label") if program_race else None,
        "grade_number": program_race.get("grade_number") if program_race else None,
        "title": program_race.get("title") if program_race else None,
        "has_program": bool(program_race), "has_preview": bool(preview_race),
        "trifecta_combination": comb, "trifecta_payout": payout,
        "net_profit_100yen": payout - 100 if payout is not None else None,
        "is_high_payout": bool(payout is not None and payout >= threshold),
        "technique_number": result_race.get("technique_number"),
        "result_wind_speed": result_race.get("wind_speed"),
        "result_wave_height": result_race.get("wave_height"),
        "result_weather_number": result_race.get("weather_number"),
        "result_air_temperature": result_race.get("air_temperature"),
        "result_water_temperature": result_race.get("water_temperature"),
    }

    courses, starts, classes = [], [], []
    for pos, boat_no in enumerate(order, 1):
        prefix = f"place{pos}"
        row[f"{prefix}_boat_no"] = boat_no
        if boat_no is None: continue
        rb = rbm.get(boat_no, {})
        row[f"{prefix}_course_no_result"] = rb.get("racer_course_number")
        row[f"{prefix}_start_timing_result"] = rb.get("racer_start_timing")
        row[f"{prefix}_place_number_result"] = rb.get("racer_place_number")
        row[f"{prefix}_racer_number_result"] = rb.get("racer_number")
        row[f"{prefix}_racer_name_result"] = rb.get("racer_name")
        add_program_preview_features(row, prefix, boat_no, pbm, vbm)
        courses.append(str(rb.get("racer_course_number")) if rb.get("racer_course_number") is not None else "")
        starts.append(str(rb.get("racer_start_timing")) if rb.get("racer_start_timing") is not None else "")
        classes.append(str(row.get(f"{prefix}_class_label_est") or ""))

    for boat_no in range(1, 7):
        prefix = f"boat{boat_no}"
        rb = rbm.get(boat_no, {})
        row[f"{prefix}_boat_no"] = boat_no
        row[f"{prefix}_place_result"] = rb.get("racer_place_number")
        row[f"{prefix}_course_no_result"] = rb.get("racer_course_number")
        row[f"{prefix}_start_timing_result"] = rb.get("racer_start_timing")
        add_program_preview_features(row, prefix, boat_no, pbm, vbm)

    row["boat_order"] = "-".join(str(x) for x in order if x is not None)
    row["course_order_result"] = "-".join(courses)
    row["start_order_result"] = "-".join(starts)
    row["class_order_est"] = "-".join(classes)
    return row

def load_joined(start_date, end_date, threshold, *, refresh_recent_days, force_refresh_all):
    session = make_session()
    rows = []
    refresh_cutoff_date = end_date - dt.timedelta(days=max(refresh_recent_days - 1, 0))
    for d in tqdm(list(daterange(start_date, end_date)), desc="fetch/analyze"):
        kw = {"force_refresh_all": force_refresh_all, "refresh_cutoff_date": refresh_cutoff_date}
        results = as_race_list(fetch_json(session, "results", d, **kw))
        programs = as_race_list(fetch_json(session, "programs", d, **kw))
        previews = as_race_list(fetch_json(session, "previews", d, **kw))
        pmap, vmap = {race_key(r): r for r in programs}, {race_key(r): r for r in previews}
        for rr in results:
            rows.append(make_flat_row(rr, pmap.get(race_key(rr)), vmap.get(race_key(rr)), threshold))
    return pd.DataFrame(rows)

def summarize(df):
    high = df[df["is_high_payout"] == True].copy()
    summaries = {}
    if high.empty: return summaries
    summaries["pattern_by_boat_order"] = high.groupby("boat_order", dropna=False).agg(races=("boat_order","size"), avg_payout=("trifecta_payout","mean"), max_payout=("trifecta_payout","max"), avg_net_profit=("net_profit_100yen","mean")).reset_index().sort_values(["races","avg_payout"], ascending=[False,False])
    summaries["pattern_by_course_order"] = high.groupby("course_order_result", dropna=False).agg(races=("course_order_result","size"), avg_payout=("trifecta_payout","mean"), max_payout=("trifecta_payout","max")).reset_index().sort_values(["races","avg_payout"], ascending=[False,False])
    summaries["winner_features_summary"] = high.groupby(["place1_boat_no","place1_class_label_est"], dropna=False).agg(races=("trifecta_payout","size"), avg_payout=("trifecta_payout","mean"), max_payout=("trifecta_payout","max"), avg_motor_top2=("place1_motor_top2","mean"), avg_motor_top3=("place1_motor_top3","mean"), avg_avg_st=("place1_average_start_timing","mean"), avg_age=("place1_age","mean"), avg_weight=("place1_weight_program","mean")).reset_index().sort_values(["races","avg_payout"], ascending=[False,False])
    summaries["stadium_high_payout_summary"] = high.groupby(["stadium_number","stadium_name"], dropna=False).agg(high_payout_races=("trifecta_payout","size"), avg_payout=("trifecta_payout","mean"), max_payout=("trifecta_payout","max")).reset_index().sort_values(["high_payout_races","avg_payout"], ascending=[False,False])
    return summaries

def write_outputs(df, threshold, start_date, end_date, summaries, out_dir, refresh_recent_days, force_refresh_all):
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "all_races_flat.csv", index=False, encoding="utf-8-sig")
    df[df["is_high_payout"] == True].to_csv(out_dir / f"high_payout_{threshold}_over.csv", index=False, encoding="utf-8-sig")
    for name, sdf in summaries.items(): sdf.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    with sqlite3.connect(out_dir / "boatrace_analysis.sqlite") as con:
        df.to_sql("all_races_flat", con, if_exists="replace", index=False)
        df[df["is_high_payout"] == True].to_sql(f"high_payout_{threshold}_over", con, if_exists="replace", index=False)

    high = df[df["is_high_payout"] == True]
    total, high_count = len(df), len(high)
    rate = high_count / total * 100 if total else 0
    def top_lines(name, key_col):
        sdf = summaries.get(name)
        if sdf is None or sdf.empty: return ["- データなし"]
        return [f"- {r[key_col]}: {int(r['races'])}件 / 平均払戻 {r['avg_payout']:.0f}円 / 最大 {int(r['max_payout'])}円" for _, r in sdf.head(10).iterrows()]
    md = [
        "# 競艇 高配当反省ルール", "",
        "## 集計条件", "",
        f"- 対象期間: {start_date.isoformat()} 〜 {end_date.isoformat()}",
        f"- 抽出条件: 3連単払戻 {threshold:,}円以上",
        f"- 全レース数: {total:,}件",
        f"- 高配当レース数: {high_count:,}件",
        f"- 高配当率: {rate:.2f}%",
        f"- 日次更新方針: 未取得日は取得、直近{refresh_recent_days}日分は再取得して修正版があれば上書き",
        f"- 全件再取得: {'あり' if force_refresh_all else 'なし'}",
        "", "## 艇番パターン上位", *top_lines("pattern_by_boat_order", "boat_order"),
        "", "## 実進入コースパターン上位", *top_lines("pattern_by_course_order", "course_order_result"),
        "", "## 次回予想の強制チェック",
        "- 2号艇の差し残り・2着・3着を、機力だけで安易に切らない。",
        "- 4カド攻めは、攻めた4号艇自身の2着・3着残りまで評価する。",
        "- 5号艇は展開差し・まくり差し・2着浮上・3着残りを必ず比較する。",
        "- 6号艇はA1/A2、平均ST良、展示良、良モーターなら頭・2着・3着すべてを見る。",
        "- 1号艇は逃げ固定にせず、2着残り・飛びの条件を確認する。",
        "- 過去傾向は補助情報であり、今回レースの公式直前情報・展示・オッズを最優先する。",
    ]
    (out_dir / "high_payout_lesson_rules.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / "next_prediction_prompt.md").write_text(f"""# 競艇予想依頼プロンプト

まずGitHubのPublicリポジトリにある以下のファイルを確認してください。

- `output/high_payout_lesson_rules.md`
- `output/high_payout_{threshold}_over.csv`
- `output/pattern_by_boat_order.csv`
- `output/pattern_by_course_order.csv`
- `output/winner_features_summary.csv`
- `output/stadium_high_payout_summary.csv`

これらは2026年4月以降の日次更新済みの競艇高配当分析結果です。
ただし過去傾向は補助情報です。今回レースでは必ずBOAT RACE公式・競艇場公式の出走表、直前情報、展示、進入、オッズを最優先してください。

## 入力条件

- 日付：
- 場：
- R：
- 予算：
- 目標純利益：

## 必須
3連単、3連複、2連単、2連複を券種別に提示し、最後に実際に買う券種を1つだけ選んでください。
根拠が弱い、安い、軸が曖昧な場合は見送りにしてください。
""", encoding="utf-8")

def validate(df, start_date, end_date):
    if df.empty: raise RuntimeError("No races were loaded. Check network/API availability.")
    missing = [c for c in ["date","stadium_number","race_no","trifecta_combination","trifecta_payout"] if c not in df.columns]
    if missing: raise RuntimeError(f"Missing required columns: {missing}")

def run(start_date, end_date, threshold, *, refresh_recent_days, force_refresh_all, out_dir=OUT_DIR):
    if start_date > end_date: raise ValueError("start_date must be <= end_date")
    df = load_joined(start_date, end_date, threshold, refresh_recent_days=refresh_recent_days, force_refresh_all=force_refresh_all)
    validate(df, start_date, end_date)
    summaries = summarize(df)
    write_outputs(df, threshold, start_date, end_date, summaries, out_dir, refresh_recent_days, force_refresh_all)
    return df

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default="yesterday")
    parser.add_argument("--threshold", default=DEFAULT_THRESHOLD, type=int)
    parser.add_argument("--refresh-recent-days", default=DEFAULT_REFRESH_RECENT_DAYS, type=int)
    parser.add_argument("--force-refresh-all", action="store_true")
    args = parser.parse_args()
    df = run(parse_date(args.start_date), parse_date(args.end_date), args.threshold, refresh_recent_days=args.refresh_recent_days, force_refresh_all=args.force_refresh_all)
    print(f"DONE: all={len(df):,}, high_payout={int(df['is_high_payout'].sum()):,}, output={OUT_DIR.resolve()}")

if __name__ == "__main__":
    main()
