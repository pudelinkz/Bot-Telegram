import os
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, flash
from dotenv import load_dotenv
from database import init_db, get_settings, save_settings, stats

load_dotenv()
PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
SECRET = os.getenv("FLASK_SECRET_KEY", "")
if len(PASSWORD) < 16 or len(SECRET) < 32:
    raise RuntimeError("Atur DASHBOARD_PASSWORD (min. 16 karakter) dan FLASK_SECRET_KEY (min. 32 karakter) di .env")

app = Flask(__name__)
app.secret_key = SECRET
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

LOGIN = """<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login Anti-Spam</title><style>
body{font:16px system-ui;background:#101827;color:#e5e7eb;display:grid;place-items:center;min-height:100vh;margin:0}
form{background:#1f2937;padding:28px;border-radius:16px;width:min(360px,85vw)}input,button{box-sizing:border-box;width:100%;padding:12px;margin-top:12px;border-radius:8px;border:1px solid #475569}
button{background:#2563eb;color:white;border:0;font-weight:700;cursor:pointer}a{color:#93c5fd}
</style><form method="post"><h2>🛡️ Anti-Spam Admin</h2><p>Masuk ke dashboard</p><input name="password" type="password" placeholder="Password admin" required autofocus><button>Login</button></form></html>"""

PAGE = """<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard Anti-Spam</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e5e7eb;font:15px system-ui}
header{padding:22px 5%;background:#111c30;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
main{max-width:1100px;margin:24px auto;padding:0 18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}
.card,section{background:#131f33;border:1px solid #26364e;border-radius:14px;padding:18px;margin-bottom:18px}
.number{font-size:30px;font-weight:800}label{display:block;margin:13px 0 6px;color:#cbd5e1}
input,textarea{width:100%;background:#0b1220;color:#fff;border:1px solid #35465e;border-radius:8px;padding:10px}
input[type=checkbox]{width:auto;transform:scale(1.2);margin-right:8px}
button,.button{background:#2563eb;color:white;border:0;border-radius:8px;padding:11px 16px;cursor:pointer;text-decoration:none;display:inline-block}
.secondary{background:#334155}table{width:100%;border-collapse:collapse;overflow-wrap:anywhere}th,td{text-align:left;border-bottom:1px solid #26364e;padding:9px;font-size:13px}
.small{color:#94a3b8;font-size:13px}.flash{padding:10px;background:#164e3b;border-radius:8px;margin:10px 0}
@media(max-width:600px){th,td{padding:6px;font-size:12px}.number{font-size:25px}}
</style></head><body>
<header><div><strong>🛡️ Telegram Anti-Spam</strong><div class="small">Panel moderasi grup</div></div><a class="button secondary" href="/logout">Logout</a></header>
<main>
{% for msg in get_flashed_messages() %}<div class="flash">{{msg}}</div>{% endfor %}
<div class="grid"><div class="card"><div class="small">Total pelanggaran</div><div class="number">{{s.total}}</div></div>
<div class="card"><div class="small">Hari ini (UTC)</div><div class="number">{{s.today}}</div></div>
<div class="card"><div class="small">Jenis alasan tercatat</div><div class="number">{{s.reasons|length}}</div></div></div>
<form method="post" action="/settings"><section><h2>Pengaturan moderasi</h2>
<label><input type="checkbox" name="anti_link" {% if cfg.anti_link %}checked{% endif %}> Aktifkan anti-link</label>
<label>Kata terlarang (satu per baris)</label><textarea name="banned_words" rows="5">{{cfg.banned_words|join('\\n')}}</textarea>
<label>Domain yang diizinkan (satu per baris, contoh: t.me)</label><textarea name="allowed_domains" rows="3">{{cfg.allowed_domains|join('\\n')}}</textarea>
<div class="grid">
<div><label>Maksimum pesan</label><input type="number" name="flood_max_messages" min="2" max="30" value="{{cfg.flood_max_messages}}"></div>
<div><label>Dalam jendela (detik)</label><input type="number" name="flood_window_seconds" min="2" max="60" value="{{cfg.flood_window_seconds}}"></div>
<div><label>Duplikat sebelum ditindak</label><input type="number" name="duplicate_limit" min="2" max="8" value="{{cfg.duplicate_limit}}"></div>
<div><label>Mute (menit)</label><input type="number" name="mute_minutes" min="1" max="10080" value="{{cfg.mute_minutes}}"></div>
<div><label>Jumlah warning sebelum mute</label><input type="number" name="warnings_before_mute" min="1" max="10" value="{{cfg.warnings_before_mute}}"></div>
<div><label>Jumlah warning sebelum ban</label><input type="number" name="warnings_before_ban" min="2" max="20" value="{{cfg.warnings_before_ban}}"></div>
</div><p class="small">Perubahan berlaku saat pesan berikutnya diproses. Jangan set threshold ban terlalu rendah untuk mengurangi false positive.</p><button>Simpan pengaturan</button></section></form>
<section><h2>Ringkasan alasan</h2>{% if s.reasons %}<table><tr><th>Alasan</th><th>Jumlah</th></tr>{% for r in s.reasons %}<tr><td>{{r.reason}}</td><td>{{r.n}}</td></tr>{% endfor %}</table>{% else %}<p class="small">Belum ada pelanggaran.</p>{% endif %}</section>
<section><h2>20 pelanggaran terakhir</h2><div style="overflow-x:auto"><table><tr><th>Waktu UTC</th><th>Chat ID</th><th>User ID</th><th>Username</th><th>Alasan</th></tr>
{% for r in s.recent %}<tr><td>{{r.created_at}}</td><td>{{r.chat_id}}</td><td>{{r.user_id}}</td><td>{{r.username or '-'}}</td><td>{{r.reason}}</td></tr>{% endfor %}</table></div></section>
<p class="small">Dashboard ini mencatat metadata pelanggaran dan cuplikan teks terbatas di database lokal. Lindungi VPS dan jangan membuka port dashboard ke internet tanpa HTTPS serta kontrol akses tambahan.</p>
</main></body></html>"""

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password", "") == PASSWORD:
            session.clear()
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("Password salah.")
    return render_template_string(LOGIN)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template_string(PAGE, cfg=get_settings(), s=stats())

@app.route("/settings", methods=["POST"])
@login_required
def settings():
    def lines(name):
        return [x.strip().lower() for x in request.form.get(name, "").splitlines() if x.strip()]
    def number(name, default, lo, hi):
        try: value = int(request.form.get(name, default))
        except (TypeError, ValueError): value = default
        return max(lo, min(hi, value))
    save_settings({
        "anti_link": "anti_link" in request.form,
        "banned_words": lines("banned_words"),
        "allowed_domains": lines("allowed_domains"),
        "flood_max_messages": number("flood_max_messages", 6, 2, 30),
        "flood_window_seconds": number("flood_window_seconds", 8, 2, 60),
        "duplicate_limit": number("duplicate_limit", 3, 2, 8),
        "mute_minutes": number("mute_minutes", 10, 1, 10080),
        "warnings_before_mute": number("warnings_before_mute", 2, 1, 10),
        "warnings_before_ban": number("warnings_before_ban", 4, 2, 20),
    })
    flash("Pengaturan berhasil disimpan.")
    return redirect(url_for("index"))

if __name__ == "__main__":
    init_db()
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    app.run(host=host, port=port, debug=False)
