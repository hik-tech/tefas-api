import os
import time
import threading
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi import requests


app = FastAPI(title="TEFAS API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


TEFAS_URL = (
    "https://www.tefas.gov.tr/api/funds/"
    "fonFiyatBilgiGetir"
)

CACHE_SECONDS = 21600  # 6 saat

cache = {}

cache_lock = threading.Lock()


def parse_price(value):
    if value is None:
        return None

    text = str(value).strip()

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    return float(text)


def parse_date(value):
    text = str(value)[:10]

    return datetime.strptime(
        text,
        "%Y-%m-%d"
    )


def get_tefas_data(fund_code):

    fund_code = fund_code.upper().strip()

    now = time.time()

    # ------------------------------------------------------
    # CACHE
    # ------------------------------------------------------

    with cache_lock:

        cached = cache.get(fund_code)

        if cached:
            cached_time, cached_data = cached

            if now - cached_time < CACHE_SECONDS:
                return cached_data


    # ------------------------------------------------------
    # TEFAS İSTEĞİ
    # ------------------------------------------------------

    headers = {

        "Accept": "application/json, text/plain, */*",

        "Content-Type": "application/json",

        "Origin":
            "https://www.tefas.gov.tr",

        "Referer":
            "https://www.tefas.gov.tr/tr/fon-verileri",

        "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"

    }


    payload = {

        "fonKodu": fund_code,

        "dil": "TR",

        "periyod": 60

    }


    try:

        response = requests.post(
            TEFAS_URL,
            headers=headers,
            json=payload,
            impersonate="chrome",
            timeout=30
        )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=f"TEFAS bağlantı hatası: {exc}"
        )


    if response.status_code != 200:

        raise HTTPException(
            status_code=502,
            detail=(
                f"TEFAS HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        )


    try:

        result = response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail=(
                "TEFAS geçerli JSON döndürmedi: "
                + response.text[:300]
            )
        )


    if result.get("errorMessage"):

        raise HTTPException(
            status_code=502,
            detail=result["errorMessage"]
        )


    rows = result.get("resultList")


    if not rows or not isinstance(rows, list):

        raise HTTPException(
            status_code=404,
            detail=f"{fund_code} için veri bulunamadı."
        )


    # ------------------------------------------------------
    # VERİLERİ HAZIRLA
    # ------------------------------------------------------

    data = []


    for row in rows:

        try:

            date = parse_date(row["tarih"])

            price = parse_price(row["fiyat"])

            data.append(
                {
                    "date": date,
                    "price": price
                }
            )

        except Exception:

            continue


    if not data:

        raise HTTPException(
            status_code=404,
            detail=f"{fund_code} için geçerli fiyat verisi yok."
        )


    data.sort(
        key=lambda x: x["date"]
    )


    latest = data[-1]


    # ------------------------------------------------------
    # YARDIMCI FONKSİYONLAR
    # ------------------------------------------------------

    def find_before(target):

        for item in reversed(data):

            if item["date"] <= target:
                return item["price"]

        return data[0]["price"]


    def return_percent(old_price):

        if not old_price:
            return None

        return (
            (latest["price"] - old_price)
            / old_price
            * 100
        )


    def add_months(date, months):

        year = date.year
        month = date.month + months

        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1

        import calendar

        day = min(
            date.day,
            calendar.monthrange(year, month)[1]
        )

        return datetime(
            year,
            month,
            day
        )


    # ------------------------------------------------------
    # DÖNEMLER
    # ------------------------------------------------------

    from datetime import timedelta


    one_day = latest["date"] - timedelta(days=1)

    one_week = latest["date"] - timedelta(days=7)


    one_month = add_months(
        latest["date"],
        -1
    )


    three_month = add_months(
        latest["date"],
        -3
    )


    six_month = add_months(
        latest["date"],
        -6
    )


    one_year = add_months(
        latest["date"],
        -12
    )


    three_year = add_months(
        latest["date"],
        -36
    )


    five_year = add_months(
        latest["date"],
        -60
    )


    # ------------------------------------------------------
    # YILBAŞI
    # ------------------------------------------------------

    year_start_price = None


    for item in data:

        if item["date"].year == latest["date"].year:

            year_start_price = item["price"]

            break


    # ------------------------------------------------------
    # SONUÇ
    # ------------------------------------------------------

    result = {

        "fonKodu":
            fund_code,

        "fiyat":
            latest["price"],

        "tarih":
            latest["date"].strftime(
                "%Y-%m-%d"
            ),

        "gunluk":
            return_percent(
                find_before(one_day)
            ),

        "haftalik":
            return_percent(
                find_before(one_week)
            ),

        "aylik":
            return_percent(
                find_before(one_month)
            ),

        "3aylik":
            return_percent(
                find_before(three_month)
            ),

        "6aylik":
            return_percent(
                find_before(six_month)
            ),

        "1yillik":
            return_percent(
                find_before(one_year)
            ),

        "3yillik":
            return_percent(
                find_before(three_year)
            ),

        "5yillik":
            return_percent(
                find_before(five_year)
            ),

        "yilbasi":
            return_percent(
                year_start_price
            )

    }


    # ------------------------------------------------------
    # CACHE
    # ------------------------------------------------------

    with cache_lock:

        cache[fund_code] = (
            time.time(),
            result
        )


    return result


@app.get("/")
def root():

    return {

        "status": "OK",

        "service":
            "TEFAS API",

        "usage":
            "/fund/GSP"

    }


@app.get("/health")
def health():

    return {
        "status": "OK"
    }


@app.get("/fund/{fund_code}")
def fund(fund_code: str):

    return get_tefas_data(
        fund_code
    )
