"""Invitation gate for the RD-Agent web app.

Wraps the upstream Flask app with a cookie-based invitation check.
- Visitors need a valid invite link:  https://<host>/?invite=<token>
- The admin (holder of ADMIN_MASTER_KEY) manages invites at /admin
- /test (Fly.io health check) and /favicon.ico stay open.
"""

import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from flask import jsonify, request

from rdagent.log.server.app import app, _load_existing_traces, log_folder_path

STORE = Path(os.environ.get("INVITE_STORE", "git_ignore_folder/invites.json"))
COOKIE = "rd_invite"
MASTER = os.environ.get("ADMIN_MASTER_KEY", "").strip()
if not MASTER:
    MASTER = secrets.token_urlsafe(16)
    print(f"[invite-gate] ADMIN_MASTER_KEY not set - generated master key: {MASTER}", flush=True)
print(f"[invite-gate] Admin console: /admin?key=***", flush=True)

_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    tmp.replace(STORE)


def _prune(d):
    return {k: v for k, v in d.items() if _parse(v.get("expires", "")) > _now()}


def _valid(tok):
    if not tok:
        return False
    with _lock:
        d = _load()
    v = d.get(tok)
    return bool(v) and _parse(v.get("expires", "")) > _now()


def _create(days, note):
    tok = secrets.token_urlsafe(12)
    exp = _now() + timedelta(days=days)
    with _lock:
        d = _prune(_load())
        d[tok] = {"created": _now().isoformat(), "expires": exp.isoformat(), "note": note or ""}
        _save(d)
    return tok, exp


def _revoke(tok):
    with _lock:
        d = _load()
        if tok in d:
            del d[tok]
            _save(d)
            return True
    return False


def _list():
    with _lock:
        d = _prune(_load())
        _save(d)
    return d


# ---------------------------------------------------------------- admin API

def _check_master():
    j = request.get_json(silent=True) or {}
    key = request.values.get("key") or j.get("key") or ""
    return bool(MASTER) and secrets.compare_digest(key, MASTER)


@app.route("/admin", methods=["GET"])
def admin_console():
    return ADMIN_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/admin/invites", methods=["GET", "POST"])
def admin_invites():
    if not _check_master():
        return jsonify({"error": "forbidden"}), 403
    if request.method == "GET":
        out = []
        for tok, v in sorted(_list().items(), key=lambda kv: kv[1].get("expires", "")):
            out.append({
                "token": tok,
                "link": request.host_url.rstrip("/") + "/?invite=" + tok,
                "expires": v.get("expires"),
                "note": v.get("note", ""),
            })
        return jsonify(out)
    j = request.get_json(silent=True) or {}
    try:
        days = float(j.get("days", 14))
    except Exception:
        days = 14
    days = min(max(days, 0.25), 365)
    try:
        count = int(j.get("count", 1))
    except Exception:
        count = 1
    count = min(max(count, 1), 50)
    note = str(j.get("note", ""))[:120]
    created = []
    for _ in range(count):
        tok, exp = _create(days, note)
        created.append({
            "token": tok,
            "link": request.host_url.rstrip("/") + "/?invite=" + tok,
            "expires": exp.isoformat(),
        })
    resp = {"invites": created}
    resp.update(created[0])  # back-compat single-invite fields
    return jsonify(resp)


@app.route("/admin/invites/revoke", methods=["POST"])
def admin_revoke():
    if not _check_master():
        return jsonify({"error": "forbidden"}), 403
    j = request.get_json(silent=True) or {}
    tok = j.get("token", "")
    return jsonify({"revoked": _revoke(tok)})


# ---------------------------------------------------------------- gate WSGI

BYPASS = {"/test", "/favicon.ico"}

