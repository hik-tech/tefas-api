import threading
import time
import calendar
from datetime import datetime, timedelta

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


CACHE_SECONDS = 21600
cache = {}
cache_lock = threading.Lock()


def parse_date(value):

    text = str(value).strip()

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%d.%m.%Y",
        "%d/%m/%Y",
    ]

    for fmt in formats:

        try:
            return datetime.strptime(text, fmt)

        except ValueError:
            pass

    return datetime.fromisoformat(
        text.replace("Z", "")
    )


def parse_price(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if "," in text and "." in text:
        text = text.replace(".", "")
        text = text.replace(",", ".")

    elif "," in text:
        text = text.replace(",", ".")

    return float(text)


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


def find_before(data, target):

    for item in reversed(data):

        if item["date"] <= target:
            return item["price"]

    return data[0]["price"]


def calc(latest_price, old_price):

    if old_price in (None, 0):
        return None

    return (
        (latest_price - old_price)
        / old_price
        * 100
    )


def get_fund_data(fund_code):

    fund_code = str(
        fund_code
    ).strip().upper()


    # ------------------------------------------------------
    # CACHE
    # ------------------------------------------------------

    with cache_lock:

        item = cache.get(fund_code)

        if item:

            saved_time, saved_data = item

            if time.time() - saved_time < CACHE_SECONDS:

                return saved_data


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
                f"{fund_code} için veri bulunamadı."
            )
        )


    # ------------------------------------------------------
    # NORMALİZE ET
    # ------------------------------------------------------

    data = []

    for row in rows:

        try:

            # tefasmak normalde
            # {'tarih': ..., 'fiyat': ...}
            # döndürüyor.

            date = parse_date(
                row["tarih"]
            )

            price = parse_price(
                row["fiyat"]
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
                f"{fund_code} için "
                "geçerli fiyat verisi yok."
            )
        )


    data.sort(
        key=lambda x: x["date"]
    )


    latest = data[-1]

    latest_price = latest["price"]
    latest_date = latest["date"]


    # ------------------------------------------------------
    # HEDEF TARİHLER
    # ------------------------------------------------------

    one_day = (
        latest_date
        - timedelta(days=1)
    )

    one_week = (
        latest_date
        - timedelta(days=7)
    )

    one_month = add_months(
        latest_date,
        -1
    )

    three_months = add_months(
        latest_date,
        -3
    )

    six_months = add_months(
        latest_date,
        -6
    )

    one_year = add_months(
        latest_date,
        -12
    )

    three_years = add_months(
        latest_date,
        -36
    )

    five_years = add_months(
        latest_date,
        -60
    )


    # ------------------------------------------------------
    # YILBAŞI
    # ------------------------------------------------------

    year_start_price = None

    for item in data:

        if item["date"].year == latest_date.year:

            year_start_price = item["price"]

            break


    # ------------------------------------------------------
    # SONUÇ
    # ------------------------------------------------------

    result = {

        "fonKodu":
            fund_code,

        "fiyat":
            latest_price,

        "tarih":
            latest_date.strftime(
                "%Y-%m-%d"
            ),

        "gunluk":
            calc(
                latest_price,
                find_before(
                    data,
                    one_day
                )
            ),

        "haftalik":
            calc(
                latest_price,
                find_before(
                    data,
                    one_week
                )
            ),

        "aylik":
            calc(
                latest_price,
                find_before(
                    data,
                    one_month
                )
            ),

        "3aylik":
            calc(
                latest_price,
                find_before(
                    data,
                    three_months
                )
            ),

        "6aylik":
            calc(
                latest_price,
                find_before(
                    data,
                    six_months
                )
            ),

        "1yillik":
            calc(
                latest_price,
                find_before(
                    data,
                    one_year
                )
            ),

        "3yillik":
            calc(
                latest_price,
                find_before(
                    data,
                    three_years
                )
            ),

        "5yillik":
            calc(
                latest_price,
                find_before(
                    data,
                    five_years
                )
            ),

        "yilbasi":
            calc(
                latest_price,
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
# ENDPOINTLER
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

    return get_fund_data(
        fund_code
    )
