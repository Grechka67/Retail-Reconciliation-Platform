"""Live dashboard — centralised data + a clickable alerts inbox.

Routes:
    GET  /dashboard         -> the HTML app (tabbed, friendly, mobile-ok)
    GET  /dashboard/data    -> JSON the page fetches on load / refresh
Alerts are acknowledged via the existing POST /admin/alerts/{id}/ack.

Unlike scripts/generate_dashboard_html.py (a static snapshot), this serves
live data straight from Postgres every time the page loads or refreshes.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.db import engine

router = APIRouter()


def _fetch() -> dict:
    with engine.connect() as conn:
        health = conn.execute(text(
            "SELECT * FROM public_safe.store_health_score"
        )).mappings().first()

        trend = [dict(r) for r in conn.execute(text("""
            SELECT business_day, total_thb, cash_thb, transfer_thb
            FROM public_safe.daily_revenue ORDER BY business_day
        """)).mappings()]
        today = trend[-1] if trend else {}

        totals = conn.execute(text("""
            SELECT SUM(total_thb)::numeric AS total_revenue_30d,
                   SUM(receipt_count)::int AS receipts_30d
            FROM public_safe.daily_revenue
        """)).mappings().first()

        match_summary = conn.execute(text("""
            SELECT COUNT(*) FILTER (WHERE status='VERIFIED')           AS verified,
                   COUNT(*) FILTER (WHERE status='UNMATCHED')          AS unmatched,
                   COUNT(*) FILTER (WHERE status='POSSIBLE_DUPLICATE') AS duplicates
            FROM transfer_matches
        """)).mappings().first()

        # NOTE: id is selected so the UI can acknowledge each alert.
        alerts = [dict(r) for r in conn.execute(text("""
            SELECT id, severity, alert_type, payload, financial_impact_thb,
                   created_at, shift_id
            FROM alerts WHERE acked_at IS NULL
            ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
                     created_at DESC
        """)).mappings()]

        matching = [dict(r) for r in conn.execute(text("""
            SELECT receipt_id, timestamp, total, transfer_amount,
                   payment_method, status, time_delta_seconds
            FROM public_safe.live_payment_matching
            WHERE status IS NOT NULL
            ORDER BY CASE status WHEN 'UNMATCHED' THEN 0 WHEN 'POSSIBLE_DUPLICATE' THEN 1 ELSE 2 END,
                     timestamp DESC
            LIMIT 30
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
            FROM public_safe.shift_summary ORDER BY scheduled_start DESC LIMIT 10
        """)).mappings()]

        employees = [dict(r) for r in conn.execute(text("""
            SELECT name, transactions_handled, shifts_worked,
                   open_discrepancies, total_impact_thb, anomaly_alerts
            FROM public_safe.employee_accountability
            ORDER BY anomaly_alerts DESC, transactions_handled DESC
        """)).mappings()]

    return {
        "health": dict(health) if health else {},
        "today": dict(today) if today else {},
        "totals": dict(totals) if totals else {},
        "match_summary": dict(match_summary) if match_summary else {},
        "trend": trend, "alerts": alerts, "matching": matching,
        "inv_loss": inv_loss, "shifts": shifts, "employees": employees,
    }


@router.get("/dashboard/data")
def dashboard_data():
    return _fetch()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    return PAGE


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShopOS · Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  [data-th]{display:none}
  body.th [data-en]{display:none}
  body.th [data-th]{display:inline}
  :root{
    --bg:#fff7fb; --card:#ffffff; --ink:#3b3340; --muted:#8a8194;
    --line:#f0e6ef; --accent:#ff7eb6; --accent-ink:#a8326e;
    --mint:#d8f3e6; --mint-ink:#1f6b4a;
    --peach:#ffe7cf; --peach-ink:#9c5a1c;
    --rose:#ffe0e6; --rose-ink:#c0344c;
    --sky:#dcecff; --sky-ink:#2b5a9e;
    --lilac:#ece1ff; --lilac-ink:#6b46b8;
    --radius:18px; --shadow:0 6px 22px rgba(180,120,160,.10);
  }
  html,body{
    font-family:"Inter","Segoe UI","Noto Sans Thai","Sarabun",system-ui,sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.55;
    -webkit-font-smoothing:antialiased; font-size:15px;
  }
  .wrap{max-width:760px; margin:0 auto; padding:0 16px}

  /* top bar */
  header{position:sticky; top:0; z-index:20; background:rgba(255,247,251,.92);
    backdrop-filter:blur(8px); border-bottom:1px solid var(--line)}
  .bar{display:flex; align-items:center; justify-content:space-between; padding:14px 0; gap:12px}
  .brand{display:flex; align-items:center; gap:10px}
  .logo{width:34px;height:34px;border-radius:11px;background:var(--lilac);color:var(--lilac-ink);
    display:grid;place-items:center;font-weight:800;font-size:14px}
  .brand h1{font-size:16px;font-weight:700}
  .brand p{font-size:12px;color:var(--muted)}
  .refresh{border:1px solid var(--line);background:var(--card);border-radius:12px;
    padding:8px 12px;font:inherit;font-size:13px;font-weight:600;color:var(--ink);cursor:pointer}
  .refresh:active{transform:translateY(1px)}

  /* tabs */
  nav{position:sticky; top:62px; z-index:19; background:rgba(255,247,251,.92);
    backdrop-filter:blur(8px); border-bottom:1px solid var(--line)}
  .tabs{display:flex; gap:6px; padding:10px 0; overflow-x:auto; scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
  .tab{flex:0 0 auto; border:none; background:transparent; font:inherit; font-size:14px;
    font-weight:600; color:var(--muted); padding:8px 14px; border-radius:999px; cursor:pointer;
    display:flex; align-items:center; gap:7px; white-space:nowrap}
  .tab:hover{background:#fff}
  .tab.active{background:var(--accent); color:#fff}
  .tab .count{background:rgba(255,255,255,.35); color:inherit; font-size:11px; font-weight:800;
    min-width:20px; height:20px; padding:0 6px; border-radius:999px; display:grid; place-items:center}
  .tab:not(.active) .count{background:var(--rose); color:var(--rose-ink)}
  .tab .count.zero{background:var(--mint); color:var(--mint-ink)}

  main{padding:20px 0 90px}
  .panel{display:none; animation:fade .25s ease}
  .panel.active{display:block}
  @keyframes fade{from{opacity:0; transform:translateY(6px)}to{opacity:1; transform:none}}

  h2{font-size:19px;font-weight:700;margin-bottom:2px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13px;margin-bottom:16px}

  /* kpi */
  .kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:18px}
  .kpi{background:var(--card);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
  .kpi .k{font-size:12px;color:var(--muted);font-weight:600;display:flex;align-items:center;gap:6px}
  .kpi .v{font-size:26px;font-weight:800;margin-top:6px;letter-spacing:-.02em}
  .kpi .s{font-size:12px;color:var(--muted);margin-top:2px}
  .ring{--p:0;width:54px;height:54px;border-radius:50%;
    background:conic-gradient(var(--accent) calc(var(--p)*1%), var(--line) 0);
    display:grid;place-items:center;flex:0 0 auto}
  .ring span{width:42px;height:42px;border-radius:50%;background:var(--card);display:grid;place-items:center;
    font-weight:800;font-size:15px}
  .health{display:flex;align-items:center;gap:14px}

  .card{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow);padding:18px;margin-bottom:14px}
  .card h3{font-size:15px;font-weight:700;margin-bottom:10px}
  .chart{height:220px;position:relative}

  /* alerts */
  .alert{display:flex;gap:12px;align-items:flex-start;background:var(--card);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:14px 16px;margin-bottom:10px;border-left:5px solid var(--line);
    transition:opacity .25s,transform .25s}
  .alert.sev-WARN{border-left-color:var(--accent)}
  .alert.sev-CRITICAL{border-left-color:var(--rose-ink)}
  .alert.sev-INFO{border-left-color:var(--sky)}
  .alert.going{opacity:0;transform:translateX(40px)}
  .emoji{font-size:22px;line-height:1;flex:0 0 auto;padding-top:1px}
  .a-body{flex:1;min-width:0}
  .a-title{font-weight:700;font-size:14.5px;line-height:1.4}
  .a-desc{font-size:13px;color:var(--muted);margin-top:2px}
  .a-foot{display:flex;align-items:center;gap:10px;margin-top:9px;flex-wrap:wrap}
  .impact{font-weight:800;font-size:13px;color:var(--accent-ink);background:#fff0f6;
    padding:2px 9px;border-radius:999px}
  .ago{font-size:12px;color:var(--muted)}
  .done{margin-left:auto;border:none;background:var(--mint);color:var(--mint-ink);font:inherit;
    font-size:13px;font-weight:700;padding:7px 14px;border-radius:999px;cursor:pointer}
  .done:active{transform:translateY(1px)}
  .done:disabled{opacity:.5;cursor:default}

  /* tables */
  .twrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
    font-weight:700;padding:8px 12px 8px 0;border-bottom:1px solid var(--line)}
  td{padding:11px 12px 11px 0;border-bottom:1px solid var(--line)}
  tr:last-child td{border-bottom:none}
  .num{text-align:right;font-variant-numeric:tabular-nums;padding-right:0}
  th.num{text-align:right}
  .mono{font-family:"JetBrains Mono",Consolas,monospace;font-size:11.5px;color:var(--muted)}
  .badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700}
  .b-VERIFIED{background:var(--mint);color:var(--mint-ink)}
  .b-UNMATCHED{background:var(--rose);color:var(--rose-ink)}
  .b-POSSIBLE_DUPLICATE{background:var(--peach);color:var(--peach-ink)}
  .warn{color:var(--rose-ink);font-weight:700}
  .empty{text-align:center;padding:30px 16px;color:var(--muted)}
  .empty .big{font-size:34px;margin-bottom:8px}
  .toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(20px);
    background:var(--ink);color:#fff;padding:10px 18px;border-radius:999px;font-size:13px;font-weight:600;
    opacity:0;transition:.25s;z-index:50}
  .toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  @media(max-width:520px){.kpis{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><div class="wrap bar">
  <div class="brand">
    <div class="logo">OT</div>
    <div><h1>ShopOS</h1><p id="stamp"></p></div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="refresh" onclick="toggleLang()"><span data-en>ไทย</span><span data-th>EN</span></button>
    <button class="refresh" onclick="load()">↻ <span data-en>Refresh</span><span data-th>รีเฟรช</span></button>
  </div>
</div></header>

<nav><div class="wrap"><div class="tabs" id="tabs">
  <button class="tab active" data-tab="overview">🏠 <span data-en>Overview</span><span data-th>ภาพรวม</span></button>
  <button class="tab" data-tab="alerts">🔔 <span data-en>Alerts</span><span data-th>แจ้งเตือน</span> <span class="count zero" id="alertCount">0</span></button>
  <button class="tab" data-tab="money">💸 <span data-en>Money</span><span data-th>เงิน</span></button>
  <button class="tab" data-tab="stock">📦 <span data-en>Stock</span><span data-th>สต็อก</span></button>
  <button class="tab" data-tab="team">🧑‍🤝‍🧑 <span data-en>Team</span><span data-th>ทีม</span></button>
</div></div></nav>

<main><div class="wrap">
  <!-- OVERVIEW -->
  <section class="panel active" id="overview">
    <h2><span data-en>How's the store?</span><span data-th>วันนี้ร้านเป็นยังไง?</span></h2>
    <p class="sub" id="ovSub">—</p>
    <div class="kpis" id="kpis"></div>
    <div class="card"><h3><span data-en>Last 30 days</span><span data-th>30 วันที่ผ่านมา</span></h3>
      <div class="chart"><canvas id="trend"></canvas></div></div>
  </section>

  <!-- ALERTS -->
  <section class="panel" id="alerts">
    <h2><span data-en>Needs your attention</span><span data-th>เรื่องที่ต้องดู</span></h2>
    <p class="sub"><span data-en>Tap “Mark done” when you've handled one — it clears for everyone.</span>
      <span data-th>กด“เรียบร้อย”เมื่อจัดการแล้ว — จะหายไปสำหรับทุกคน</span></p>
    <div id="feed"></div>
  </section>

  <!-- MONEY -->
  <section class="panel" id="money">
    <h2><span data-en>Transfer payments</span><span data-th>การชำระโอน</span></h2>
    <p class="sub"><span data-en>Every transfer checked against your KBank account. Problems first.</span>
      <span data-th>ตรวจการโอนทุกครั้งกับบัญชี KBank · ปัญหาขึ้นก่อน</span></p>
    <div class="card"><div class="twrap"><table id="matchTable">
      <thead><tr>
        <th><span data-en>Receipt</span><span data-th>บิล</span></th>
        <th><span data-en>When</span><span data-th>เวลา</span></th>
        <th class="num"><span data-en>Amount</span><span data-th>จำนวน</span></th>
        <th class="num"><span data-en>Status</span><span data-th>สถานะ</span></th>
      </tr></thead><tbody></tbody></table></div></div>
  </section>

  <!-- STOCK -->
  <section class="panel" id="stock">
    <h2><span data-en>Inventory</span><span data-th>สินค้าคงเหลือ</span></h2>
    <p class="sub"><span data-en>Items where the shelf count doesn't match what was sold.</span>
      <span data-th>สินค้าที่นับแล้วไม่ตรงกับยอดขาย</span></p>
    <div class="card" id="stockCard"><div class="twrap"><table id="invTable">
      <thead><tr>
        <th><span data-en>Product</span><span data-th>สินค้า</span></th>
        <th class="num"><span data-en>Sold</span><span data-th>ขาย</span></th>
        <th class="num"><span data-en>Missing</span><span data-th>หาย</span></th>
      </tr></thead><tbody></tbody></table></div></div>
  </section>

  <!-- TEAM -->
  <section class="panel" id="team">
    <h2><span data-en>Recent shifts</span><span data-th>กะล่าสุด</span></h2>
    <p class="sub"><span data-en>Last shifts and the cash difference at close.</span>
      <span data-th>กะล่าสุดและผลต่างเงินสดตอนปิดกะ</span></p>
    <div class="card"><div class="twrap"><table id="shiftTable">
      <thead><tr>
        <th><span data-en>When</span><span data-th>เวลา</span></th>
        <th><span data-en>Staff</span><span data-th>พนักงาน</span></th>
        <th class="num"><span data-en>Sales</span><span data-th>ยอดขาย</span></th>
        <th class="num"><span data-en>Cash diff</span><span data-th>เงินสดต่าง</span></th>
      </tr></thead><tbody></tbody></table></div></div>
    <h2 style="margin-top:22px"><span data-en>Your team</span><span data-th>พนักงานของคุณ</span></h2>
    <p class="sub"><span data-en>Sorted by alerts — who to check in with, not blame.</span>
      <span data-th>เรียงตามการแจ้งเตือน — ใครต้องคุยด้วย ไม่ใช่ไล่</span></p>
    <div class="card"><div class="twrap"><table id="empTable">
      <thead><tr>
        <th><span data-en>Name</span><span data-th>ชื่อ</span></th>
        <th class="num"><span data-en>Shifts</span><span data-th>กะ</span></th>
        <th class="num"><span data-en>Receipts</span><span data-th>บิล</span></th>
        <th class="num"><span data-en>Alerts</span><span data-th>เตือน</span></th>
      </tr></thead><tbody></tbody></table></div></div>
  </section>
</div></main>

<div class="toast" id="toast"></div>

<script>
const THB = n => "฿" + Math.round(Number(n||0)).toLocaleString("en-US");
const NUM = n => Number(n||0).toLocaleString("en-US");
const fmtTime = iso => iso ? new Date(iso).toLocaleString("en-GB",
  {day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}) : "—";
const ago = iso => {
  if(!iso) return "";
  const d=(Date.now()-new Date(iso))/1000;
  if(d<60)return "just now"; if(d<3600)return Math.floor(d/60)+"m ago";
  if(d<86400)return Math.floor(d/3600)+"h ago"; return Math.floor(d/86400)+"d ago";
};
const ALERT = {
  UNMATCHED_TRANSFER:{e:"💸",
    en:p=>["Customer paid by transfer but the bank didn't see it",`Receipt ${p.receipt_id} · ${THB(p.amount_thb)} should have arrived from KBank`],
    th:p=>["ลูกค้าโอนแต่ธนาคารยังไม่มีเงินเข้า",`บิล ${p.receipt_id} · ${THB(p.amount_thb)} ควรเข้าบัญชี KBank`]},
  POSSIBLE_DUPLICATE_TRANSFER:{e:"👯",
    en:p=>["Two deposits could match the same receipt",`Receipt ${p.receipt_id} · ${THB(p.amount_thb)} — please check`],
    th:p=>["เงินเข้า 2 รายการอาจตรงกับบิลเดียว",`บิล ${p.receipt_id} · ${THB(p.amount_thb)} — โปรดตรวจสอบ`]},
  CASH_DISCREPANCY:{e:"💰",
    en:p=>["Cash drawer was short at close",`Expected ${THB(p.expected)}, counted ${THB(p.counted)} — missing ${THB(Math.abs(p.delta))}`],
    th:p=>["เงินสดในลิ้นชักไม่ครบตอนปิดกะ",`ควรมี ${THB(p.expected)} นับได้ ${THB(p.counted)} — ขาด ${THB(Math.abs(p.delta))}`]},
  INVENTORY_SHRINKAGE:{e:"📦",
    en:p=>[`${Math.abs(p.delta_units)} ${p.name} missing`,"Shelf count doesn't match what was sold"],
    th:p=>[`${p.name} หาย ${Math.abs(p.delta_units)} ชิ้น`,"นับสต็อกแล้วไม่ตรงกับยอดขาย"]},
  VOID_BURST:{e:"🚫",
    en:p=>["One employee voided lots of receipts fast",`${p.void_count} voids in ${p.window_minutes} min — worth a quick chat`],
    th:p=>["พนักงานยกเลิกบิลถี่ผิดปกติ",`ยกเลิก ${p.void_count} บิลใน ${p.window_minutes} นาที — ควรคุยดู`]},
  REFUND_SPIKE:{e:"↩️",
    en:p=>["Refunds unusually high today",`${p.today_refunds} vs ${p.avg_14d} avg`],
    th:p=>["วันนี้คืนเงินเยอะกว่าปกติ",`คืน ${p.today_refunds} ครั้ง เฉลี่ย ${p.avg_14d}`]},
  EXCESSIVE_DISCOUNT:{e:"🏷️",
    en:p=>["A receipt got a very large discount",`Receipt ${p.receipt_id} · ${p.discount_pct}% off (${THB(p.discount_thb)})`],
    th:p=>["บิลหนึ่งได้ส่วนลดเยอะมาก",`บิล ${p.receipt_id} · ลด ${p.discount_pct}% (${THB(p.discount_thb)})`]},
  SMS_BRIDGE_DOWN:{e:"📵",
    en:p=>["KBank SMS phone went offline",`Silent ${p.silence_minutes} min`],
    th:p=>["มือถือรับ SMS KBank หลุด",`เงียบไป ${p.silence_minutes} นาที`]},
};
let chart;
const isTH=()=>document.body.classList.contains("th");

function toast(en,th){const t=document.getElementById("toast");t.textContent=isTH()?th:en;
  t.classList.add("show");setTimeout(()=>t.classList.remove("show"),1800);}

function toggleLang(){document.body.classList.toggle("th");}

// tab switching
document.getElementById("tabs").addEventListener("click",e=>{
  const b=e.target.closest(".tab"); if(!b)return;
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t===b));
  document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("active",p.id===b.dataset.tab));
  window.scrollTo({top:0,behavior:"smooth"});
});

async function ack(id,btn){
  btn.disabled=true; btn.innerHTML="…";
  try{
    const r=await fetch(`/admin/alerts/${id}/ack`,{method:"POST",
      headers:{"Content-Type":"application/json"},body:"{}"});
    if(!r.ok)throw 0;
    const card=btn.closest(".alert"); card.classList.add("going");
    setTimeout(()=>{card.remove(); updateAlertCount(); maybeEmpty();},250);
    toast("Marked done ✓","เรียบร้อย ✓");
  }catch{btn.disabled=false;
    btn.innerHTML='<span data-en>Mark done</span><span data-th>เรียบร้อย</span>';
    toast("Couldn't save — try again","บันทึกไม่ได้ — ลองใหม่");}
}
function updateAlertCount(){
  const n=document.querySelectorAll("#feed .alert").length;
  const c=document.getElementById("alertCount");
  c.textContent=n; c.classList.toggle("zero",n===0);
}
const EMPTY_ALERTS=`<div class="empty"><div class="big">✨</div>
  <span data-en>All clear. Nice work.</span><span data-th>ไม่มีปัญหาค้าง · เยี่ยม!</span></div>`;

function maybeEmpty(){
  if(document.querySelectorAll("#feed .alert").length===0)
    document.getElementById("feed").innerHTML=EMPTY_ALERTS;
}

function renderAlerts(alerts){
  const feed=document.getElementById("feed");
  if(!alerts.length){feed.innerHTML=EMPTY_ALERTS; updateAlertCount(); return;}
  feed.innerHTML=alerts.map(a=>{
    const c=ALERT[a.alert_type]||{e:"ℹ️",en:()=>[a.alert_type,""],th:()=>[a.alert_type,""]};
    const p=a.payload||{}; const en=c.en(p), th=c.th(p);
    const impact=a.financial_impact_thb?`<span class="impact">${THB(a.financial_impact_thb)}</span>`:"";
    return `<div class="alert sev-${a.severity}">
      <div class="emoji">${c.e}</div>
      <div class="a-body">
        <div class="a-title"><span data-en>${en[0]}</span><span data-th>${th[0]}</span></div>
        <div class="a-desc"><span data-en>${en[1]}</span><span data-th>${th[1]}</span></div>
        <div class="a-foot">${impact}<span class="ago">${ago(a.created_at)}</span>
          <button class="done" onclick="ack(${a.id},this)">
            <span data-en>Mark done</span><span data-th>เรียบร้อย</span></button></div>
      </div></div>`;
  }).join("");
  updateAlertCount();
}

function renderKpis(d){
  const h=d.health||{}, t=d.today||{}, m=d.match_summary||{}, tot=d.totals||{};
  const score=Math.round(h.score_pct||0);
  const matched=(m.verified||0), miss=(m.unmatched||0), dup=(m.duplicates||0);
  const pct=Math.round(100*matched/Math.max(1,matched+miss+dup));
  const word=score>=80?["Healthy","ดี"]:score>=60?["Watch","เฝ้าดู"]:["Action","ต้องแก้"];
  document.getElementById("ovSub").innerHTML=
    `<span data-en>${NUM(t.receipt_count)} receipts today · ${THB(t.total_thb)} in sales</span>`+
    `<span data-th>วันนี้ ${NUM(t.receipt_count)} บิล · ขาย ${THB(t.total_thb)}</span>`;
  document.getElementById("kpis").innerHTML=`
    <div class="kpi"><div class="k">💚 <span data-en>Store health</span><span data-th>สุขภาพร้าน</span></div>
      <div class="health"><div class="ring" style="--p:${score}"><span>${score}</span></div>
        <div><div class="v" style="font-size:18px"><span data-en>${word[0]}</span><span data-th>${word[1]}</span></div>
        <div class="s"><span data-en>out of 100</span><span data-th>จาก 100</span></div></div></div></div>
    <div class="kpi"><div class="k">💸 <span data-en>Today's revenue</span><span data-th>ยอดขายวันนี้</span></div>
      <div class="v">${THB(t.total_thb)}</div>
      <div class="s"><span data-en>cash ${THB(t.cash_thb)} · transfer ${THB(t.transfer_thb)}</span>
        <span data-th>เงินสด ${THB(t.cash_thb)} · โอน ${THB(t.transfer_thb)}</span></div></div>
    <div class="kpi"><div class="k">🔁 <span data-en>Transfers matched</span><span data-th>โอนยืนยันแล้ว</span></div>
      <div class="v">${pct}%</div>
      <div class="s"><span data-en>${matched} verified · ${miss} missing</span>
        <span data-th>ยืนยัน ${matched} · ไม่พบ ${miss}</span></div></div>
    <div class="kpi"><div class="k">🗓️ <span data-en>Last 30 days</span><span data-th>30 วันที่ผ่านมา</span></div>
      <div class="v">${THB(tot.total_revenue_30d)}</div>
      <div class="s"><span data-en>${NUM(tot.receipts_30d)} receipts</span>
        <span data-th>${NUM(tot.receipts_30d)} บิล</span></div></div>`;
}

function renderTrend(trend){
  const ctx=document.getElementById("trend").getContext("2d");
  if(chart)chart.destroy();
  chart=new Chart(ctx,{type:"line",data:{
    labels:trend.map(r=>fmtTime(r.business_day).slice(0,6)),
    datasets:[{data:trend.map(r=>r.total_thb),borderColor:"#ff7eb6",
      backgroundColor:"rgba(255,126,182,.12)",fill:true,tension:.35,borderWidth:2,
      pointRadius:0,pointHoverRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{y:{beginAtZero:true,ticks:{callback:v=>THB(v),font:{size:10},color:"#8a8194"},
        grid:{color:"#f0e6ef"}},x:{grid:{display:false},
        ticks:{font:{size:10},color:"#8a8194",maxRotation:0,autoSkipPadding:14}}}}});
}

function renderTables(d){
  const ST={VERIFIED:["matched","ตรง"],UNMATCHED:["missing","ไม่พบ"],POSSIBLE_DUPLICATE:["duplicate?","ซ้ำ?"]};
  document.querySelector("#matchTable tbody").innerHTML=d.matching.map(r=>{
    const amt=Number(r.transfer_amount||r.total); const s=ST[r.status]||[r.status,r.status];
    return `<tr><td class="mono">${r.receipt_id}</td><td>${fmtTime(r.timestamp)}</td>
      <td class="num">${THB(amt)}</td>
      <td class="num"><span class="badge b-${r.status}"><span data-en>${s[0]}</span><span data-th>${s[1]}</span></span></td></tr>`;}).join("")
    || `<tr><td colspan="4" class="empty"><span data-en>No transfer payments yet.</span><span data-th>ยังไม่มีการโอน</span></td></tr>`;

  const inv=d.inv_loss;
  if(!inv.length)document.getElementById("stockCard").innerHTML=
    `<div class="empty"><div class="big">📦</div><span data-en>No items missing. Counts match sales.</span><span data-th>ไม่มีสินค้าหาย · นับครบ</span></div>`;
  else document.querySelector("#invTable tbody").innerHTML=inv.map(r=>
    `<tr><td><strong>${r.name}</strong><br><span class="mono">${r.sku}</span></td>
      <td class="num">${NUM(Math.round(r.sold))}</td>
      <td class="num warn">${Number(r.shrinkage_units).toFixed(0)}</td></tr>`).join("");

  document.querySelector("#shiftTable tbody").innerHTML=d.shifts.map(r=>{
    const disc=Number(r.cash_discrepancy_thb||0);
    const cls=Math.abs(disc)>=100?"warn":"";
    const s=disc===0?"—":(disc>0?"−":"+")+THB(Math.abs(disc)).slice(1);
    return `<tr><td>${fmtTime(r.scheduled_start)}</td><td>${r.employees||"—"}</td>
      <td class="num">${THB(r.revenue_thb)}</td><td class="num ${cls}">${s}</td></tr>`;}).join("");

  document.querySelector("#empTable tbody").innerHTML=d.employees.map(r=>{
    const al=Number(r.anomaly_alerts||0);
    return `<tr><td><strong>${r.name}</strong></td><td class="num">${r.shifts_worked}</td>
      <td class="num">${r.transactions_handled}</td>
      <td class="num ${al>=5?"warn":""}">${al}</td></tr>`;}).join("");
}

async function load(){
  const stamp=document.getElementById("stamp");
  stamp.innerHTML='<span data-en>refreshing…</span><span data-th>กำลังโหลด…</span>';
  try{
    const d=await(await fetch("/dashboard/data")).json();
    renderKpis(d); renderTrend(d.trend); renderAlerts(d.alerts); renderTables(d);
    const t=new Date().toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"});
    stamp.innerHTML=`<span data-en>live · ${t}</span><span data-th>อัปเดต · ${t}</span>`;
  }catch(e){stamp.innerHTML='<span data-en>couldn\'t load data</span><span data-th>โหลดข้อมูลไม่ได้</span>';}
}
load();
</script>
</body>
</html>
"""
