"""Weekly basket UI.

    .venv/bin/python buyer_history/examples/weekly_basket_app.py
    .venv/bin/python buyer_history/examples/weekly_basket_app.py "transaction data/…​.xlsx"

Plan the week from the learned profile, tick the lines you want, and send them to
a real Weee! cart. Every approved line still passes through the Decision Engine
before the browser sees it.

The web layer is stdlib only. The cart button additionally needs Pydantic and
Playwright; without them the page still plans, and only that button is disabled.
"""

from __future__ import annotations

import errno
import json
import sys
import threading
import uuid
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
for _pkg in ("buyer_history", "contracts", "mandate_engine", "weee_cart"):
    sys.path.insert(0, str(ROOT / _pkg / "src"))

from buyer_history import build_profile_from_workbook  # noqa: E402
from buyer_history.basket import suggest_weekly_basket  # noqa: E402

try:
    from buyer_history.contract import to_contract_profile
    from mandatelab_weee_cart import (
        BrowserWorker,
        WeeeCartExecutor,
        approved_lines,
        gate_basket,
    )

    BROWSER = BrowserWorker()
    CART_READY = True
    CART_ERROR = ""
except Exception as exc:  # pragma: no cover
    BROWSER = None
    CART_READY = False
    CART_ERROR = str(exc)

FIXTURE = ROOT / "buyer_history" / "fixtures" / "synthetic_household.xlsx"
PORT = 8765
TODAY = date(2026, 8, 16)
PATH_A_URL = "http://127.0.0.1:5173"

_paths = [a for a in sys.argv[1:] if not a.startswith("--")]
WORKBOOK = Path(_paths[0]) if _paths else FIXTURE
for _arg in sys.argv[1:]:
    if _arg.startswith("--today="):
        TODAY = date.fromisoformat(_arg.split("=", 1)[1])
    elif _arg.startswith("--path-a-url="):
        PATH_A_URL = _arg.split("=", 1)[1]

