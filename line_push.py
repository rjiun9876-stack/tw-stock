# -*- coding: utf-8 -*-
"""
台股每日分析 → LINE 推播
每個交易日收盤後執行：抓 FinMind 免費資料，產生白話分析，
用 LINE 官方帳號 broadcast 給所有加好友的人（長輩）。
"""
import os
import sys
import datetime
import urllib.request
import urllib.parse
import json

API = "https://api.finmindtrade.com/api/v4/data"
TARGETS = [
    {"id": "TAIEX", "name": "台股大盤", "is_index": True},
    {"id": "2451",  "name": "創見(2451)", "is_index": False},
    {"id": "2377",  "name": "微星(2377)", "is_index": False},
]
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
PAGE_URL = os.environ.get("PAGE_URL", "")  # GitHub Pages 網址（選填）


def fetch(dataset, data_id, start_date):
    qs = urllib.parse.urlencode(
        {"dataset": dataset, "data_id": data_id, "start_date": start_date})
    req = urllib.request.Request(API + "?" + qs,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    if j.get("status") != 200:
        raise RuntimeError(j.get("msg", "API error"))
    return j.get("data", [])


def days_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def taipei_today():
    return (datetime.datetime.utcnow() +
            datetime.timedelta(hours=8)).date().isoformat()


def inst_daily(rows, who):
    m = {}
    for r in rows or []:
        if r["name"] == who:
            m[r["date"]] = m.get(r["date"], 0) + (r["buy"] - r["sell"])
    return [{"date": d, "net": m[d]} for d in sorted(m)]


def inst_streak(daily):
    if not daily:
        return 0
    s = 0
    last_sign = 0
    for row in reversed(daily):
        sign = (row["net"] > 0) - (row["net"] < 0)
        if last_sign == 0:
            if sign == 0:
                break
            last_sign = sign
            s = sign
        elif sign == last_sign:
            s += sign
        else:
            break
    return s  # 正=連買天數，負=連賣天數


def analyze(rows, inst_rows, is_index):
    closes = [r["close"] for r in rows]
    last = rows[-1]
    unit = "點" if is_index else "元"
    dec = 0 if is_index else 1
    spread = last["spread"]
    prev = last["close"] - spread
    pct = spread / prev * 100 if prev else 0.0

    arrow = "🔺" if spread > 0 else ("🔻" if spread < 0 else "➖")
    head = "{} {:,.{d}f}{}（{}{:.2f}%）".format(
        arrow, last["close"], unit, "+" if pct >= 0 else "", pct, d=dec)

    sents = []
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    tone = "flat"
    if ma5 and ma20:
        if last["close"] > ma5 > ma20:
            sents.append("最近走勢偏強")
            tone = "up"
        elif last["close"] < ma5 < ma20:
            sents.append("最近走勢偏弱")
            tone = "down"
        else:
            sents.append("最近在盤整")

    fi_streak = inst_streak(inst_daily(inst_rows, "Foreign_Investor"))
    if fi_streak >= 3:
        sents.append("外資連買{}天".format(fi_streak))
    elif fi_streak <= -3:
        sents.append("外資連賣{}天".format(-fi_streak))

    hi60 = max(closes[-60:]) if len(closes) >= 2 else last["close"]
    dd = (hi60 - last["close"]) / hi60 * 100 if hi60 else 0
    if dd >= 15:
        sents.append("比近期高點低約{:.0f}%，波動大，保守先觀望".format(dd))
    elif dd >= 8:
        sents.append("比高點低約{:.0f}%，不建議大筆買進".format(dd))
    elif tone == "up":
        sents.append("持股可續抱，照原計畫就好")
    else:
        sents.append("維持平常心")

    return head, "、".join(sents) + "。"


def build_message():
    start = days_ago(120)
    today = taipei_today()
    blocks = []
    latest_date = None
    for t in TARGETS:
        rows = fetch("TaiwanStockPrice", t["id"], start)
        if not rows:
            continue
        rows.sort(key=lambda r: r["date"])
        latest_date = rows[-1]["date"]
        inst_rows = []
        if not t["is_index"]:
            try:
                inst_rows = fetch("TaiwanStockInstitutionalInvestorsBuySell",
                                  t["id"], days_ago(15))
            except Exception:
                pass
        head, advice = analyze(rows, inst_rows, t["is_index"])
        blocks.append("【{}】\n{}\n💬 {}".format(t["name"], head, advice))

    if latest_date is None:
        raise RuntimeError("抓不到任何資料")
    # 假日/休市：最新資料不是今天就不發，避免舊資料誤導
    if latest_date != today:
        print("今日({})非交易日或資料未更新(最新={})，不推播。".format(
            today, latest_date))
        return None

    msg = "📈 台股每日分析 {}\n\n".format(latest_date.replace("-", "/"))
    msg += "\n\n".join(blocks)
    if PAGE_URL:
        msg += "\n\n📱 詳細圖表：\n" + PAGE_URL
    msg += "\n\n（僅供參考，非投資建議）"
    return msg


def line_broadcast(text):
    body = json.dumps(
        {"messages": [{"type": "text", "text": text}]}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/broadcast",
        data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + LINE_TOKEN,
        })
    with urllib.request.urlopen(req, timeout=30) as r:
        print("LINE 回應:", r.status)


if __name__ == "__main__":
    message = build_message()
    if message is None:
        sys.exit(0)
    print("===== 訊息內容 =====")
    print(message)
    print("====================")
    if not LINE_TOKEN:
        print("未設定 LINE_CHANNEL_ACCESS_TOKEN，僅預覽不發送。")
        sys.exit(0)
    line_broadcast(message)
    print("推播完成 ✅")
