#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kindle 7 信息屏渲染端
每小时运行一次：抓取天气/紫外线/空气质量/金句/上证指数 → 渲染 600x800 灰度 PNG
输出: panel.png（Kindle 端直接拉取这张图）
数据源:
  天气/紫外线/日出日落: Open-Meteo (免费, 无需 key) - 上海
  空气质量: Open-Meteo Air Quality API (免费, 无需 key)
  金句: 本地金句库轮换 (无网络依赖)
  上证: 新浪行情接口 (免费)
字体: HarmonyOS Sans SC (免费商用), 位于仓库 fonts/ 目录
"""
import json
import urllib.request
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

# ============ 配置 ============
W, H = 600, 800                      # Kindle 7 (KT2) 分辨率
LAT, LON = 31.2304, 121.4737         # 上海
FONT_REGULAR = "fonts/HarmonyOS_SansSC_Regular.ttf"
FONT_MEDIUM = "fonts/HarmonyOS_SansSC_Medium.ttf"
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ============ 金句库 ============
QUOTES = [
    "种一棵树最好的时间是十年前，其次是现在。",
    "知足者富，强行者有志。",
    "不积跬步，无以至千里。",
    "博观而约取，厚积而薄发。",
    "人非生而知之者，孰能无惑？",
    "路漫漫其修远兮，吾将上下而求索。",
    "纸上得来终觉浅，绝知此事要躬行。",
    "天行健，君子以自强不息。",
    "千里之行，始于足下。",
    "学而不思则罔，思而不学则殆。",
]


# ============ 数据抓取 ============
def fetch_json(url, timeout=15, retries=3):
    """抓 JSON，带重试（网络偶发超时兜底）"""
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last = e
    raise last


def get_weather():
    """Open-Meteo 上海实时天气 + 今日日出日落 + 紫外线指数"""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,relative_humidity_2m"
        f"&daily=sunrise,sunset,uv_index_max"
        f"&timezone=Asia%2FShanghai"
    )
    try:
        data = fetch_json(url)
        cur = data["current"]
        day = data["daily"]
        return {
            "temp": round(cur["temperature_2m"]),
            "humidity": round(cur["relative_humidity_2m"]),
            "sunrise": day["sunrise"][0][11:16],
            "sunset": day["sunset"][0][11:16],
            "uv": round(day["uv_index_max"][0]),
        }
    except Exception as e:
        return {"temp": "--", "humidity": "--", "sunrise": "--:--", "sunset": "--:--", "uv": "--", "error": str(e)}


def get_lunar():
    """lunar_python 计算黄历宜忌（只取宜/忌，不显示农历日期）"""
    try:
        from lunar_python import Lunar
        solar = datetime.now()
        lunar = Lunar.fromYmd(solar.year, solar.month, solar.day)
        return {
            "yi": lunar.getDayYi(),
            "ji": lunar.getDayJi(),
        }
    except Exception:
        return {"yi": "", "ji": ""}


def get_air_quality():
    """Open-Meteo 空气质量 API（上海 AQI）"""
    url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={LAT}&longitude={LON}"
        f"&current=us_aqi"
        f"&timezone=Asia%2FShanghai"
    )
    try:
        data = fetch_json(url)
        aqi = data["current"]["us_aqi"]
        return {"aqi": aqi, "level": aqi_level(aqi)}
    except Exception as e:
        return {"aqi": "--", "level": "", "error": str(e)}


def get_stock():
    """新浪上证指数实时行情"""
    # hq.sinajs.cn 需要 Referer，用新浪备用地址
    url = "https://hq.sinajs.cn/list=s_sh000001"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("gbk")
        # 格式: var hq_str_s_sh000001="上证指数,3345.61,7.21,0.22,198321,3.21,..."  简化版
        parts = text.split('"')[1].split(",")
        name = parts[0]
        # 简化版字段: 名称,当前价,涨跌额,涨跌幅,...（各数据源字段不同，容错解析）
        if len(parts) >= 4:
            price = parts[1]
            change_pct = parts[3]
            # 价格保留两位小数
            try:
                price = f"{float(price):.2f}"
            except ValueError:
                pass
            return {"name": name, "price": price, "pct": change_pct}
        return {"name": name, "price": parts[1] if len(parts) > 1 else "--", "pct": "--"}
    except Exception as e:
        return {"name": "上证指数", "price": "--", "pct": "--", "error": str(e)}


def get_quote():
    """本地金句库按天轮换（每天同一句，稳定不刷屏）"""
    day_of_year = datetime.now().timetuple().tm_yday
    return QUOTES[day_of_year % len(QUOTES)]


def aqi_level(aqi):
    """US AQI 等级 → 中文"""
    if aqi is None:
        return ""
    if aqi <= 50:
        return "优"
    if aqi <= 100:
        return "良"
    if aqi <= 150:
        return "轻度污染"
    if aqi <= 200:
        return "中度污染"
    if aqi <= 300:
        return "重度污染"
    return "严重污染"


def uv_level(uv):
    """紫外线指数等级"""
    if uv is None:
        return ""
    if uv <= 2:
        return "弱"
    if uv <= 5:
        return "中等"
    if uv <= 7:
        return "强"
    if uv <= 10:
        return "很强"
    return "极强"


# ============ 渲染 ============
def load_font(size, path=FONT_REGULAR):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def wrap_text(text, font, max_width, draw):
    """按像素宽度换行"""
    lines = []
    for line in text.split("\n"):
        if draw.textlength(line, font=font) <= max_width:
            lines.append(line)
            continue
        cur = ""
        for ch in line:
            if draw.textlength(cur + ch, font=font) <= max_width:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines


def draw_centered(draw, text, y, font, color=0):
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, y), text, font=font, fill=color)


def render(weather, air, lunar, stock, quote, now):
    img = Image.new("L", (W, H), 255)  # 白底
    draw = ImageDraw.Draw(img)

    f_title = load_font(42, FONT_MEDIUM)
    f_big = load_font(64, FONT_MEDIUM)
    f_mid = load_font(34, FONT_MEDIUM)
    f_small = load_font(26, FONT_REGULAR)
    f_quote = load_font(30, FONT_REGULAR)

    # 顶部: 日期 + 星期
    draw_centered(draw, now.strftime("%Y年%m月%d日") + " " + WEEKDAYS[now.weekday()], 20, f_mid)

    # 中部: 天气大卡片
    draw_centered(draw, "上海天气", 120, f_title)
    draw_centered(draw, f"{weather['temp']}°C", 165, f_big)
    draw_centered(
        draw,
        f"湿度 {weather['humidity']}% · 紫外线 {weather['uv']} {uv_level(weather['uv'])}",
        245,
        f_mid,
    )

    # 日出日落 + 空气质量
    draw_centered(draw, f"日出 {weather['sunrise']} · 日落 {weather['sunset']}", 300, f_small)
    draw_centered(draw, f"空气质量 {air['level']} · AQI {air['aqi']}", 335, f_small)

    # 黄历宜忌（只显示宜/忌，不显示农历日期）
    if lunar:
        yi = lunar.get("yi", "")
        ji = lunar.get("ji", "")
        yi = " ".join(yi) if isinstance(yi, list) else str(yi)
        ji = " ".join(ji) if isinstance(ji, list) else str(ji)
        draw_centered(draw, "宜: " + yi[:18], 375, f_small)
        draw_centered(draw, "忌: " + ji[:18], 410, f_small)

    # 上证指数
    draw_centered(draw, f"{stock['name']} {stock['price']}", 465, f_mid)
    draw_centered(draw, f"涨跌幅 {stock['pct']}%", 505, f_mid)

    # 分割线
    draw.line([(80, 560), (520, 560)], fill=0, width=2)

    # 每日金句（内容直接展示，无标题）
    lines = wrap_text(quote, f_quote, W - 80, draw)
    y = 580
    for line in lines[:4]:
        draw_centered(draw, line, y, f_quote)
        y += 44

    # 更新时间
    draw_centered(draw, "更新 " + now.strftime("%H:%M"), 745, f_small)

    img = img.convert("L")
    img.save("panel.png", optimize=True)
    print("panel.png saved")


def main():
    now = datetime.now()
    weather = get_weather()
    air = get_air_quality()
    lunar = get_lunar()
    stock = get_stock()
    quote = get_quote()
    render(weather, air, lunar, stock, quote, now)
    print("OK", json.dumps({"weather": weather, "air": air, "lunar": lunar, "stock": stock}, ensure_ascii=False))


if __name__ == "__main__":
    main()
