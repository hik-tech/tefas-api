from datetime import datetime, timedelta
import calendar
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from tefasmak import fon_5y_fiyat


app = FastAPI(title="TEFAS API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ==========================================================
# CACHE
# ==========================================================

CACHE_SECONDS = 21600  # 6 saat

cache = {}
cache_lock = threading.Lock()


# ==========================================================
# TARİH YARDIMCILARI
# ==========================================================

def add_months(date, months):

    year = date.year
    month = date.month + months

    year += (month - 1) // 12
    month = ((month - 1) % 12) + 1

    day = min(
        date.day,
        calendar.monthrange(year, month)[1]
    )

    return datetime(
        year,
        month,
        day
    )


def parse_date(value):

    if isinstance(value, datetime):
        return value

    text = str(value).strip()

    # 2026-08-24
    if len(text) >= 10:
        try:
            return datetime.strptime(
                text[:10],
                "%Y-%m-%d"
            )
        except Exception:
            pass

    # 24.08.2026
    try:
        return datetime.strptime(
            text,
            "%d.%m.%Y"
        )
    except Exception:
        pass

    raise ValueError(
        f"Tarih çözümlenemedi: {value}"
    )


# ==========================================================
# TEFAS VERİSİ
# ==========================================================

def load_fund(fund_code):

    fund_code = (
        str(fund_code)
        .strip()
        .upper()
    )

    # ------------------------------------------------------
    # CACHE
    # ------------------------------------------------------

    now = time.time()

    with cache_lock:

        cached = cache.get(fund_code)

        if cached:

            cached_time, cached_data = cached

            if now - cached_time < CACHE_SECONDS:

                return cached_data


    # ------------------------------------------------------
    # TEFAS
    # ------------------------------------------------------

    try:

        rows = fon_5y_fiyat(
            fund_code
        )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "TEFAS verisi alınamadı: "
                + str(exc)
            )
        )


    if not rows:

        raise HTTPException(
            status_code=404,
            detail=(
                f"{fund_code} için TEFAS verisi bulunamadı."
            )
        )


    # ------------------------------------------------------
    # VERİLERİ HAZIRLA
    # ------------------------------------------------------

    data = []


    for row in rows:

        try:

            raw_date = (
                row.get("tarih")
                if isinstance(row, dict)
                else None
            )

            raw_price = (
                row.get("fiyat")
                if isinstance(row, dict)
                else None
            )

            if raw_date is None:
                continue

            if raw_price is None:
                continue


            date = parse_date(
                raw_date
            )


            if isinstance(raw_price, str):

                price_text = (
                    raw_price
                    .strip()
                    .replace(",", ".")
                )

                price = float(
                    price_text
                )

            else:

                price = float(
                    raw_price
                )


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
            detail=(
                f"{fund_code} için geçerli fiyat verisi bulunamadı."
            )
        )


    # ------------------------------------------------------
    # TARİHE GÖRE SIRALA
    # ------------------------------------------------------

    data.sort(
        key=lambda x: x["date"]
    )


    latest = data[-1]


    # ------------------------------------------------------
    # HEDEF TARİHTEN ÖNCEKİ FİYAT
    # ------------------------------------------------------

    def find_before(target):

        for item in reversed(data):

            if item["date"] <= target:

                return item["price"]


        return data[0]["price"]


    # ------------------------------------------------------
    # GETİRİ
    # ------------------------------------------------------

    def calc(old_price):

        if (
            old_price is None
            or old_price == 0
        ):

            return None


        return (
            (latest["price"] - old_price)
            / old_price
            * 100
        )


    # ------------------------------------------------------
    # DÖNEMLER
    # ------------------------------------------------------

    one_day = (
        latest["date"]
        - timedelta(days=1)
    )


    one_week = (
        latest["date"]
        - timedelta(days=7)
    )


    one_month = add_months(
        latest["date"],
        -1
    )


    three_months = add_months(
        latest["date"],
        -3
    )


    six_months = add_months(
        latest["date"],
        -6
    )


    one_year = add_months(
        latest["date"],
        -12
    )


    three_years = add_months(
        latest["date"],
        -36
    )


    five_years = add_months(
        latest["date"],
        -60
    )


    # ------------------------------------------------------
    # YILBAŞI
    # ------------------------------------------------------

    year_start_price = None


    for item in data:

        if (
            item["date"].year
            == latest["date"].year
        ):

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
            calc(
                find_before(
                    one_day
                )
            ),

        "haftalik":
            calc(
                find_before(
                    one_week
                )
            ),

        "aylik":
            calc(
                find_before(
                    one_month
                )
            ),

        "3aylik":
            calc(
                find_before(
                    three_months
                )
            ),

        "6aylik":
            calc(
                find_before(
                    six_months
                )
            ),

        "1yillik":
            calc(
                find_before(
                    one_year
                )
            ),

        "3yillik":
            calc(
                find_before(
                    three_years
                )
            ),

        "5yillik":
            calc(
                find_before(
                    five_years
                )
            ),

        "yilbasi":
            calc(
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


# ==========================================================
# API ENDPOINTLERİ
# ==========================================================

@app.get("/")
def root():

    return {
        "status": "OK",
        "service": "TEFAS API",
        "usage": "/fund/GSP"
    }


@app.get("/health")
def health():

    return {
        "status": "OK"
    }


@app.get("/fund/{fund_code}")
def fund(fund_code: str):

    return load_fund(
        fund_code
    )