GATE_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RD-Agent - Invitation required</title><style>
:root{color-scheme:light}body{margin:0;font-family:system-ui,sans-serif;background:#f5f7fb;color:#1f2430;
display:flex;min-height:100vh;align-items:center;justify-content:center}
.card{background:#fff;border:1px solid #e6eaf2;border-radius:14px;padding:34px 30px;max-width:430px;width:92%;
box-shadow:0 6px 24px rgba(16,24,40,.07);text-align:center}
h1{font-size:20px;margin:0 0 6px}p{color:#5b6472;font-size:14px;line-height:1.55}
input{width:100%;padding:11px 12px;border:1px solid #d4dae5;border-radius:9px;font-size:14px;margin-top:14px;box-sizing:border-box}
button{margin-top:12px;width:100%;background:#1677ff;border:0;color:#fff;font-weight:600;font-size:15px;
padding:11px;border-radius:9px;cursor:pointer}button:hover{background:#0e5fd8}
.err{color:#c0392b;font-size:13px;margin-top:10px;min-height:16px}</style></head><body>
<div class="card"><h1>RD-Agent</h1>
<p>This workspace is private. Paste your <b>invitation link</b> (or invite code) to enter. Invites are valid for 2 weeks and are issued by the admin.</p>
<input id="inv" placeholder="https://rd-agent.fly.dev/?invite=..." autofocus>
<button onclick="go()">Enter</button><div class="err" id="err"></div></div>
<script>
function go(){var v=document.getElementById('inv').value.trim();var m=v.match(/invite=([A-Za-z0-9_\\-]+)/);
var code=m?m[1]:v.replace(/^\\/+|\\/+$/g,'');if(!code){document.getElementById('err').textContent='Please paste your invite link.';return;}
location.href='/?invite='+encodeURIComponent(code);}
document.getElementById('inv').addEventListener('keydown',function(e){if(e.key==='Enter')go();});
</script></body></html>"""

ADMIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RD-Agent - Invite admin</title><style>
:root{color-scheme:light}body{margin:0;font-family:system-ui,sans-serif;background:#f5f7fb;color:#1f2430}
header{background:linear-gradient(120deg,#0b1f3a,#123a6d 60%,#1677ff);color:#fff;padding:22px 24px}
header h1{margin:0;font-size:20px}header p{margin:4px 0 0;font-size:13px;opacity:.85}
main{max-width:960px;margin:22px auto;padding:0 16px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:#fff;border:1px solid #e6eaf2;
border-radius:12px;padding:16px;margin-bottom:14px}
label{font-size:13px;font-weight:600;color:#414a59;display:flex;gap:6px;align-items:center}
input,select{padding:9px 10px;border:1px solid #d4dae5;border-radius:8px;font-size:14px}
button{background:#1677ff;border:0;color:#fff;font-weight:600;font-size:14px;padding:9px 16px;border-radius:8px;cursor:pointer}
button.gray{background:#64748b}button.red{background:#dc2626;padding:5px 10px;font-size:12px}
button.small{padding:5px 10px;font-size:12px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e6eaf2;border-radius:12px;overflow:hidden;font-size:13px}
th,td{padding:10px 12px;border-bottom:1px solid #f0f2f7;text-align:left;vertical-align:middle}
th{background:#f8fafc;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#5b6472}
a{color:#1677ff;word-break:break-all}
.msg{font-size:13px;color:#5b6472;margin:8px 2px;min-height:18px}
.hint{font-size:12px;color:#8a93a3;margin:0 2px 14px}
.pill{display:inline-block;background:#e8f7ee;color:#0a7d3b;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px}
</style></head><body>
<header><h1>Invitation admin</h1><p>Create, copy and revoke invite links. Each invite grants access until its expiry date.</p></header>
<main>
<div class="row"><label>Master key <input type="password" id="key" style="width:250px"></label>
<button onclick="load()">Load invites</button>
<a href="/" style="margin-left:auto;font-size:13px">← dashboard</a></div>
<p class="hint" id="hint"></p>

<div class="row">
  <label>Number of invites <input type="number" id="count" value="1" min="1" max="50" style="width:74px"></label>
  <label>Valid for <input type="number" id="days" value="14" min="1" max="365" style="width:74px"> days</label>
  <input id="note" placeholder="note (e.g. name or team)" style="flex:1;min-width:170px">
  <button onclick="create()">Create invite(s)</button>
  <button class="gray" onclick="copyAll()">Copy all links</button>
</div>
<div class="msg" id="msg"></div>

<table><thead><tr><th style="width:46%">Invite link</th><th>Expires (UTC)</th><th>Time left</th><th>Note</th><th></th></tr></thead>
<tbody id="tb"></tbody></table>
</main><script>
function k(){return document.getElementById('key').value.trim();}
function msg(t,bad){var e=document.getElementById('msg');e.textContent=t;e.style.color=bad?'#c0392b':'#0a7d3b';}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
async function api(path,opt){var r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opt||{}));
if(r.status===403){msg('Wrong master key.',true);throw 0;}return r.json();}
function leftDays(exp){return Math.max(0,Math.ceil((new Date(exp)-Date.now())/86400000));}
async function load(){try{var d=await api('/admin/invites?key='+encodeURIComponent(k()));var tb=document.getElementById('tb');
tb.innerHTML='';window._links=[];
d.forEach(function(x){window._links.push(x.link);var tr=document.createElement('tr');
tr.innerHTML='<td><a href="'+esc(x.link)+'" target="_blank">'+esc(x.link)+'</a><br>'+
'<button class="gray small" style="margin-top:4px" data-l="'+esc(x.link)+'" onclick="copyOne(this)">copy link</button></td>'+
'<td>'+esc(x.expires).replace('T',' ').slice(0,16)+'</td>'+
'<td><span class="pill">'+leftDays(x.expires)+' d</span></td>'+
'<td>'+esc(x.note||'')+'</td>'+
'<td><button class="red" data-t="'+esc(x.token)+'" onclick="revoke(this.dataset.t)">revoke</button></td>';
tb.appendChild(tr);});
msg(d.length+' active invite(s).',false);document.getElementById('msg').style.color='#5b6472';}catch(e){}}
async function create(){var c=Math.max(1,Math.min(50,+document.getElementById('count').value||1));
try{var x=await api('/admin/invites',{method:'POST',body:JSON.stringify({key:k(),days:+document.getElementById('days').value||14,count:c,note:document.getElementById('note').value})});
msg('Created '+x.invites.length+' invite(s). Latest: '+x.invites[x.invites.length-1].link,false);load();}catch(e){}}
function copyOne(b){navigator.clipboard.writeText(b.dataset.l);b.textContent='copied!';setTimeout(function(){b.textContent='copy link';},1200);}
function copyAll(){if(!window._links||!window._links.length){msg('No invites to copy.',true);return;}
navigator.clipboard.writeText(window._links.join('\\n'));msg(window._links.length+' link(s) copied to clipboard.',false);}
async function revoke(t){try{await api('/admin/invites/revoke',{method:'POST',body:JSON.stringify({key:k(),token:t})});msg('Revoked.',false);load();}catch(e){}}
var qk=new URLSearchParams(location.search).get('key');
if(qk){document.getElementById('key').value=qk;load();}
document.getElementById('key').addEventListener('input',function(){var v=this.value;
document.getElementById('hint').textContent=(v&&v.length<12)?'Tip: short master keys are guessable - set a long random ADMIN_MASTER_KEY secret in Fly.':'';});
</script></body></html>"""


class InviteGate:
    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path in BYPASS or path == "/admin" or path.startswith("/admin/"):
            return self.wsgi(environ, start_response)

        qs = parse_qs(environ.get("QUERY_STRING", ""))
        invite = (qs.get("invite") or [None])[0]
        key = (qs.get("key") or [None])[0]

        cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
        tok = cookies[COOKIE].value if COOKIE in cookies else None

        # Existing valid session?
        if tok and (tok == MASTER or _valid(tok)):
            return self.wsgi(environ, start_response)

        # Invite link or master key in URL -> set cookie, redirect to clean URL
        granted, max_age = None, 0
        if invite == MASTER or key == MASTER:
            granted, max_age = MASTER, 90 * 86400
        elif invite and _valid(invite):
            granted = invite
            with _lock:
                exp = _parse(_load().get(invite, {}).get("expires", ""))
            max_age = max(int((exp - _now()).total_seconds()), 300)

        if granted:
            clean_qs = {k2: v2 for k2, v2 in qs.items() if k2 not in ("invite", "key")}
            loc = path + ("?" + "&".join(f"{k2}={v2[0]}" for k2, v2 in clean_qs.items()) if clean_qs else "")
            headers = [
                ("Location", loc or "/"),
                ("Set-Cookie", f"{COOKIE}={granted}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"),
                ("Cache-Control", "no-store"),
            ]
            start_response("302 Found", headers)
            return [b""]

        start_response("403 Forbidden", [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store")])
        return [GATE_HTML.encode()]


def main(port: int = 19899):
    app.config["UI_SERVER_PORT"] = port
    _load_existing_traces(log_folder_path)
    app.wsgi_app = InviteGate(app.wsgi_app)
    app.run(debug=False, host="0.0.0.0", port=port)


if __name__ == "__main__":
    import typer

    typer.run(main)
