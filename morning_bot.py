#!/usr/bin/env python3
"""Утренняя сводка в Telegram.

Сейчас: новости Asia-Plus (заголовок + ссылка), без шума и без повторов.
Цены и курсы подключаются позже в функции get_prices().
Только стандартная библиотека Python, ничего устанавливать не нужно.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

# ------------------------- НАСТРОЙКИ -------------------------
TIMEZONE = "Asia/Dushanbe"      # ваш часовой пояс
SEND_TIME = (8, 0)              # во сколько слать: (часы, минуты)
MAX_WAIT_MINUTES = 40           # ждать 8:00 не дольше этого; иначе слать сразу
FEED_URL = "https://asiaplus.news/feed/"            # RSS (проверьте, что открывается)
PAGE_URL = "https://asiaplus.news/vse-novosti/"     # запасной вариант: разбор страницы
STOP_PHRASES = ["салом алейкум", "#ap30"]           # шум: заголовки с этим пропускаем
MAX_ITEMS = 50                  # не больше новостей за один раз
KEEP_SENT = 1000                # сколько отправленных ссылок помнить
TG_LIMIT = 4000                 # лимит Telegram ~4096 символов на сообщение
USER_AGENT = "Mozilla/5.0 (compatible; morning-bot/1.0)"
STATE_FILE = Path(__file__).with_name("sent.json")
# --------------------------------------------------------------

ARTICLE_RE = re.compile(r"/20\d\d/\d\d/\d\d/")  # ссылки на материалы вида /2026/09/28/...


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------- получение новостей ----------
def parse_rss(text):
    root = ET.fromstring(text)
    items = []
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if title and link:
            items.append((title, link))
    return items


class H3Links(HTMLParser):
    """Собирает ссылки внутри заголовков <h3> (так устроена страница «Все новости»)."""

    def __init__(self):
        super().__init__()
        self.items = []
        self._in_h3 = False
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "h3":
            self._in_h3 = True
        elif tag == "a" and self._in_h3:
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            title = " ".join("".join(self._buf).split())
            if title:
                self.items.append((title, self._href))
            self._href = None
        elif tag == "h3":
            self._in_h3 = False


def parse_page(text):
    parser = H3Links()
    parser.feed(text)
    return parser.items


def clean(items):
    """Оставляет только материалы, убирает дубли и шум."""
    result, seen = [], set()
    for title, link in items:
        if link in seen or not ARTICLE_RE.search(link):
            continue
        if any(p in title.lower() for p in STOP_PHRASES):
            continue
        seen.add(link)
        result.append((title, link))
    return result


def get_news():
    errors = []
    for name, url, parser in (("RSS", FEED_URL, parse_rss), ("страница", PAGE_URL, parse_page)):
        try:
            items = clean(parser(fetch(url)))
            if items:
                print(f"Новости получены ({name}): {len(items)} шт.")
                return items
            errors.append(f"{name}: пусто")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}")
    raise RuntimeError("; ".join(errors))


# ---------- цены (пока заглушка) ----------
def get_prices():
    """Вернуть список строк вида «Золото: 1234 (дата)». Подключим позже:
    LME (cash offer), ProFinance (золото, Brent, EUR/USD, USD/RUB, алюминий)."""
    return []


# ---------- состояние (что уже отправлено) ----------
def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_state(links):
    STATE_FILE.write_text(
        json.dumps(links[-KEEP_SENT:], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


# ---------- сообщения ----------
def split_blocks(header, blocks, limit=TG_LIMIT):
    messages, current = [], header
    for block in blocks:
        if len(current) + len(block) + 2 > limit and current.strip() != header.strip():
            messages.append(current.rstrip())
            current = ""
        current += block + "\n\n"
    if current.strip():
        messages.append(current.rstrip())
    return messages


def build_news_messages(items):
    if not items:
        return ["📰 Asia-Plus: новых материалов нет."]
    blocks = [f"• {title}\n{link}" for title, link in items]
    return split_blocks("📰 Asia-Plus: новое\n\n", blocks)


def send_telegram(token, chat_id, text):
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram ответил ошибкой: {e.read().decode(errors='replace')}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram недоступен: {e.reason}") from None
    if not body.get("ok"):
        raise RuntimeError(f"Telegram ответил ошибкой: {body}")


# ---------- ожидание 8:00 ----------
def wait_until_send_time():
    if os.environ.get("SKIP_WAIT"):
        return
    now = datetime.now(ZoneInfo(TIMEZONE))
    target = now.replace(hour=SEND_TIME[0], minute=SEND_TIME[1], second=0, microsecond=0)
    delta = (target - now).total_seconds()
    if 0 < delta <= MAX_WAIT_MINUTES * 60:
        print(f"Жду {int(delta)} сек. до {SEND_TIME[0]:02d}:{SEND_TIME[1]:02d}")
        time.sleep(delta)
    else:
        print("Время отправки уже наступило или далеко: отправляю сразу")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    sent = load_state()
    sent_set = set(sent)
    messages, new_items = [], []

    price_lines = get_prices()
    if price_lines:
        messages.append("💹 Цены и курсы\n\n" + "\n".join(price_lines))

    try:
        fresh = [(t, l) for t, l in get_news() if l not in sent_set]
        new_items = fresh[:MAX_ITEMS]
        messages += build_news_messages(new_items)
    except Exception as e:  # noqa: BLE001
        messages.append(f"⚠️ Asia-Plus: не удалось получить новости ({e})")

    wait_until_send_time()
    for text in messages:
        send_telegram(token, chat_id, text)

    sent.extend(link for _, link in new_items)
    save_state(sent)
    print(f"Готово: сообщений {len(messages)}, новых ссылок {len(new_items)}")


if __name__ == "__main__":
    main()
