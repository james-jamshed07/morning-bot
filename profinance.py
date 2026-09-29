#!/usr/bin/env python3
"""Котировки ProFinance (столбец Last).

Как это работает (повторяет то, что делает сама страница):
1. GET site.jsp -> в ответе есть временный SID сеанса;
2. POST на .../htmlquotes/q со списком инструментов и этим SID;
3. в ответ приходят строки вида: 1;I=1;S=Gold;TICK=..;LP=4147.64;T=13:14:30;...

Запуск напрямую (python3 profinance.py) = диагностика: печатает, что пришло.
Только стандартная библиотека Python.
"""
import gzip
import http.cookiejar
import re
import time
import urllib.request

BASE = "https://jq.profinance.ru/html/htmlquotes/"
ORIGIN = "https://jq.profinance.ru"
UA = "Mozilla/5.0 (compatible; morning-bot/1.0)"

# Группы инструментов ровно в том виде, как их отправляет страница.
GROUPS = [
    "LP=;NCHL=;NCHPL=;S=DJIA;S=SPX;S=NASD100;S=FTSE100;S=DAX;S=CAC40;S=MMVB;S=RTST;S=USD_INDEX;S=594;",
    "LP=;NCHL=;NCHPL=;S=528;S=529;S=530;S=532;S=533;S=534;S=535;S=536;S=605",
    "LP=;NCHL=;NCHPL=;S=Gold;S=Silver;S=Platinum;S=Palladium;S=Aluminum;S=Copper;S=Nickel;S=Brent oil;S=WTI oil;S=Gas US;S=TTF USD1000;S=Urals Med",
    "LP=;NCHL=;NCHPL=;S=29;S=30;S=CNY/RUB;S=392;S=612;S=429",
    "LP=;NCHL=;NCHPL=;S=NASDAQ;S=SnP500",
    "LP=;NCHL=;NCHPL=;SP=;S=AUD/JPY;S=AUD/USD;S=EUR/AUD;S=EUR/CAD;S=EUR/CHF;S=EUR/GBP;S=EUR/JPY;S=EUR/USD;S=GBP/CHF;S=GBP/JPY;S=GBP/USD;S=USD/CAD;S=USD/CHF;S=USD/CNH;S=USD/JPY;S=USD/KZT;S=USD/MXN;S=USD/TRY",
    "LP=;NCHL=;NCHPL=;S=ERUB_FUT;S=RUB_FUT;S=CNYRUB_FUT;S=USDRUB_F;S=EURRUB_F;S=CNYRUB_F",
    "LP=;NCHL=;NCHPL=;S=DJIA_FUT;S=SP500_FUT;S=NASD100_FUT;S=NIK_FUT;S=RTS Futures;S=MIX_FUT",
]


def _open(opener, url, data=None, headers=None, timeout=10):
    h = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    return opener.open(urllib.request.Request(url, data=data, headers=h), timeout=timeout)


def _decode(raw):
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:  # noqa: BLE001
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def parse_quotes(text):
    """Разбирает строки ответа. Знак перед LP показывает направление, а не часть цены."""
    quotes = {}
    for line in text.splitlines():
        if "S=" not in line or "LP=" not in line:
            continue
        fields = {}
        for part in line.strip().split(";")[1:]:
            key, _, value = part.partition("=")
            fields[key] = value
        name = fields.get("S")
        if not name:
            continue
        try:
            price = float(fields["LP"].lstrip("+-").replace(",", "."))
        except (KeyError, ValueError):
            continue
        quotes[name] = {"price": price, "time": fields.get("T", ""), "tick": fields.get("TICK", "")}
    return quotes


def fetch_quotes(wanted=None, total_timeout=20):
    """Возвращает (quotes, info, raw_text). wanted: названия, которых дожидаемся."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    with _open(opener, BASE + "site.jsp") as resp:
        page = _decode(resp.read())
    match = re.search(r"qtable\.htm\?SID=([A-Za-z0-9]+)", page) or re.search(r"SID=([A-Za-z0-9]+)", page)
    if not match:
        raise RuntimeError("не нашёл SID на странице ProFinance")
    sid = match.group(1)

    qtable_url = f"{BASE}qtable.htm?SID={sid}&r=1000"
    try:  # как браузер: открываем вложенную страницу, чтобы сеанс «прогрелся»
        with _open(opener, qtable_url, headers={"Referer": BASE + "site.jsp"}) as resp:
            resp.read()
    except Exception:  # noqa: BLE001
        pass

    body = "\n".join(f"1;SID={sid};{g}" for g in GROUPS).encode("utf-8")
    headers = {"Content-Type": "text/plain;charset=UTF-8", "Referer": qtable_url, "Origin": ORIGIN}
    resp = _open(opener, BASE + "q", data=body, headers=headers, timeout=8)
    info = {
        "status": getattr(resp, "status", None),
        "content_type": resp.headers.get("Content-Type"),
        "content_encoding": resp.headers.get("Content-Encoding"),
    }

    buf, deadline = b"", time.time() + total_timeout
    while time.time() < deadline:
        try:
            chunk = resp.read1(8192)
        except (TimeoutError, OSError):
            break
        if not chunk:
            break
        buf += chunk
        if wanted and set(wanted) <= set(parse_quotes(_decode(buf))):
            break
    resp.close()

    text = _decode(buf)
    return parse_quotes(text), info, text


if __name__ == "__main__":
    print("== Диагностика ProFinance ==")
    try:
        quotes, info, raw = fetch_quotes(total_timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"ОШИБКА: {type(e).__name__}: {e}")
        raise SystemExit(1)
    print("Ответ сервера:", info)
    print("Получено байт текста:", len(raw), "| инструментов:", len(quotes))
    print("Первые 300 символов ответа:")
    print(raw[:300])
    print("\nИнструмент | TICK | Last | время")
    for name, q in quotes.items():
        print(f"{name} | {q['tick']} | {q['price']} | {q['time']}")