print(f"Loading profile from {WORKBOOK.name} …")
BUNDLE = build_profile_from_workbook(WORKBOOK, buyer_id="household", as_of=TODAY)
print(
    f"  {len(BUNDLE.transactions)} transactions, "
    f"{len(BUNDLE.item_profiles)} item profiles, "
    f"{len(BUNDLE.category_profiles)} categories"
)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weekly basket</title>
<style>
  :root {
    --bg:#f4f6f9;      --panel:#ffffff;   --panel-2:#eef1f6;
    --line:#dfe4ec;    --line-soft:#eaeef4;
    --ink:#111823;     --ink-2:#48546a;   --ink-3:#7b8798;
    --brand:#2f4bd8;   --brand-ink:#ffffff; --brand-soft:#e7ebfc;
    --ok:#0d6b55;      --ok-bg:#dcefe8;
    --warn:#8a5709;    --warn-bg:#f7ead2;
    --stop:#a32f2f;    --stop-bg:#f9e3e3;
    --shadow:0 1px 2px rgba(17,24,35,.05), 0 8px 24px -12px rgba(17,24,35,.16);
    --r:10px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#0d1015;    --panel:#161b23;   --panel-2:#1d232c;
      --line:#2a323d;  --line-soft:#222933;
      --ink:#e8ecf3;   --ink-2:#a6b2c2;   --ink-3:#75808f;
      --brand:#8ba3ff; --brand-ink:#0d1015; --brand-soft:#1c2440;
      --ok:#4fd0ab;    --ok-bg:#10302a;
      --warn:#e6b465;  --warn-bg:#342814;
      --stop:#ef8a8a;  --stop-bg:#381d1d;
      --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
    }
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  }
  .wrap { max-width:760px; margin:0 auto; padding:40px 20px 150px; }

  .eyebrow {
    font:11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
    letter-spacing:.16em; text-transform:uppercase; color:var(--ink-3);
    margin-bottom:10px;
  }
  h1 { margin:0 0 6px; font-size:clamp(26px,4.4vw,34px); letter-spacing:-.022em; line-height:1.15; }
  .lede { margin:0; color:var(--ink-2); max-width:54ch; }

  .btn {
    appearance:none; border:1px solid transparent; border-radius:8px;
    padding:11px 18px; font-size:14.5px; font-weight:600; cursor:pointer;
    font-family:inherit; transition:filter .15s, transform .06s, opacity .15s;
  }
  .btn:active { transform:translateY(1px); }
  .btn:focus-visible { outline:2px solid var(--brand); outline-offset:2px; }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  a.btn { text-decoration:none; display:inline-block; }
  .btn-primary { background:var(--brand); color:var(--brand-ink); }
  .btn-primary:hover:not(:disabled) { filter:brightness(1.08); }
  .btn-ghost { background:var(--panel); color:var(--ink); border-color:var(--line); }
  .btn-ghost:hover:not(:disabled) { background:var(--panel-2); }
  .btn-sm { padding:7px 12px; font-size:13px; font-weight:500; border-radius:7px; }

  .toolbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:22px 0 8px; }
  .status { font-size:12.5px; color:var(--ink-3); margin:8px 0 0; min-height:18px; }
  .status b { color:var(--ok); font-weight:600; }

  .tabs { display:flex; gap:4px; margin:0 0 22px; border-bottom:1px solid var(--line); }
  .tab {
    appearance:none; background:none; border:0; border-bottom:2px solid transparent;
    padding:10px 14px; font:inherit; font-size:14px; font-weight:560;
    color:var(--ink-3); cursor:pointer; margin-bottom:-1px;
  }
  .tab:hover { color:var(--ink-2); }
  .tab.on { color:var(--brand); border-bottom-color:var(--brand); }
  .tab:focus-visible { outline:2px solid var(--brand); outline-offset:-3px; }
  a.tab { text-decoration:none; }

  .summary {
    display:grid; grid-template-columns:repeat(auto-fit,minmax(112px,1fr));
    background:var(--panel); border:1px solid var(--line); border-radius:var(--r);
    box-shadow:var(--shadow); margin:26px 0 18px; overflow:hidden;
  }
  .summary > div { padding:15px 16px; border-right:1px solid var(--line-soft); }
  .summary > div:last-child { border-right:0; }
  .summary .n {
    display:block; font:22px/1.15 ui-monospace,SFMono-Regular,Menlo,monospace;
    font-variant-numeric:tabular-nums; letter-spacing:-.02em;
  }
  .summary .l {
    display:block; margin-top:3px; font:10px/1 ui-monospace,monospace;
    letter-spacing:.11em; text-transform:uppercase; color:var(--ink-3);
  }

  .group { margin-top:22px; }
  .group-head {
    display:flex; justify-content:space-between; align-items:baseline; gap:10px;
    padding:0 4px 8px; border-bottom:1px solid var(--line);
  }
  .group-head h2 { margin:0; font-size:14px; letter-spacing:.01em; }
  .group-head span {
    font:12px/1 ui-monospace,monospace; color:var(--ink-3);
    font-variant-numeric:tabular-nums;
  }
  .rows { list-style:none; margin:10px 0 0; padding:0; display:flex; flex-direction:column; gap:7px; }
  .card {
    background:var(--panel); border:1px solid var(--line); border-radius:var(--r);
    box-shadow:var(--shadow); overflow:hidden; transition:opacity .15s, border-color .15s;
  }
  .card.off { opacity:.45; }
  .card:focus-within { border-color:var(--brand); }
  .line { display:grid; grid-template-columns:auto 1fr auto auto; gap:12px; align-items:center; padding:12px 14px; }
  .line input[type=checkbox] { width:17px; height:17px; accent-color:var(--brand); cursor:pointer; margin:0; }
  .who { min-width:0; cursor:pointer; }
  .nm { font-weight:600; letter-spacing:-.005em; }
  .nm .q {
    font:11.5px/1 ui-monospace,monospace; color:var(--ink-3);
    margin-left:6px; font-variant-numeric:tabular-nums;
  }
  .sub { font-size:12.5px; color:var(--ink-3); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .amt { font:14.5px/1 ui-monospace,monospace; font-variant-numeric:tabular-nums; }
  .chip {
    font:10px/1 ui-monospace,monospace; letter-spacing:.06em;
    padding:4px 7px; border-radius:5px; white-space:nowrap;
  }
  .t-good { color:var(--ok); background:var(--ok-bg); }
  .t-warn { color:var(--warn); background:var(--warn-bg); }
  .t-bad  { color:var(--stop); background:var(--stop-bg); }
  .t-flat { color:var(--ink-3); background:var(--panel-2); }
  .OVERDUE, .BLOCK { color:var(--stop); background:var(--stop-bg); }
  .STAPLE, .APPROVE, .ADDED, .DRY_RUN { color:var(--ok); background:var(--ok-bg); }
  .DUE, .REVIEW, .NO_MATCH, .PRICE_ABOVE_LIMIT, .NOT_APPROVED,
  .BROWSER_UNAVAILABLE, .ADD_BUTTON_NOT_FOUND { color:var(--warn); background:var(--warn-bg); }
  .why {
    padding:11px 14px 13px 43px; border-top:1px solid var(--line-soft);
    font-size:12.5px; color:var(--ink-2); background:var(--panel-2);
  }
  .why ul { margin:0; padding-left:15px; display:flex; flex-direction:column; gap:4px; }
  .why .dim { color:var(--ink-3); font-style:italic; }
  .disclose {
    background:none; border:0; padding:0; color:var(--ink-3); cursor:pointer;
    font:11px/1 ui-monospace,monospace; text-decoration:underline; text-underline-offset:3px;
  }
  .disclose:hover { color:var(--brand); }

  .dock {
    position:fixed; left:0; right:0; bottom:0; z-index:20;
    background:color-mix(in srgb, var(--panel) 92%, transparent);
    backdrop-filter:blur(10px); border-top:1px solid var(--line);
    padding:12px 20px; display:none;
  }
  .dock.on { display:block; }
  .dock-in {
    max-width:760px; margin:0 auto; display:flex; gap:12px;
    align-items:center; justify-content:space-between; flex-wrap:wrap;
  }
  .dock .count { font-size:13.5px; color:var(--ink-2); }
  .dock .count b { color:var(--ink); font-variant-numeric:tabular-nums; }
  .dock .right { display:flex; gap:10px; align-items:center; }
  .peek { font-size:12.5px; color:var(--ink-2); display:flex; gap:6px; align-items:center; cursor:pointer; }

  .note {
    margin:18px 0 0; padding:13px 15px; border-radius:var(--r); font-size:13.5px;
    background:var(--brand-soft); border:1px solid var(--line); color:var(--ink);
  }
  .note.warn { background:var(--warn-bg); }
  .note a { color:var(--brand); }
  .empty { color:var(--ink-3); padding:26px 4px; }
  .help { margin-top:16px; font-size:13px; color:var(--ink-2); }
  .help summary { cursor:pointer; color:var(--brand); }
  .help p { max-width:60ch; }
  code { font:12.5px ui-monospace,monospace; background:var(--panel-2); padding:1px 5px; border-radius:4px; }
  footer {
    margin-top:34px; padding-top:14px; border-top:1px solid var(--line);
    font:11px/1.7 ui-monospace,monospace; color:var(--ink-3);
  }
  .bar { height:4px; background:var(--panel-2); border-radius:3px; overflow:hidden; margin:10px 0 4px; }
  .bar i { display:block; height:100%; background:var(--brand); transition:width .3s ease; }
  .spin { display:inline-block; animation:sp 1s linear infinite; }
  @keyframes sp { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion:reduce) { .spin { animation:none; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">MandateLab</div>

  <nav class="tabs">
    <button class="tab on" data-tab="how">How</button>
    <a class="tab" href="__PATH_A_URL__">Path A &middot; new buyer</a>
    <button class="tab" data-tab="b">Path B &middot; existing buyer</button>
  </nav>

  <section id="pane-how">
    <h1>How MandateLab works</h1>
    <p class="lede">It learns what &ldquo;best&rdquo; means for you, turns that
    into an explicit mandate, and only then lets an agent add to a cart.
    Nothing is checked out without you.</p>

    <div class="toolbar">
      <a class="btn btn-primary" href="__PATH_A_URL__">Start as a new buyer</a>
      <button class="btn btn-ghost" data-goto="b">Plan this week</button>
    </div>

    <section class="group">
      <div class="group-head"><h2>Two ways in</h2></div>
      <ul class="rows">
        <li class="card">
          <div class="line" style="grid-template-columns:1fr auto">
            <div class="who">
              <div class="nm">Path A &middot; new buyer</div>
              <div class="sub">Five product comparisons. Enough to build the same
              profile the engine consumes.</div>
            </div>
            <a class="btn btn-ghost btn-sm" href="__PATH_A_URL__">Open</a>
          </div>
        </li>
        <li class="card">
          <div class="line" style="grid-template-columns:1fr auto">
            <div class="who">
              <div class="nm">Path B &middot; existing buyer</div>
              <div class="sub">Purchase history in, staples due this week out,
              then into a real Weee! cart.</div>
            </div>
            <button class="btn btn-ghost btn-sm" data-goto="b">Open</button>
          </div>
        </li>
      </ul>
    </section>

    <p class="note">Every approved line still passes through the Decision Engine
    before the browser sees it. The agent only ever adds to the cart.</p>

    <details class="help">
      <summary>How the browser works</summary>
      <p>The first time you add items, a Chrome window opens and asks you to sign in
      to Weee!. That sign-in is kept in a private profile at
      <code>~/.mandatelab/weee-profile</code>, so every run after that goes straight
      to your cart &mdash; no flags, no relaunching.</p>
      <p>The agent never sees your password, and it only ever adds to the cart:
      there is no checkout path anywhere in the code, so nothing can be bought
      without you.</p>
    </details>
  </section>

  <section id="pane-b" hidden>
  <h1>What do we need this week?</h1>
  <p class="lede">Reads the learned purchase profile, works out which staples come
  due in the next seven days, then sends the ones you approve to your Weee! cart.</p>

  <div class="toolbar">
    <button class="btn btn-primary" id="plan">Plan this week</button>
    <button class="btn btn-ghost btn-sm" id="selall" hidden>Approve all</button>
    <button class="btn btn-ghost btn-sm" id="selnone" hidden>Clear all</button>
  </div>
  <p class="status" id="status">&nbsp;</p>

  <div id="out"></div>
  <div id="cartout"></div>

  </section>
  <footer id="foot"></footer>
</div>

<div class="dock" id="dock">
  <div class="dock-in">
    <div class="count"><b id="dockN">0</b> selected &middot; <b id="dockT">$0.00</b></div>
    <div class="right">
      <label class="peek"><input type="checkbox" id="dry"> Preview only</label>
      <button class="btn btn-primary" id="send">Add to Weee! cart</button>
    </div>
  </div>
</div>

<script>
const CART_READY = window.__CART_READY__ === true;
const $ = (id) => document.getElementById(id);
const out = $('out'), cartOut = $('cartout'), statusEl = $('status'), foot = $('foot');
const dock = $('dock');
let BASKET = null;
const chosen = new Set();

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
const money = (n) => '$' + Number(n).toFixed(2);

/* Plain words, not enum names: the buyer should be able to read the outcome. */
const LABEL = {
  ADDED: 'Added',
  DRY_RUN: 'Would add',
  OUT_OF_STOCK: 'Sold out',
  NO_MATCH: 'Not found',
  PRICE_ABOVE_LIMIT: 'Price too high',
  ADD_BUTTON_NOT_FOUND: "Couldn't add",
  NOT_APPROVED: 'Not approved',
  BROWSER_UNAVAILABLE: 'Browser problem',
  APPROVE: 'Approved',
  REVIEW: 'Needs you',
  BLOCK: 'Blocked',
};
const TONE = {
  ADDED: 'good', DRY_RUN: 'good', APPROVE: 'good',
  OUT_OF_STOCK: 'flat', NO_MATCH: 'flat', NOT_APPROVED: 'flat',
  PRICE_ABOVE_LIMIT: 'warn', REVIEW: 'warn', ADD_BUTTON_NOT_FOUND: 'warn',
  BROWSER_UNAVAILABLE: 'bad', BLOCK: 'bad',
};
const label = (s) => LABEL[s] || String(s).replace(/_/g, ' ').toLowerCase();
const tone = (s) => TONE[s] || 'flat';
const NOTE = {
  OUT_OF_STOCK: 'Weee! has this item but it is sold out right now.',
  NO_MATCH: 'No close enough match in the search results — nothing was added.',
  PRICE_ABOVE_LIMIT: 'Priced well above what you usually pay, so it was held back.',
  ADD_BUTTON_NOT_FOUND: 'Found the product but its add control did not respond.',
};
const keyOf = (s) => 'c' + Math.abs([...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7));

$('plan').addEventListener('click', async () => {
  const b = $('plan');
  b.disabled = true;
  b.innerHTML = '<span class="spin">&#9676;</span> Planning&hellip;';
  cartOut.innerHTML = '';
  try {
    const res = await fetch('/api/basket?horizon=7');
    BASKET = await res.json();
    chosen.clear();
    (BASKET.suggestions || []).forEach(s => chosen.add(s.item));
    renderBasket();
  } catch (err) {
    out.innerHTML = '<p class="note warn">Could not plan: ' + esc(err) + '</p>';
  } finally {
    b.disabled = false;
    b.textContent = 'Plan this week';
  }
});

function renderBasket() {
  const d = BASKET;
  if (!d || !d.count) {
    out.innerHTML = '<p class="empty">Nothing comes due in the next ' +
      (d ? d.horizon_days : 7) + ' days.</p>';
    dock.classList.remove('on');
    return;
  }
  $('selall').hidden = false;
  $('selnone').hidden = false;

  let html = '<div class="summary">' +
    '<div><span class="n">' + d.count + '</span><span class="l">due</span></div>' +
    '<div><span class="n">' + money(d.estimated_total) + '</span><span class="l">estimated</span></div>' +
    '<div><span class="n">' + Object.keys(d.by_channel).length + '</span><span class="l">stores</span></div>' +
    '<div><span class="n">' + d.as_of + '</span><span class="l">week of</span></div>' +
    '</div>';

  for (const [channel, items] of Object.entries(d.by_channel)) {
    const sub = items.reduce((t, i) => t + i.estimated_line_total, 0);
    html += '<section class="group"><div class="group-head"><h2>' + esc(channel) +
      '</h2><span>' + items.length + ' items &middot; ' + money(sub) + '</span></div><ul class="rows">';
    for (const i of items) {
      const id = keyOf(i.item);
      html += '<li class="card">' +
        '<div class="line">' +
          '<input type="checkbox" id="' + id + '" data-pick="' + esc(i.item) + '" checked>' +
          '<label class="who" for="' + id + '">' +
            '<div class="nm">' + esc(i.item) +
              (i.quantity > 1 ? '<span class="q">&times;' + i.quantity + '</span>' : '') + '</div>' +
            '<div class="sub">' + esc(i.category) +
              (i.brand ? ' &middot; ' + esc(i.brand) : '') +
              ' &middot; every ' + Math.round(i.cadence_days) + 'd</div>' +
          '</label>' +
          '<span class="chip ' + i.status + '">' + i.status + '</span>' +
          '<span class="amt">' + money(i.estimated_line_total) + '</span>' +
        '</div>' +
        '<div style="padding:0 14px 10px 43px">' +
          '<button class="disclose" data-why="' + id + '">why this?</button></div>' +
        '<div class="why" id="w' + id + '" hidden><ul>' +
          i.reasons.map(r => '<li>' + esc(r) + '</li>').join('') +
          i.unknowns.map(u => '<li class="dim">' + esc(u) + '</li>').join('') +
          '<li class="dim">P(buy) ' + i.probability.toFixed(2) +
            ' &middot; confidence ' + i.confidence.toFixed(2) +
            ' &middot; ' + i.occasions + ' past purchases</li>' +
        '</ul></div></li>';
    }
    html += '</ul></section>';
  }
  out.innerHTML = html;

  out.querySelectorAll('input[data-pick]').forEach(box => {
    box.addEventListener('change', () => {
      if (box.checked) { chosen.add(box.dataset.pick); } else { chosen.delete(box.dataset.pick); }
      box.closest('.card').classList.toggle('off', !box.checked);
      updateDock();
    });
  });
  out.querySelectorAll('[data-why]').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = $('w' + btn.dataset.why);
      panel.hidden = !panel.hidden;
      btn.textContent = panel.hidden ? 'why this?' : 'hide';
    });
  });

  updateDock();
  refreshStatus();
  foot.textContent = 'profile v' + d.profile_version +
    ' · suggestions only — the Mandate Engine authorizes every purchase';
}

