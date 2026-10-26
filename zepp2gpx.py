#!/usr/bin/env python3
"""Скачивает тренировки Amazfit T-Rex 2 из облака Zepp и сохраняет в GPX.

Не требует приложения Zepp, работает на FreeBSD (нужны python3 и requests).

Использование:
  ZEPP_EMAIL='me@mail.com' ZEPP_PASS='secret' ./zepp2gpx.py -o tracks
  ZEPP_TOKEN='...' ./zepp2gpx.py -o tracks      # готовый app_token, без логина
  ./zepp2gpx.py -o tracks --debug               # сохранять сырой JSON

Токен кэшируется в ~/.cache/zepp2gpx_token (права 600), чтобы не логиниться
повторно и не ловить HTTP 429. Если токен протух, он сбрасывается автоматически.
"""
import argparse
import json
import os
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests

API_USER = "https://api-user.huami.com"
ACCOUNT = "https://account.huami.com"
# Региональный хост; при пустых данных попробуйте api-mifit-de2 / -us2 / -sg2
_HOSTS = [
    "https://api-mifit.huami.com",
    "https://api-mifit-de2.huami.com",
    "https://api-mifit-de2.zepp.com",
    "https://api-mifit-us2.huami.com",
    "https://api-mifit-sg2.huami.com",
]
HOSTS = [os.environ["ZEPP_API"]] if os.environ.get("ZEPP_API") else _HOSTS
API_DATA = HOSTS[0]
APPNAME = os.environ.get("ZEPP_APPNAME", "com.huami.midong")
APPPLATFORM = os.environ.get("ZEPP_PLATFORM", "android_phone")
SOURCE = "run.watch.huami.com"
UA = "Dalvik/2.1.0 (Linux; U; Android 12; Pixel 6 Build/SD1A)"
TOKEN_FILE = Path.home() / ".cache" / "zepp2gpx_token"


class AuthError(Exception):
    """Токен недействителен или истёк."""


def login(email, password):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    r = s.post(
        f"{API_USER}/registrations/{quote(email)}/tokens",
        data={
            "client_id": "HuaMi",
            "password": password,
            "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
            "token": "access",
        },
        allow_redirects=False,
        timeout=30,
    )
    if r.status_code == 429:
        sys.exit("HTTP 429: слишком много попыток входа. Подождите 30-60 минут "
                 f"(Retry-After: {r.headers.get('Retry-After', 'не указан')}), "
                 "отключите VPN и не повторяйте запуск.")
    loc = r.headers.get("Location", "")
    code = parse_qs(urlparse(loc).query).get("access", [None])[0]
    if not code:
        sys.exit(f"Логин не удался: HTTP {r.status_code}, Location={loc!r}, "
                 f"тело={r.text[:200]!r}\n"
                 "Возможно неверный пароль или аккаунт без пароля "
                 "(вход через Google/Apple не поддерживается).")

    r = s.post(
        f"{ACCOUNT}/v2/client/login",
        data={
            "app_name": "com.xiaomi.hm.health",
            "app_version": "6.3.5",
            "code": code,
            "country_code": "US",
            "device_id": str(uuid.uuid4()),
            "device_model": "android_phone",
            "grant_type": "access_token",
            "third_name": "huami",
            "allow_registration": "false",
            "source": "com.xiaomi.hm.health:6.3.5:50818",
            "lang": "en",
        },
        timeout=30,
    )
    if r.status_code == 429:
        sys.exit("HTTP 429 на втором шаге входа, подождите и повторите позже.")
    try:
        info = r.json().get("token_info")
    except ValueError:
        info = None
    if not info:
        sys.exit(f"Не получен app_token: HTTP {r.status_code}, {r.text[:300]}")
    return info["app_token"]


def get_token(force_login=False):
    """Порядок: ZEPP_TOKEN -> кэш-файл -> логин по email/паролю."""
    if not force_login:
        tok = os.environ.get("ZEPP_TOKEN")
        if tok:
            return tok
        if TOKEN_FILE.exists():
            tok = TOKEN_FILE.read_text().strip()
            if tok:
                return tok
    email, pw = os.environ.get("ZEPP_EMAIL"), os.environ.get("ZEPP_PASS")
    if not email or not pw:
        sys.exit("Нет токена. Задайте ZEPP_EMAIL и ZEPP_PASS (или ZEPP_TOKEN).")
    tok = login(email, pw)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(tok)
    TOKEN_FILE.chmod(0o600)
    return tok


def drop_cached_token():
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass


