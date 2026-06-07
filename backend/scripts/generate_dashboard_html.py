"""Generate a single self-contained HTML dashboard from the current DB state.

Design: Notion-clean, alerts-first, one long scroll, TH/EN toggle.

Run:
    docker compose exec backend python scripts/generate_dashboard_html.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db import engine

BKK = ZoneInfo("Asia/Bangkok")
OUT_PATH = Path("/app/dashboard.html")


def _encode(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"can't encode {type(o)}")


def fetch():
    with engine.connect() as conn:
        health = dict(conn.execute(text(
            "SELECT * FROM public_safe.store_health_score"
        )).mappings().first())

        trend = [dict(r) for r in conn.execute(text("""
            SELECT business_day, total_thb, cash_thb, transfer_thb
            FROM public_safe.daily_revenue
            ORDER BY business_day
        """)).mappings()]

        today = trend[-1] if trend else {}

        totals = dict(conn.execute(text("""
            SELECT
                SUM(total_thb)::numeric    AS total_revenue_30d,
                SUM(cash_thb)::numeric     AS cash_30d,
                SUM(transfer_thb)::numeric AS transfer_30d,
                SUM(receipt_count)::int    AS receipts_30d
            FROM public_safe.daily_revenue
        """)).mappings().first())

        match_summary = dict(conn.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE status='VERIFIED')           AS verified,
                COUNT(*) FILTER (WHERE status='UNMATCHED')          AS unmatched,
                COUNT(*) FILTER (WHERE status='POSSIBLE_DUPLICATE') AS duplicates
            FROM transfer_matches
        """)).mappings().first())

        alerts = [dict(r) for r in conn.execute(text("""
            SELECT severity, alert_type, payload, financial_impact_thb,
                   created_at, shift_id
            FROM alerts WHERE acked_at IS NULL
            ORDER BY
                CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT 20
        """)).mappings()]

        matching = [dict(r) for r in conn.execute(text("""
            SELECT receipt_id, timestamp, total, transfer_amount,
                   payment_method, status, time_delta_seconds
            FROM public_safe.live_payment_matching
            WHERE status IS NOT NULL
            ORDER BY
                CASE status WHEN 'UNMATCHED' THEN 0 WHEN 'POSSIBLE_DUPLICATE' THEN 1 ELSE 2 END,
                timestamp DESC
            LIMIT 20
        """)).mappings()]

        inv_loss = [dict(r) for r in conn.execute(text("""
            SELECT sku, name, sold, shrinkage_units, shrinkage_events
            FROM public_safe.inventory_loss_view
            WHERE shrinkage_units IS NOT NULL AND shrinkage_units != 0
            ORDER BY shrinkage_units
        """)).mappings()]

        shifts = [dict(r) for r in conn.execute(text("""
            SELECT shift_id, scheduled_start, scheduled_end, employees,
                   revenue_thb, cash_discrepancy_thb, discrepancy_count
            FROM public_safe.shift_summary
            ORDER BY scheduled_start DESC
            LIMIT 7
        """)).mappings()]

        employees = [dict(r) for r in conn.execute(text("""
            SELECT name, transactions_handled, shifts_worked,
                   open_discrepancies, total_impact_thb, anomaly_alerts
            FROM public_safe.employee_accountability
            ORDER BY anomaly_alerts DESC, transactions_handled DESC
        """)).mappings()]

    return {
        "health": health, "trend": trend, "today": today, "totals": totals,
        "match_summary": match_summary, "alerts": alerts, "matching": matching,
        "inv_loss": inv_loss, "shifts": shifts, "employees": employees,
    }