function setAll(on) {
  chosen.clear();
  out.querySelectorAll('input[data-pick]').forEach(box => {
    box.checked = on;
    box.closest('.card').classList.toggle('off', !on);
    if (on) chosen.add(box.dataset.pick);
  });
  updateDock();
}
$('selall').addEventListener('click', () => setAll(true));
$('selnone').addEventListener('click', () => setAll(false));

function updateDock() {
  if (!BASKET) return;
  const picked = (BASKET.suggestions || []).filter(s => chosen.has(s.item));
  const total = picked.reduce((t, s) => t + s.estimated_line_total, 0);
  $('dockN').textContent = picked.length;
  $('dockT').textContent = money(total);
  $('send').disabled = !picked.length || !CART_READY;
  dock.classList.toggle('on', (BASKET.count || 0) > 0);
}

$('send').addEventListener('click', async () => {
  const b = $('send');
  const dry = $('dry').checked;
  b.disabled = true;
  try {
    const start = await (await fetch('/api/cart', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({dry_run: dry, horizon: 7, items: Array.from(chosen)}),
    })).json();
    if (!start.job_id) { renderCart(start); return; }
    await follow(start.job_id, b, dry);
  } catch (err) {
    cartOut.innerHTML = '<p class="note warn">Cart run failed: ' + esc(err) + '</p>';
  } finally {
    b.disabled = false;
    b.textContent = 'Add to Weee! cart';
    updateDock();
    refreshStatus();
  }
});

