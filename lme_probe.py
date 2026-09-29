#!/usr/bin/env python3
"""Диагностика: пускает ли LME запрос из GitHub Actions и что в ответе.
Ничего не отправляет в Telegram, только печатает в лог."""
import json
import urllib.error
import urllib.request

URL = "https://www.lme.com/api/trading-data/day-delayed?datasourceId=1a0ef0b6-3ee6-4e44-a415-7a313d5bd771"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.lme.com/en/Metals/Non-ferrous/LME-Aluminium",
}


def find_cash(node, found, limit=8):
    """Собирает словари/списки, в которых где-то встречается слово cash."""
    if len(found) >= limit:
        return
    if isinstance(node, dict):
        if any(isinstance(v, str) and "cash" in v.lower() for v in node.values()):
            found.append(node)
        for v in node.values():
            find_cash(v, found, limit)
    elif isinstance(node, list):
        for v in node:
            find_cash(v, found, limit)


def main():
    print("== Диагностика LME ==")
    req = urllib.request.Request(URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, ctype, raw = resp.status, resp.headers.get("Content-Type"), resp.read()
    except urllib.error.HTTPError as e:
        print(f"HTTP-ошибка: {e.code} {e.reason}")
        print("Заголовки ответа (часть):", {k: v for k, v in e.headers.items() if k.lower() in ("server", "content-type", "cf-ray", "x-cache")})
        print("Начало тела ответа:", e.read()[:500].decode("utf-8", errors="replace"))
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001
        print(f"Ошибка соединения: {type(e).__name__}: {e}")
        raise SystemExit(1)

    text = raw.decode("utf-8", errors="replace")
    print(f"Статус: {status} | Content-Type: {ctype} | размер: {len(raw)} байт")
    print("Начало ответа (первые 1500 символов):")
    print(text[:1500])

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("\nОтвет не JSON.")
        return
    found = []
    find_cash(data, found)
    print(f"\nЭлементов со словом cash: {len(found)}")
    for item in found:
        print(json.dumps(item, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