def render(d: dict, now: datetime) -> str:
    j = json.dumps(d, default=_encode, ensure_ascii=False)
    health_score = int(d["health"].get("score_pct") or 0)
    health_color = d["health"].get("status_color") or "green"

    total_30d = int(float(d["totals"].get("total_revenue_30d") or 0))
    rcpt_30d = int(d["totals"].get("receipts_30d") or 0)

    verified = int(d["match_summary"].get("verified") or 0)
    unmatched = int(d["match_summary"].get("unmatched") or 0)
    duplicates = int(d["match_summary"].get("duplicates") or 0)
    match_pct = round(100 * verified / max(1, verified + unmatched + duplicates), 1)

    today_rev = int(float(d["today"].get("total_thb") or 0))
    today_cash = int(float(d["today"].get("cash_thb") or 0))
    today_xfer = int(float(d["today"].get("transfer_thb") or 0))
    today_receipts = int(d["today"].get("receipt_count") or 0)

    inv_loss_count = sum(int(abs(float(r["shrinkage_units"]))) for r in d["inv_loss"])

    alerts_count = len(d["alerts"])
    alerts_label_en = "All clear" if alerts_count == 0 else f"{alerts_count} need{'s' if alerts_count == 1 else ''} attention"
    alerts_label_th = "ทุกอย่างเรียบร้อย" if alerts_count == 0 else f"มี {alerts_count} เรื่องต้องดู"
    alerts_mood = "calm" if alerts_count == 0 else ("watch" if alerts_count < 5 else "urgent")

    return TEMPLATE.format(
        generated_at=now.strftime("%a %d %b %Y · %H:%M"),
        data_json=j,
        health_score=health_score,
        health_color=health_color,
        health_label_en={"green": "Healthy", "yellow": "Watch", "red": "Action needed"}[health_color],
        health_label_th={"green": "ดี", "yellow": "ต้องระวัง", "red": "ต้องแก้ไข"}[health_color],
        alerts_count=alerts_count,
        alerts_label_en=alerts_label_en,
        alerts_label_th=alerts_label_th,
        alerts_mood=alerts_mood,
        today_rev=f"{today_rev:,}",
        today_cash=f"{today_cash:,}",
        today_xfer=f"{today_xfer:,}",
        today_receipts=today_receipts,
        total_30d=f"{total_30d:,}",
        rcpt_30d=f"{rcpt_30d:,}",
        verified=verified,
        unmatched=unmatched,
        match_pct=match_pct,
        inv_loss_count=inv_loss_count,
    )


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShopOS — Today</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  /* ===== Reset ===== */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  /* ===== Notion-clean palette ===== */
  :root {{
    --bg: #ffffff;
    --bg-soft: #fbfbfa;
    --bg-paper: #f7f7f5;
    --border: #ebebea;
    --border-strong: #d8d8d6;
    --text: #37352f;
    --text-muted: #6b6a66;
    --text-light: #9b9a97;

    --mint-bg: #e0f0e8;
    --mint-text: #1f4d36;
    --mint-bg-strong: #c4e5d3;

    --peach-bg: #faebdd;
    --peach-text: #835a18;

    --rose-bg: #fbe4e6;
    --rose-text: #8b2a32;
    --rose-bg-strong: #f6cbcf;

    --sky-bg: #e2ecf2;
    --sky-text: #1e3a5f;

    --lavender-bg: #ece6f3;
    --lavender-text: #4d3680;

    --gray-bg: #efefed;
    --gray-text: #5a5955;
  }}

  html, body {{
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI",
                 "Sarabun", "Noto Sans Thai", Tahoma, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    font-size: 15px;
  }}

  .wrap {{ max-width: 880px; margin: 0 auto; padding: 0 24px; }}

  /* ===== Header ===== */
  header {{
    padding: 28px 0 24px;
    border-bottom: 1px solid var(--border);
  }}
  header .wrap {{
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 16px;
  }}
  .brand {{ display: flex; align-items: center; gap: 12px; }}
  .brand-mark {{
    width: 36px; height: 36px; border-radius: 10px;
    background: var(--lavender-bg); color: var(--lavender-text);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 14px; letter-spacing: -0.02em;
  }}
  .brand-text h1 {{
    font-size: 17px; font-weight: 600; color: var(--text);
    letter-spacing: -0.01em;
  }}
  .brand-text p {{
    font-size: 13px; color: var(--text-muted); margin-top: 1px;
  }}
  .header-right {{
    display: flex; align-items: center; gap: 14px;
    font-size: 13px; color: var(--text-muted);
  }}
  .lang-toggle {{
    border: 1px solid var(--border); background: var(--bg);
    padding: 6px 12px; border-radius: 8px; font-size: 12px;
    color: var(--text); font-weight: 500; cursor: pointer;
    font-family: inherit;
  }}
  .lang-toggle:hover {{ background: var(--bg-paper); }}

  /* ===== Main ===== */
  main {{ padding: 32px 0 80px; }}

  section {{ margin-bottom: 48px; }}

  .section-title {{
    font-size: 13px; font-weight: 600; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 16px;
  }}

  h2 {{
    font-size: 22px; font-weight: 600; color: var(--text);
    letter-spacing: -0.015em; margin-bottom: 4px;
  }}
  h3 {{
    font-size: 16px; font-weight: 600; color: var(--text);
    letter-spacing: -0.01em;
  }}
  .subtle {{ color: var(--text-muted); font-size: 14px; }}

  /* ===== Hero: Alerts-first ===== */
  .hero {{
    border-radius: 16px;
    padding: 32px 32px 28px;
    margin-bottom: 36px;
  }}
  .hero.calm {{
    background: var(--mint-bg);
    color: var(--mint-text);
  }}
  .hero.watch {{
    background: var(--peach-bg);
    color: var(--peach-text);
  }}
  .hero.urgent {{
    background: var(--rose-bg);
    color: var(--rose-text);
  }}
  .hero-eyebrow {{
    font-size: 12px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; opacity: 0.7;
  }}
  .hero-headline {{
    font-size: 32px; font-weight: 700; letter-spacing: -0.02em;
    margin-top: 4px; margin-bottom: 8px;
    line-height: 1.15;
  }}
  .hero-sub {{ font-size: 16px; opacity: 0.85; }}

  /* ===== Alert list ===== */
  .alert-list {{ margin-top: 24px; }}
  .alert {{
    background: rgba(255, 255, 255, 0.55);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 8px;
    display: flex; gap: 14px; align-items: flex-start;
    transition: background 0.15s;
  }}
  .alert:hover {{ background: rgba(255, 255, 255, 0.8); }}
  .alert-emoji {{
    flex-shrink: 0; font-size: 20px; line-height: 1;
    padding-top: 2px;
  }}
  .alert-body {{ flex: 1; min-width: 0; }}
  .alert-title {{
    font-size: 15px; font-weight: 600; line-height: 1.4;
    color: inherit;
  }}
  .alert-desc {{
    font-size: 13px; opacity: 0.78; margin-top: 2px;
  }}
  .alert-meta {{
    font-size: 12px; opacity: 0.6; margin-top: 4px;
  }}
  .alert-impact {{
    font-size: 14px; font-weight: 700; white-space: nowrap;
    align-self: center;
  }}
  .empty-state {{
    text-align: center; padding: 24px;
    color: inherit; opacity: 0.85;
    font-size: 15px;
  }}

  /* ===== KPI strip ===== */
  .kpi-strip {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 12px; margin-bottom: 8px;
  }}
  .kpi {{
    background: var(--bg-paper);
    border-radius: 12px;
    padding: 18px 18px 16px;
  }}
  .kpi-label {{
    font-size: 12px; color: var(--text-muted);
    font-weight: 500;
  }}
  .kpi-value {{
    font-size: 24px; font-weight: 700; color: var(--text);
    margin-top: 6px; letter-spacing: -0.02em;
  }}
  .kpi-sub {{
    font-size: 12px; color: var(--text-muted); margin-top: 4px;
  }}
  @media (max-width: 700px) {{
    .kpi-strip {{ grid-template-columns: repeat(2, 1fr); }}
    .hero-headline {{ font-size: 26px; }}
    .hero {{ padding: 24px; }}
  }}

  /* ===== Section blocks ===== */
  .block {{
    background: var(--bg-paper);
    border-radius: 14px;
    padding: 24px 26px;
  }}
  .block + .block {{ margin-top: 12px; }}

  /* ===== Trend chart ===== */
  .chart-wrap {{ height: 260px; margin-top: 16px; position: relative; }}

  /* ===== Tables ===== */
  .table-wrap {{ margin-top: 14px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{
    text-align: left; font-weight: 500; color: var(--text-muted);
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 10px 14px 10px 0; border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 14px 14px 14px 0; color: var(--text);
    border-bottom: 1px solid var(--border);
  }}
  tr:last-child td {{ border-bottom: none; }}
  .num {{ font-variant-numeric: tabular-nums; text-align: right; padding-right: 0; }}
  th.num {{ text-align: right; }}
  .mono {{
    font-family: "SF Mono", "JetBrains Mono", Consolas, monospace;
    font-size: 12px; color: var(--text-muted);
  }}

  /* ===== Badges ===== */
  .badge {{
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.02em;
    text-transform: lowercase;
  }}
  .badge-verified {{ background: var(--mint-bg); color: var(--mint-text); }}
  .badge-unmatched {{ background: var(--rose-bg); color: var(--rose-text); }}
  .badge-duplicate {{ background: var(--peach-bg); color: var(--peach-text); }}

  .pill-warn {{
    color: var(--rose-text); font-weight: 600;
  }}
  .pill-ok {{ color: var(--text-muted); }}

  /* ===== Actions ===== */
  .actions {{ margin-top: 40px; display: flex; gap: 10px; flex-wrap: wrap; }}
  .btn {{
    padding: 10px 18px; border-radius: 10px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 14px;
    font-weight: 500; cursor: pointer; font-family: inherit;
  }}
  .btn:hover {{ background: var(--bg-paper); }}
  .btn-primary {{
    background: var(--text); color: var(--bg); border-color: var(--text);
  }}
  .btn-primary:hover {{ background: #1f1e1c; }}

  /* ===== Footer ===== */
  footer {{
    margin-top: 64px; padding-top: 24px;
    border-top: 1px solid var(--border);
    color: var(--text-light); font-size: 12px;
    text-align: center; line-height: 1.7;
  }}
  footer span {{ display: inline-block; padding: 0 6px; }}

  /* ===== Bilingual ===== */
  [data-th] {{ display: none; }}
  body.th [data-en] {{ display: none; }}
  body.th [data-th] {{ display: inline; }}

  /* ===== Print ===== */
  @media print {{
    body {{ background: white; }}
    .lang-toggle, .actions {{ display: none; }}
    .hero {{ break-inside: avoid; }}
    section {{ break-inside: avoid-page; }}
  }}
</style>
</head>
<body>

<!-- ============ HEADER ============ -->
<header>
  <div class="wrap">
    <div class="brand">
      <div class="brand-mark">OT</div>
      <div class="brand-text">
        <h1>ShopOS</h1>
        <p>
          <span data-en>Today, {generated_at}</span>
          <span data-th>วันนี้ {generated_at}</span>
        </p>
      </div>
    </div>
    <div class="header-right">
      <button class="lang-toggle" onclick="document.body.classList.toggle('th')">
        <span data-en>ภาษาไทย</span>
        <span data-th>English</span>
      </button>
    </div>
  </div>
</header>

<main>
<div class="wrap">

<!-- ============ HERO: ALERTS-FIRST ============ -->
<section class="hero {alerts_mood}">
  <div class="hero-eyebrow">
    <span data-en>What needs your attention</span>
    <span data-th>เรื่องที่ต้องดู</span>
  </div>
  <div class="hero-headline">
    <span data-en>{alerts_label_en}</span>
    <span data-th>{alerts_label_th}</span>
  </div>
  <div class="hero-sub">
    <span data-en>Sorted by what could cost you the most.</span>
    <span data-th>เรียงตามความเสี่ยงทางการเงิน</span>
  </div>

  <div class="alert-list" id="alerts-feed"></div>
</section>

<!-- ============ HOW'S THE STORE TODAY ============ -->
<section>
  <h2>
    <span data-en>How's the store today?</span>
    <span data-th>วันนี้ร้านเป็นยังไง?</span>
  </h2>
  <p class="subtle">
    <span data-en>{today_receipts} receipts so far · ฿{today_rev} in sales</span>
    <span data-th>วันนี้ขายไป {today_receipts} บิล · ฿{today_rev}</span>
  </p>

  <div class="kpi-strip" style="margin-top: 20px;">
    <div class="kpi">
      <div class="kpi-label">
        <span data-en>Store Health</span>
        <span data-th>สุขภาพร้าน</span>
      </div>
      <div class="kpi-value">{health_score}<span style="font-size:14px;color:var(--text-muted);font-weight:500;">/100</span></div>
      <div class="kpi-sub">
        <span data-en>{health_label_en}</span>
        <span data-th>{health_label_th}</span>
      </div>
    </div>
    <div class="kpi">
      <div class="kpi-label">
        <span data-en>Today's revenue</span>
        <span data-th>ยอดขายวันนี้</span>
      </div>
      <div class="kpi-value">฿{today_rev}</div>
      <div class="kpi-sub">
        <span data-en>cash ฿{today_cash} · transfer ฿{today_xfer}</span>
        <span data-th>เงินสด ฿{today_cash} · โอน ฿{today_xfer}</span>
      </div>
    </div>
    <div class="kpi">
      <div class="kpi-label">
        <span data-en>Transfers matched</span>
        <span data-th>โอนยืนยันแล้ว</span>
      </div>
      <div class="kpi-value">{match_pct}%</div>
      <div class="kpi-sub">
        <span data-en>{verified} verified · {unmatched} missing</span>
        <span data-th>ยืนยัน {verified} · ไม่พบ {unmatched}</span>
      </div>
    </div>
    <div class="kpi">
      <div class="kpi-label">
        <span data-en>Items missing</span>
        <span data-th>สินค้าหาย</span>
      </div>
      <div class="kpi-value">{inv_loss_count}</div>
      <div class="kpi-sub">
        <span data-en>last 30 days</span>
        <span data-th>ใน 30 วันที่ผ่านมา</span>
      </div>
    </div>
  </div>
</section>

<!-- ============ TREND ============ -->
<section>
  <h2>
    <span data-en>The last 30 days</span>
    <span data-th>30 วันที่ผ่านมา</span>
  </h2>
  <p class="subtle">
    <span data-en>฿{total_30d} total · {rcpt_30d} receipts</span>
    <span data-th>รวม ฿{total_30d} · {rcpt_30d} บิล</span>
  </p>
  <div class="block" style="margin-top: 16px;">
    <div class="chart-wrap">
      <canvas id="trendChart"></canvas>
    </div>
  </div>
</section>

<!-- ============ TRANSFERS ============ -->
<section>
  <h2>
    <span data-en>Transfer payments</span>
    <span data-th>การชำระโอน</span>
  </h2>
  <p class="subtle">
    <span data-en>Each transfer is checked against your KBank account.</span>
    <span data-th>การโอนแต่ละครั้งจะตรวจกับบัญชี KBank</span>
  </p>
  <div class="block" style="margin-top: 16px; padding: 0;">
    <div class="table-wrap" style="padding: 0 26px;">
      <table id="matching-table">
        <thead>
          <tr>
            <th><span data-en>Receipt</span><span data-th>บิล</span></th>
            <th><span data-en>When</span><span data-th>เวลา</span></th>
            <th class="num"><span data-en>Amount</span><span data-th>จำนวน</span></th>
            <th class="num"><span data-en>Status</span><span data-th>สถานะ</span></th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</section>

<!-- ============ INVENTORY ============ -->
<section>
  <h2>
    <span data-en>Inventory</span>
    <span data-th>สินค้าคงเหลือ</span>
  </h2>
  <p class="subtle">
    <span data-en>Items where the count doesn't match what was sold.</span>
    <span data-th>สินค้าที่นับแล้วไม่ตรงกับที่ขายไป</span>
  </p>
  <div class="block" style="margin-top: 16px;" id="inv-block">
    <table id="inv-table">
      <thead>
        <tr>
          <th><span data-en>Product</span><span data-th>สินค้า</span></th>
          <th class="num"><span data-en>Sold</span><span data-th>ขาย</span></th>
          <th class="num"><span data-en>Missing</span><span data-th>หาย</span></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
</section>

<!-- ============ SHIFTS ============ -->
<section>
  <h2>
    <span data-en>Recent shifts</span>
    <span data-th>กะล่าสุด</span>
  </h2>
  <p class="subtle">
    <span data-en>Last 7 shifts. Cash difference shows what was off at close.</span>
    <span data-th>กะล่าสุด 7 รายการ · ผลต่างเงินสดตอนปิดกะ</span>
  </p>
  <div class="block" style="margin-top: 16px;">
    <table id="shifts-table">
      <thead>
        <tr>
          <th><span data-en>When</span><span data-th>เวลา</span></th>
          <th><span data-en>Staff</span><span data-th>พนักงาน</span></th>
          <th class="num"><span data-en>Sales</span><span data-th>ยอดขาย</span></th>
          <th class="num"><span data-en>Cash diff</span><span data-th>เงินสดต่าง</span></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
</section>

<!-- ============ STAFF ============ -->
<section>
  <h2>
    <span data-en>Your team</span>
    <span data-th>พนักงานของคุณ</span>
  </h2>
  <p class="subtle">
    <span data-en>Sorted by alerts — just so you see who needs a conversation, not blame.</span>
    <span data-th>เรียงตามจำนวนการแจ้งเตือน — ดูใครต้องคุยด้วย ไม่ใช่ไล่</span>
  </p>
  <div class="block" style="margin-top: 16px;">
    <table id="emp-table">
      <thead>
        <tr>
          <th><span data-en>Name</span><span data-th>ชื่อ</span></th>
          <th class="num"><span data-en>Shifts</span><span data-th>กะ</span></th>
          <th class="num"><span data-en>Receipts</span><span data-th>บิล</span></th>
          <th class="num"><span data-en>Alerts</span><span data-th>แจ้งเตือน</span></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
</section>

<!-- ============ ACTIONS ============ -->
<div class="actions">
  <button class="btn btn-primary" onclick="window.print()">
    <span data-en>Save as PDF</span>
    <span data-th>บันทึก PDF</span>
  </button>
  <button class="btn" onclick="document.body.classList.toggle('th')">
    <span data-en>ภาษาไทย</span>
    <span data-th>English</span>
  </button>
</div>

<footer>
  <span data-en>Generated from live data · {generated_at}</span>
  <span data-th>สร้างจากข้อมูลจริง · {generated_at}</span>
</footer>

</div>
</main>

<script>
const DATA = {data_json};
const fmtTHB = n => "฿" + Math.round(Number(n)).toLocaleString("en-US");
const fmtNum = n => Number(n).toLocaleString("en-US");
const fmtTime = iso => {{
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {{ day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }});
}};
const timeAgo = iso => {{
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff/60) + "m ago";
  if (diff < 86400) return Math.floor(diff/3600) + "h ago";
  return Math.floor(diff/86400) + "d ago";
}};

/* ----- Alerts: plain-language descriptions ----- */
const alertCopy = {{
  UNMATCHED_TRANSFER: {{
    emoji: "💸",
    en: p => ({{
      title: "Customer paid by transfer but the bank didn't see the money",
      desc: `Receipt ${{p.receipt_id}} · ${{fmtTHB(p.amount_thb)}} should have arrived from KBank`,
    }}),
    th: p => ({{
      title: "ลูกค้าโอนแต่ธนาคารยังไม่มีเงินเข้า",
      desc: `บิล ${{p.receipt_id}} · ${{fmtTHB(p.amount_thb)}} ควรเข้าบัญชี KBank`,
    }}),
  }},
  POSSIBLE_DUPLICATE_TRANSFER: {{
    emoji: "👯",
    en: p => ({{
      title: "Two bank deposits could match the same receipt",
      desc: `Receipt ${{p.receipt_id}} · ${{fmtTHB(p.amount_thb)}} — needs you to check`,
    }}),
    th: p => ({{
      title: "เงินเข้า 2 รายการอาจตรงกับบิลเดียวกัน",
      desc: `บิล ${{p.receipt_id}} · ${{fmtTHB(p.amount_thb)}} — ต้องตรวจสอบ`,
    }}),
  }},
  CASH_DISCREPANCY: {{
    emoji: "💰",
    en: p => ({{
      title: "Cash drawer was short at end of shift",
      desc: `Expected ${{fmtTHB(p.expected)}}, counted ${{fmtTHB(p.counted)}} — missing ${{fmtTHB(Math.abs(p.delta))}}`,
    }}),
    th: p => ({{
      title: "เงินสดในลิ้นชักไม่ครบตอนปิดกะ",
      desc: `ควรมี ${{fmtTHB(p.expected)}} · นับได้ ${{fmtTHB(p.counted)}} — ขาด ${{fmtTHB(Math.abs(p.delta))}}`,
    }}),
  }},
  INVENTORY_SHRINKAGE: {{
    emoji: "📦",
    en: p => ({{
      title: `${{Math.abs(p.delta_units)}} ${{p.name}} missing from inventory`,
      desc: `Counted on shelf, doesn't match what was sold`,
    }}),
    th: p => ({{
      title: `${{p.name}} หาย ${{Math.abs(p.delta_units)}} ชิ้น`,
      desc: `นับสต็อกแล้วไม่ตรงกับยอดขาย`,
    }}),
  }},
  VOID_BURST: {{
    emoji: "🚫",
    en: p => ({{
      title: "One employee voided lots of receipts quickly",
      desc: `${{p.void_count}} voids in ${{p.window_minutes}} minutes — worth a quick chat`,
    }}),
    th: p => ({{
      title: "พนักงานคนหนึ่งยกเลิกบิลถี่ผิดปกติ",
      desc: `ยกเลิก ${{p.void_count}} บิลใน ${{p.window_minutes}} นาที — ควรคุยดูก่อน`,
    }}),
  }},
  REFUND_SPIKE: {{
    emoji: "↩️",
    en: p => ({{ title: "Refunds are unusually high today", desc: `${{p.today_refunds}} refunds vs ${{p.avg_14d}} average` }}),
    th: p => ({{ title: "วันนี้คืนเงินเยอะกว่าปกติ", desc: `คืน ${{p.today_refunds}} ครั้ง ค่าเฉลี่ย ${{p.avg_14d}}` }}),
  }},
  EXCESSIVE_DISCOUNT: {{
    emoji: "🏷️",
    en: p => ({{ title: "A receipt got a very large discount", desc: `Receipt ${{p.receipt_id}} · ${{p.discount_pct}}% off (${{fmtTHB(p.discount_thb)}})` }}),
    th: p => ({{ title: "บิลหนึ่งได้ส่วนลดเยอะมาก", desc: `บิล ${{p.receipt_id}} · ลด ${{p.discount_pct}}% (${{fmtTHB(p.discount_thb)}})` }}),
  }},
  SMS_BRIDGE_DOWN: {{
    emoji: "📵",
    en: p => ({{ title: "KBank notification phone went offline", desc: `Silent for ${{p.silence_minutes}} minutes — we can't see new transfers in real time` }}),
    th: p => ({{ title: "มือถือรับ SMS KBank ขาดการเชื่อมต่อ", desc: `เงียบไป ${{p.silence_minutes}} นาที — ไม่เห็นการโอนแบบเรียลไทม์` }}),
  }},
}};

const feed = document.getElementById("alerts-feed");
if (DATA.alerts.length === 0) {{
  feed.innerHTML = `<div class="empty-state">
    <div style="font-size:32px;margin-bottom:8px;">✨</div>
    <div data-en>No open issues. Nice work.</div>
    <div data-th>ไม่มีปัญหาค้าง · เยี่ยม!</div>
  </div>`;
}} else {{
  DATA.alerts.forEach(a => {{
    const copy = alertCopy[a.alert_type] || {{
      emoji: "ℹ️",
      en: () => ({{ title: a.alert_type, desc: JSON.stringify(a.payload).slice(0, 80) }}),
      th: () => ({{ title: a.alert_type, desc: JSON.stringify(a.payload).slice(0, 80) }}),
    }};
    const en = copy.en(a.payload || {{}});
    const th = copy.th(a.payload || {{}});
    const impact = a.financial_impact_thb ? fmtTHB(a.financial_impact_thb) : "";

    feed.insertAdjacentHTML("beforeend", `
      <div class="alert">
        <div class="alert-emoji">${{copy.emoji}}</div>
        <div class="alert-body">
          <div class="alert-title">
            <span data-en>${{en.title}}</span>
            <span data-th>${{th.title}}</span>
          </div>
          <div class="alert-desc">
            <span data-en>${{en.desc}}</span>
            <span data-th>${{th.desc}}</span>
          </div>
          <div class="alert-meta">${{timeAgo(a.created_at)}}</div>
        </div>
        <div class="alert-impact">${{impact}}</div>
      </div>
    `);
  }});
}}

/* ----- Trend chart ----- */
const ctx = document.getElementById("trendChart").getContext("2d");
new Chart(ctx, {{
  type: "line",
  data: {{
    labels: DATA.trend.map(r => fmtTime(r.business_day).slice(0, 6)),
    datasets: [{{
      label: "Sales",
      data: DATA.trend.map(r => r.total_thb),
      borderColor: "#4d3680",
      backgroundColor: "rgba(77, 54, 128, 0.08)",
      fill: true, tension: 0.35, borderWidth: 2,
      pointRadius: 0, pointHoverRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{
        beginAtZero: true,
        ticks: {{ callback: v => fmtTHB(v), font: {{ size: 11 }}, color: "#9b9a97" }},
        grid: {{ color: "#ebebea", drawBorder: false }},
      }},
      x: {{
        grid: {{ display: false }},
        ticks: {{ font: {{ size: 11 }}, color: "#9b9a97", maxRotation: 0 }},
      }}
    }}
  }}
}});

/* ----- Matching table ----- */
const mtb = document.querySelector("#matching-table tbody");
DATA.matching.forEach(r => {{
  const statusClass = r.status === "VERIFIED" ? "verified"
                     : r.status === "UNMATCHED" ? "unmatched" : "duplicate";
  const statusLabelEn = r.status === "VERIFIED" ? "matched" : r.status === "UNMATCHED" ? "missing" : "duplicate?";
  const statusLabelTh = r.status === "VERIFIED" ? "ตรง" : r.status === "UNMATCHED" ? "ไม่พบ" : "ซ้ำ?";
  const amount = Number(r.transfer_amount || r.total);
  mtb.insertAdjacentHTML("beforeend", `
    <tr>
      <td class="mono">${{r.receipt_id}}</td>
      <td>${{fmtTime(r.timestamp)}}</td>
      <td class="num">${{fmtTHB(amount)}}</td>
      <td class="num"><span class="badge badge-${{statusClass}}">
        <span data-en>${{statusLabelEn}}</span><span data-th>${{statusLabelTh}}</span>
      </span></td>
    </tr>
  `);
}});

/* ----- Inventory table ----- */
const itb = document.querySelector("#inv-table tbody");
if (DATA.inv_loss.length === 0) {{
  document.getElementById("inv-block").innerHTML = `<div class="empty-state" style="padding:32px;color:var(--text-muted);">
    <div data-en>No items missing. Counts match sales.</div>
    <div data-th>ไม่มีสินค้าหาย · นับครบตรงกับยอดขาย</div>
  </div>`;
}} else {{
  DATA.inv_loss.forEach(r => {{
    itb.insertAdjacentHTML("beforeend", `
      <tr>
        <td><strong>${{r.name}}</strong><br><span class="mono">${{r.sku}}</span></td>
        <td class="num">${{fmtNum(Math.round(r.sold))}}</td>
        <td class="num pill-warn">${{Number(r.shrinkage_units).toFixed(0)}}</td>
      </tr>
    `);
  }});
}}

/* ----- Shifts table ----- */
const stb = document.querySelector("#shifts-table tbody");
DATA.shifts.forEach(r => {{
  const disc = Number(r.cash_discrepancy_thb || 0);
  const discClass = Math.abs(disc) >= 100 ? "pill-warn" : "pill-ok";
  const discStr = disc === 0 ? "—" : (disc > 0 ? "−" : "+") + fmtTHB(Math.abs(disc)).slice(1);
  stb.insertAdjacentHTML("beforeend", `
    <tr>
      <td>${{fmtTime(r.scheduled_start)}}</td>
      <td>${{r.employees || "—"}}</td>
      <td class="num">${{fmtTHB(r.revenue_thb || 0)}}</td>
      <td class="num ${{discClass}}">${{discStr}}</td>
    </tr>
  `);
}});

/* ----- Employees table ----- */
const etb = document.querySelector("#emp-table tbody");
DATA.employees.forEach(r => {{
  const alerts = Number(r.anomaly_alerts || 0);
  const alertClass = alerts >= 5 ? "pill-warn" : "pill-ok";
  etb.insertAdjacentHTML("beforeend", `
    <tr>
      <td><strong>${{r.name}}</strong></td>
      <td class="num">${{r.shifts_worked}}</td>
      <td class="num">${{r.transactions_handled}}</td>
      <td class="num ${{alertClass}}">${{alerts}}</td>
    </tr>
  `);
}});
</script>
</body>
</html>
"""


def main():
    print("Querying database…")
    data = fetch()
    print(f"  alerts={len(data['alerts'])}  matching={len(data['matching'])}  "
          f"shifts={len(data['shifts'])}  employees={len(data['employees'])}")

    now = datetime.now(BKK)
    html = render(data, now)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