/* A cart run is a few seconds per item, so show what it is doing rather than
   leaving a spinner up for a minute. */
function follow(jobId, button, dry) {
  return new Promise((resolve) => {
    const tick = async () => {
      let job;
      try {
        job = await (await fetch('/api/cart/status?id=' + jobId)).json();
      } catch (err) {
        cartOut.innerHTML = '<p class="note warn">Lost contact: ' + esc(err) + '</p>';
        return resolve();
      }
      const n = job.current || 0, total = job.total || 0;
      button.innerHTML = '<span class="spin">&#9676;</span> ' +
        (total ? n + '/' + total : (dry ? 'Checking' : 'Adding')) + '&hellip;';
      renderProgress(job, dry);
      if (job.done) {
        renderCart({
          approved: job.approved || 0,
          gated: job.gated || [],
          cart: job.cart || (job.results && job.results.length
            ? {dry_run: dry, added: job.results.filter(r => r.status === 'ADDED').length,
               results: job.results, cart_url: 'https://www.sayweee.com/en/cart'}
            : null),
          error: job.error,
          needs_signin: job.needs_signin,
        });
        return resolve();
      }
      setTimeout(tick, 600);
    };
    tick();
  });
}

function renderProgress(job, dry) {
  const total = job.total || 0, n = job.current || 0;
  const pct = total ? Math.round((n / total) * 100) : 0;
  const done = (job.results || []).map(r =>
    '<li class="card"><div class="line" style="grid-template-columns:1fr auto auto">' +
    '<div class="who"><div class="nm">' + esc(r.item) + '</div>' +
    '<div class="sub">' + esc(r.matched_title || r.detail) + '</div></div>' +
    '<span class="chip t-' + tone(r.status) + '">' + label(r.status) + '</span>' +
    '<span class="amt">' + (r.matched_price != null ? money(r.matched_price) : '&mdash;') +
    '</span></div></li>').join('');
  cartOut.innerHTML =
    '<section class="group"><div class="group-head"><h2>' +
      (dry ? 'Checking Weee!' : 'Adding to Weee!') + '</h2>' +
      '<span>' + (total ? n + ' of ' + total : '&hellip;') + '</span></div>' +
    '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
    '<p class="status">' + esc(job.stage || 'Working') + '&hellip;</p>' +
    (done ? '<ul class="rows">' + done + '</ul>' : '') +
    '</section>';
}

