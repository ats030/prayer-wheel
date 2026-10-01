"""愛知県西部の生活向け天気通知。予報は既存アプリ、警報は気象庁の発表を使う。"""

import argparse
import fcntl
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
STATE_DIR = Path.home() / "data/weather-notify"
FORECAST_URL = "http://127.0.0.1:8520/api/forecast?area=230010"
VIEW_URL = "http://ubuntu-server-app:8520/?area=230010"
WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/230000.json"
NAMES = {
    "02": "暴風雪警報", "03": "大雨警報", "04": "洪水警報", "05": "暴風警報",
    "06": "大雪警報", "07": "波浪警報", "08": "高潮警報",
    "32": "暴風雪特別警報", "33": "大雨特別警報", "35": "暴風特別警報",
    "36": "大雪特別警報", "37": "波浪特別警報", "38": "高潮特別警報",
}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "weather-notify/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def load_state(name):
    try:
        return json.loads((STATE_DIR / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_state(name, data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temp, STATE_DIR / name)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def morning(now):
    data = fetch_json(FORECAST_URL)
    if data["area"]["code"] != "230010":
        raise ValueError("予報区域が一致しない")
    today = now.date().isoformat()
    day = next(d for d in data["days"] if d["date"] == today)
    reported = datetime.fromisoformat(data["report_datetime"])
    if reported.tzinfo is None or now - reported > timedelta(hours=24):
        raise ValueError("予報の発表日時が古い")
    previous = load_state("morning.json")
    high = day["temp_max"]
    delta = None
    if previous.get("date") == (now.date() - timedelta(days=1)).isoformat():
        if high is not None and previous.get("temp_max") is not None:
            delta = high - previous["temp_max"]
    pops = [p["value"] for p in day["pops"] if p["value"] is not None]
    wet = bool(pops) and max(pops) >= 50
    changed = delta is not None and abs(delta) >= 5
    advisory = [a["name"] for a in data["alerts"] if a["level"] == "advisory"]
    lines = []
    if wet or changed or not previous or advisory:
        lines = ["**愛知県西部の天気**", f"- {day['weather']} / 最高 {high if high is not None else '不明'}℃・最低 {day['temp_min'] if day['temp_min'] is not None else '不明'}℃"]
        if wet:
            lines.append(f"- 傘の目安：当日の降水確率は最大 {max(pops)}%")
        if changed:
            lines.append(f"- 最高気温は前日分の予報との差 {delta:+g}℃（実測値との差ではありません）")
        if advisory:
            lines.append("- 発表中の注意報：" + "、".join(advisory))
        lines += [f"- 予報発表：{data['report_datetime']}", f"- 出典：気象庁ホームページ / <{VIEW_URL}>"]
    return "\n".join(lines), {"date": today, "temp_max": high}


def warning_codes(data):
    if not data.get("reportDatetime"):
        raise ValueError("警報データの発表日時がない")
    for group in data["areaTypes"]:
        for area in group["areas"]:
            if area["code"] == "230010":
                warnings = area["warnings"]
                if not isinstance(warnings, list):
                    raise ValueError("警報一覧の形式が不正")
                return sorted({w["code"] for w in warnings
                               if w["code"] in NAMES and w["status"] != "解除"})
    raise ValueError("警報データに愛知県西部がない")


def check_warnings(send, dry_run=False):
    data = fetch_json(WARNING_URL)
    current = warning_codes(data)
    previous = load_state("warnings.json")
    added = sorted(set(current) - set(previous.get("codes", [])))
    if added:
        message = "\n".join(["**気象庁発表：愛知県西部の警報**",
                              "、".join(NAMES[c] for c in added),
                              f"発表：{data['reportDatetime']}",
                              "愛知県西部の区域単位です。市区町村別の対象は気象庁で確認してください。",
                              f"出典：気象庁ホームページ <https://www.jma.go.jp/bosai/warning/#area_type=offices&area_code=230000>",
                              f"天気アプリ：<{VIEW_URL}>"])
        if dry_run:
            print(message)
        else:
            send(message)
    if not dry_run:
        save_state("warnings.json", {"codes": current, "report_datetime": data["reportDatetime"]})
    return bool(added)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # 同じWebhook・メンション無効化・送信方法を既存ダイジェストと共有する。
    import importlib.util
    spec = importlib.util.spec_from_file_location("digest", Path(__file__).with_name("morning-digest.py"))
    digest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(digest)

    def send(text):
        url = digest.webhook_url()
        if not url:
            raise ValueError("DISCORD_WEBHOOK_URL が未設定")
        digest.post_to_discord(url, text)

    try:
        if args.dry_run:
            check_warnings(send, True)
        else:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with (STATE_DIR / "warnings.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                check_warnings(send)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Webhook URL を含む例外本文はログへ出さない。
        print(f"天気通知失敗：{type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
