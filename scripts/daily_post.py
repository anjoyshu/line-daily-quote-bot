"""Daily LINE quote bot.

Fetches Wikimedia Commons "Picture of the day", composes it with a
motivational quote picked deterministically from quotes.txt (cycles
through the whole list before repeating), and either saves the image
(step=generate) or pushes it to a LINE group (step=push).
"""
import argparse
import datetime as dt
import io
import os
import random
import re
import textwrap

import requests
from PIL import Image, ImageDraw, ImageFont

REPO = os.environ.get("GITHUB_REPOSITORY", "anjoyshu/line-daily-quote-bot")
BRANCH = "main"
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
SHUFFLE_SEED = 20260101
EPOCH = dt.date(2026, 1, 1)


def taiwan_today():
    now_utc = dt.datetime.utcnow()
    return (now_utc + dt.timedelta(hours=8)).date()


def get_potd_filename(date):
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "parse",
        "page": f"Template:Potd/{date.isoformat()}",
        "prop": "wikitext",
        "format": "json",
    }
    r = requests.get(api, params=params, timeout=20)
    r.raise_for_status()
    wikitext = r.json()["parse"]["wikitext"]["*"]
    m = re.search(r"\{\{Potd filename\|[^|]*\|([^|}]+)", wikitext)
    if not m:
        raise RuntimeError("could not find POTD filename for " + date.isoformat())
    return m.group(1).strip()


def get_image_info(filename):
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": "File:" + filename,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1600,
        "format": "json",
    }
    r = requests.get(api, params=params, timeout=20)
    r.raise_for_status()
    pages = r.json()["query"]["pages"]
    page = next(iter(pages.values()))
    info = page["imageinfo"][0]
    url = info.get("thumburl") or info["url"]
    meta = info.get("extmetadata", {})
    artist = re.sub("<[^<]+?>", "", meta.get("Artist", {}).get("value", "")).strip()
    license_name = meta.get("LicenseShortName", {}).get("value", "")
    return url, artist, license_name


def download_image(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def load_quotes():
    with open("quotes.txt", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def pick_quote(quotes, date):
    deck = list(range(len(quotes)))
    random.Random(SHUFFLE_SEED).shuffle(deck)
    day_index = (date - EPOCH).days
    pos = day_index % len(deck)
    cycle = day_index // len(deck)
    return quotes[deck[pos]], cycle


def compose(photo, quote_text, date, artist, license_name):
    width = photo.width
    pad = 28
    quote_font = ImageFont.truetype(FONT_REGULAR, 22)
    meta_font = ImageFont.truetype(FONT_REGULAR, 14)
    date_font = ImageFont.truetype(FONT_BOLD, 16)

    wrapped = textwrap.wrap(quote_text, width=15)
    line_h = 34
    quote_block_h = line_h * len(wrapped)

    weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
    date_str = date.strftime("%Y年%m月%d日") + " 星期" + weekday_map[date.weekday()]

    panel_h = pad + 22 + 14 + quote_block_h + 12 + 10 + 18 + pad
    canvas = Image.new("RGB", (width, photo.height + panel_h), (250, 247, 240))
    canvas.paste(photo, (0, 0))

    draw = ImageDraw.Draw(canvas)
    y = photo.height + pad
    draw.text((pad, y), date_str, font=date_font, fill=(90, 70, 40))
    y += 22 + 14

    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=quote_font)
        tw = bbox[2] - bbox[0]
        x = (width - tw) / 2
        draw.text((x, y), line, font=quote_font, fill=(40, 30, 20))
        y += line_h

    y += 12
    draw.line([(pad, y), (width - pad, y)], fill=(210, 200, 180), width=1)
    y += 10

    credit = f"{artist}, {license_name}, via Wikimedia Commons".strip(", ")
    draw.text((pad, y), credit, font=meta_font, fill=(150, 140, 120))
    return canvas


def cmd_generate(args):
    today = taiwan_today()
    filename = get_potd_filename(today)
    url, artist, license_name = get_image_info(filename)
    photo = download_image(url)
    quotes = load_quotes()
    quote_text, _cycle = pick_quote(quotes, today)
    canvas = compose(photo, quote_text, today, artist, license_name)
    os.makedirs("images", exist_ok=True)
    out_path = f"images/{today.isoformat()}.jpg"
    canvas.save(out_path, quality=90)
    print("saved", out_path)
    print("public_url=" + f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{out_path}")


def cmd_push(args):
    today = taiwan_today()
    out_path = f"images/{today.isoformat()}.jpg"
    image_url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{out_path}"
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    group_id = os.environ["LINE_GROUP_ID"]
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": group_id,
            "messages": [
                {
                    "type": "image",
                    "originalContentUrl": image_url,
                    "previewImageUrl": image_url,
                }
            ],
        },
        timeout=20,
    )
    print(resp.status_code, resp.text)
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["generate", "push"], required=True)
    args = parser.parse_args()
    if args.step == "generate":
        cmd_generate(args)
    else:
        cmd_push(args)


if __name__ == "__main__":
    main()