def api_get(token, path, **params):
    r = requests.get(
        f"{API_DATA}{path}",
        params=params,
        headers={"apptoken": token, "appname": APPNAME,
                 "appplatform": APPPLATFORM, "User-Agent": UA},
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise AuthError(f"HTTP {r.status_code}")
    if r.status_code == 429:
        sys.exit("HTTP 429 от API данных: подождите и повторите позже.")
    r.raise_for_status()
    j = r.json()
    if j.get("code") not in (1, None):
        raise AuthError(f"API code={j.get('code')}: {str(j)[:200]}")
    return j.get("data", j)


def pick_host(token):
    """Перебирает региональные хосты, пока один не ответит на history."""
    global API_DATA
    errors = []
    for h in HOSTS:
        API_DATA = h
        try:
            api_get(token, "/v1/sport/run/history.json", source=SOURCE)
            print(f"API хост: {h}")
            return
        except AuthError as e:
            errors.append(f"{h}: auth {e}")
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{h}: {e}")
    sys.exit("Ни один хост не подошёл:\n  " + "\n  ".join(errors) +
             "\nЗадайте ZEPP_API вручную или пришлите вывод.")


def list_workouts(token):
    out, cursor = [], None
    while True:
        params = {"source": SOURCE}
        if cursor:
            params["from"] = cursor
        data = api_get(token, "/v1/sport/run/history.json", **params)
        out += data.get("summary", [])
        if not data.get("next") or data["next"] == -1:
            return out
        cursor = data["next"]


def parse_points(detail, start_ts):
    """Расшифровка трека (формат проверен на реальных данных T-Rex 2):
    longitude_latitude: 'a,b;...' — ПЕРВОЕ значение это ШИРОТА, второе ДОЛГОТА
      (вопреки названию поля), первая точка абсолютная, далее приращения,
      единицы 1e-8 градуса.
    altitude: сантиметры, по одному значению на точку.
    time: интервалы в секундах между точками (первое — от начала trackid)."""
    SCALE = 1e8
    raw = detail.get("longitude_latitude") or ""
    alts = [x for x in (detail.get("altitude") or "").split(";") if x]
    deltas = [x for x in (detail.get("time") or "").split(";") if x]
    pts, lat, lon, t = [], 0, 0, start_ts
    for i, chunk in enumerate(c for c in raw.split(";") if c):
        try:
            dlat, dlon = (int(x) for x in chunk.split(",")[:2])
        except ValueError:
            continue
        try:
            t += int(deltas[i]) if i < len(deltas) else 1
        except ValueError:
            t += 1
        lat += dlat
        lon += dlon
        if lat == 0 and lon == 0:
            continue
        ele = None
        if i < len(alts):
            try:
                ele = int(alts[i].split(",")[-1]) / 100.0  # см -> м
            except ValueError:
                pass
        pts.append((lat / SCALE, lon / SCALE, ele, t))
    return pts


def write_gpx(path, name, pts):
    ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
    ns = "{http://www.topografix.com/GPX/1/1}"
    gpx = ET.Element(ns + "gpx", version="1.1", creator="zepp2gpx")
    trk = ET.SubElement(gpx, ns + "trk")
    ET.SubElement(trk, ns + "name").text = name
    seg = ET.SubElement(trk, ns + "trkseg")
    for lat, lon, ele, ts in pts:
        p = ET.SubElement(seg, ns + "trkpt", lat=f"{lat:.7f}", lon=f"{lon:.7f}")
        if ele is not None:
            ET.SubElement(p, ns + "ele").text = f"{ele:.1f}"
        ET.SubElement(p, ns + "time").text = datetime.fromtimestamp(
            ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ET.indent(gpx)
    ET.ElementTree(gpx).write(path, encoding="utf-8", xml_declaration=True)


def save_track(d, tid, out, overwrite=False):
    start = int(tid)
    stamp = datetime.fromtimestamp(start).strftime("%Y-%m-%d_%H%M%S")
    gpx_path = out / f"{stamp}_{tid}.gpx"
    if gpx_path.exists() and not overwrite:
        return
    pts = parse_points(d, start)
    if not pts:
        print(f"  {stamp}: нет GPS (тренировка в помещении?), пропуск")
        return
    write_gpx(gpx_path, f"Workout {stamp}", pts)
    print(f"  {gpx_path.name}: {len(pts)} точек")


def main():
    ap = argparse.ArgumentParser(description="Zepp -> GPX")
    ap.add_argument("-o", "--out", default="tracks")
    ap.add_argument("--debug", action="store_true", help="сохранять сырой JSON")
    ap.add_argument("--overwrite", action="store_true",
                    help="перезаписывать существующие GPX")
    ap.add_argument("--from-json", nargs="+", metavar="FILE",
                    help="не ходить в сеть: собрать GPX из локальных JSON "
                         "(например tracks/*.json)")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.from_json:
        for f in sorted(a.from_json):
            try:
                d = json.loads(Path(f).read_text(encoding="utf-8"))
                save_track(d, d["trackid"], out, overwrite=a.overwrite)
            except (OSError, ValueError, KeyError) as e:
                print(f"  {f}: пропуск ({e})")
        return

    token = get_token()
    pick_host(token)
    try:
        workouts = list_workouts(token)
    except AuthError as e:
        print(f"Токен не принят ({e}), выполняю повторный вход...")
        drop_cached_token()
        token = get_token(force_login=True)
        workouts = list_workouts(token)
    print(f"Найдено тренировок: {len(workouts)}")

    for w in workouts:
        tid = w["trackid"]
        d = api_get(token, "/v1/sport/run/detail.json",
                    trackid=tid, source=w.get("source", SOURCE))
        if a.debug:
            (out / f"{tid}.json").write_text(
                json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        save_track(d, tid, out, overwrite=a.overwrite)


if __name__ == "__main__":
    main()