function renderCart(data) {
  let html = '<section class="group"><div class="group-head"><h2>Decision Engine</h2>' +
    '<span>' + data.approved + ' of ' + data.gated.length + ' approved</span></div><ul class="rows">';
  for (const g of data.gated) {
    html += '<li class="card"><div class="line" style="grid-template-columns:1fr auto auto">' +
      '<div class="who"><div class="nm">' + esc(g.item) + '</div>' +
      '<div class="sub">' + esc(g.reason) + '</div></div>' +
      '<span class="chip t-' + tone(g.decision) + '">' + label(g.decision) + '</span>' +
      '<span class="amt">' + money(g.expected_price) + '</span></div></li>';
  }
  html += '</ul></section>';

  if (data.error) {
    html += '<p class="note' + (data.needs_signin ? '' : ' warn') + '">' +
      (data.needs_signin ? '<strong>Sign in needed.</strong> ' : '') + esc(data.error) + '</p>';
  }
  if (data.cart && data.cart.results.length) {
    html += '<section class="group"><div class="group-head"><h2>Weee! cart</h2><span>' +
      (data.cart.dry_run
        ? 'preview — nothing added'
        : data.cart.added + ' of ' + data.cart.results.length + ' added') +
      '</span></div><ul class="rows">';
    for (const r of data.cart.results) {
      html += '<li class="card"><div class="line" style="grid-template-columns:1fr auto auto">' +
        '<div class="who"><div class="nm">' + esc(r.item) + '</div>' +
        '<div class="sub">' + esc(r.matched_title || r.detail) + '</div></div>' +
        '<span class="chip t-' + tone(r.status) + '">' + label(r.status) + '</span>' +
        '<span class="amt">' + (r.matched_price != null ? money(r.matched_price) : '&mdash;') +
        '</span></div></li>';
    }
    html += '</ul></section>';
    const issues = data.cart.results.filter(r => NOTE[r.status]);
    if (issues.length) {
      const kinds = Array.from(new Set(issues.map(r => r.status)));
      html += '<p class="note warn"><strong>' + issues.length + ' not added.</strong> ' +
        kinds.map(k => label(k) + ' — ' + NOTE[k]).join(' ') + '</p>';
    }
    if (!data.cart.dry_run && data.cart.added) {
      html += '<p class="note">Added to your cart. ' +
        '<a href="' + data.cart.cart_url + '" target="_blank" rel="noopener">Open Weee! cart</a></p>';
    }
  }
  cartOut.innerHTML = html;
  cartOut.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function refreshStatus() {
  if (!CART_READY) {
    statusEl.textContent = 'Cart button unavailable — run with .venv/bin/python.';
    return;
  }
  try {
    const s = await (await fetch('/api/browser')).json();
    statusEl.innerHTML = !s.running
      ? 'Browser not started — it opens on your first add.'
      : (s.signed_in === true ? 'Browser ready &middot; <b>signed in to Weee!</b>'
        : s.signed_in === false ? 'Browser open &middot; not signed in yet'
        : 'Browser open &middot; sign-in state unknown');
  } catch (err) { statusEl.textContent = ''; }
}
refreshStatus();

/* ---------------- tabs ---------------- */
function showTab(name) {
  document.querySelectorAll('.tab[data-tab]').forEach(x =>
    x.classList.toggle('on', x.dataset.tab === name));
  $('pane-how').hidden = name !== 'how';
  $('pane-b').hidden = name !== 'b';
  dock.classList.toggle('on', name === 'b' && !!(BASKET && BASKET.count));
}
document.querySelectorAll('.tab[data-tab]').forEach(t => {
  t.addEventListener('click', () => showTab(t.dataset.tab));
});
document.querySelectorAll('[data-goto="b"]').forEach(btn => {
  btn.addEventListener('click', () => showTab('b'));
});
</script>
</body>
</html>
"""


# A cart run takes a few seconds per item, so it runs in the background and the
# page polls for progress. A spinner with no feedback reads as a hang.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _run_cart_job(job_id: str, picked, dry_run: bool, horizon: int) -> None:
    def note(**fields):
        with JOBS_LOCK:
            JOBS[job_id].update(fields)

    try:
        basket = suggest_weekly_basket(BUNDLE, as_of=TODAY, horizon_days=horizon)
        if picked is not None:
            wanted = set(picked)
            basket.suggestions = [s for s in basket.suggestions if s.item in wanted]
        if not basket.suggestions:
            note(done=True, error="Nothing selected.")
            return

        note(stage="Checking the mandate", total=len(basket.suggestions))
        gated = gate_basket(basket, to_contract_profile(BUNDLE, None))
        note(gated=[g.to_dict() for g in gated],
             approved=sum(1 for g in gated if g.approved))

        note(stage="Opening the browser")
        status = BROWSER.status()
        if not status.running:
            error = BROWSER.ensure_started()
            if error:
                note(done=True, error=error)
                return
            status = BROWSER.status()

        if status.signed_in is False:
            BROWSER.open_login()
            note(done=True, needs_signin=True,
                 error="Sign in to Weee! in the browser window that just opened, "
                       "then click again. You only have to do this once.")
            return

        lines = approved_lines(gated)
        pending = [line for line in lines if line.get("approved")]
        note(stage="Adding to cart", total=len(pending), current=0)

        executor = WeeeCartExecutor(dry_run=dry_run)
        results = []
        for index, line in enumerate(lines, start=1):
            note(stage=f"{'Checking' if dry_run else 'Adding'} {line['item']}",
                 current=index, total=len(lines))
            run = executor.add_lines_on_worker(BROWSER, [line])
            results.extend(r.to_dict() for r in run.results)
            note(results=list(results), error=run.error)

        note(done=True, stage="Finished",
             cart={"dry_run": dry_run, "cart_url": CART_URL_FALLBACK,
                   "added": sum(1 for r in results if r["status"] == "ADDED"),
                   "results": results, "error": None})
    except Exception as exc:  # never leave the page polling forever
        note(done=True, error=f"{type(exc).__name__}: {exc}")


CART_URL_FALLBACK = "https://www.sayweee.com/en/cart"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict) -> None:
        self._send(200, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            page = PAGE.replace("__PATH_A_URL__", PATH_A_URL).replace(
                "</head>",
                f"<script>window.__CART_READY__ = {str(CART_READY).lower()};</script></head>",
            )
            self._send(200, page.encode(), "text/html; charset=utf-8")
            return

        if url.path == "/api/basket":
            horizon = int(parse_qs(url.query).get("horizon", ["7"])[0])
            basket = suggest_weekly_basket(BUNDLE, as_of=TODAY, horizon_days=horizon)
            self._json(basket.to_dict())
            return

        if url.path == "/api/cart/status":
            job_id = parse_qs(url.query).get("id", [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            self._json(job or {"done": True, "error": "unknown job"})
            return

        if url.path == "/api/browser":
            if not CART_READY:
                self._json({"running": False, "signed_in": None, "detail": CART_ERROR})
                return
            self._json(BROWSER.status().to_dict())
            return

        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path != "/api/cart":
            self._send(404, b"not found", "text/plain")
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        dry_run = bool(body.get("dry_run", False))
        horizon = int(body.get("horizon", 7))
        picked = body.get("items")

        if not CART_READY:
            self._json({"approved": 0, "gated": [], "cart": None,
                        "error": f"cart stack unavailable: {CART_ERROR}"})
            return

        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {"done": False, "stage": "Starting", "current": 0,
                            "total": 0, "gated": [], "approved": 0,
                            "results": [], "cart": None, "error": None,
                            "needs_signin": False}
        threading.Thread(
            target=_run_cart_job, args=(job_id, picked, dry_run, horizon), daemon=True
        ).start()
        self._json({"job_id": job_id})


def _serve(preferred: int, attempts: int = 20) -> ThreadingHTTPServer:
    """Bind the first free port at or above `preferred`."""
    last: OSError | None = None
    for port in range(preferred, preferred + attempts):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            last = exc
            if port == preferred:
                print(f"  port {port} is busy (another instance?) — trying {port + 1}")
    raise SystemExit(
        f"No free port in {preferred}-{preferred + attempts - 1}. "
        f"Free one with:  lsof -nP -tiTCP:{preferred} | xargs kill\n{last}"
    )


def main() -> None:
    server = _serve(PORT)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"\n  Weekly basket UI  ->  {url}\n  Ctrl-C to stop\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        server.shutdown()
        server.server_close()
        if CART_READY and BROWSER is not None:
            BROWSER.stop()
        print("stopped, port released")


if __name__ == "__main__":
    main()
