###อั้ยยะใช่ๆปิดจบแล้ววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววววว###
import csv
import hashlib
import io
import os
import re
import secrets
import smtplib
import sqlite3
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from qr import qr_svg

# =========================================================
# CONFIG
# =========================================================

# ---------------------------------------------------------
# ส่วนที่ 1: ที่อยู่ไฟล์และโฟลเดอร์ (Path)
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_NAME = "chang_jum.db"
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

STATIC_DIR = os.path.join(BASE_DIR, "static")

UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
PRODUCT_PICS_DIR = os.path.join(STATIC_DIR, "images", "products")
LOGO_PICS_DIR = os.path.join(STATIC_DIR, "images", "logo")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PRODUCT_PICS_DIR, exist_ok=True)
os.makedirs(LOGO_PICS_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "images", "admin"), exist_ok=True)

# ---------------------------------------------------------
# ส่วนที่ 2: ชื่อไฟล์รูป
# ---------------------------------------------------------
# --- 2.1 โลโก้ร้าน ---
PIC_LOGO = "images/logo/logo.png"
PIC_PLACEHOLDER = "placeholder.svg"

# --- 2.2 รูปสินค้าในร้าน ---
PIC_POKEMON_151 = "images/products/pokemon-151-box.png"
PIC_ONEPIECE_OP05 = "images/products/onepiece-op05-box.png"
PIC_POKEMON_VSTAR = "images/products/pokemon-vstar-universe-box.png"
PIC_ONEPIECE_WINNER = "images/products/onepiece-championship-winner-card.png"
PIC_POKEMON_ASCENDED = "images/products/pokemon-ascended-heroes-etb.png"

# ---------------------------------------------------------
# ส่วนที่ 3: ผู้ดูแลระบบ (แอดมิน) + ภาษี
# ---------------------------------------------------------
PIC_ADMIN_SALES = "images/admin/sales.png"

ADMIN_USERNAME = "admineiei"
ADMIN_PASSWORD = "12345678"

VAT_RATE = 0.07

ADMIN_DISPLAY_NAME = "ผู้ดูแลร้านช้างจุ่ม"
PAID_STATUSES = ("paid", "shipped", "completed")

# ---------------------------------------------------------
# ส่วนที่ 3.1: ข้อมูลร้านและการชำระเงิน
# ---------------------------------------------------------
STORE_NAME = "ช้างจุ่ม"
BANK_INFO = "ธนาคารตัวอย่าง 000-0-00000-0 ชื่อบัญชี ร้านช้างจุ่ม"

# --- QR พร้อมเพย์ (PromptPay) ---
PROMPTPAY_ID = "0800000000"
PROMPTPAY_NAME = "ร้านช้างจุ่ม"
POINTS_PER_BAHT = 100

# ---------------------------------------------------------
# ส่วนที่ 3.2: อีเมล Gmail สำหรับแจ้งเตือนเมื่อลูกค้าลืมบัญชี
# ---------------------------------------------------------
GMAIL_ADDRESS = os.environ.get("CHANG_GMAIL_ADDRESS", "changjum4@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("CHANG_GMAIL_APP_PASSWORD", "lpwf bsea txnl bmgq")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
RESET_TOKEN_MINUTES = 30
RESET_COOLDOWN_SEC = 60

# ---------------------------------------------------------
# ส่วนที่ 4: การอัปโหลดไฟล์
# ---------------------------------------------------------
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_UPLOAD_MB = 5

# ---------------------------------------------------------
# ส่วนที่ 5: ตัวเลือกสินค้า
# ---------------------------------------------------------
LOW_STOCK = 5
BRANDS = ["Pokemon", "One Piece", "Yu-Gi-Oh!", "Sports Cards", "Other"]
TYPES = ["Box", "Pack", "Single"]
LANGS = ["TH", "JP", "EN"]
BRAND_ICONS = {"Pokemon": "⚡", "One Piece": "☠", "Yu-Gi-Oh!": "◈", "Sports Cards": "★", "Other": "✦"}

# ---------------------------------------------------------
# ส่วนที่ 6: ตัวกรองราคาและการเรียงลำดับหน้าร้าน
# ---------------------------------------------------------
PRICE_RANGES = {
    "lt500": ("ไม่เกิน ฿500", 0, 500),
    "500-5000": ("฿500 - ฿5,000", 500, 5000),
    "gt5000": ("มากกว่า ฿5,000", 5000, 10 ** 9),
}
SORTS = {
    "best": ("ขายดีที่สุด", "sold DESC, id DESC"),
    "asc": ("ราคา: ต่ำไปสูง", "price ASC"),
    "desc": ("ราคา: สูงไปต่ำ", "price DESC"),
    "new": ("มาใหม่", "id DESC"),
}

# ---------------------------------------------------------
# ส่วนที่ 7: สถานะคำสั่งซื้อ
# ---------------------------------------------------------
ORDER_STATUS = {
    "pending": "รอชำระเงิน",
    "verifying": "รอตรวจสลิป",
    "paid": "ชำระแล้ว",
    "shipped": "จัดส่งแล้ว",
    "completed": "สำเร็จ",
    "cancelled": "ยกเลิก",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def _load_secret_key():
    """เก็บ secret key ไว้ในไฟล์ เพื่อให้ session ไม่หลุดเมื่อรีสตาร์ท"""
    env = os.environ.get("CHANG_SECRET_KEY")
    if env:
        return env
    path = os.path.join(BASE_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.secret_key = _load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL,
    surname TEXT,
    phone TEXT,
    email TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    type TEXT NOT NULL,
    lang TEXT NOT NULL,
    price REAL NOT NULL,
    ready_to_ship INTEGER NOT NULL DEFAULT 1,
    image TEXT,
    sold INTEGER NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    total REAL NOT NULL,
    vat_amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    ship_name TEXT NOT NULL,
    ship_phone TEXT NOT NULL,
    ship_address TEXT NOT NULL,
    slip_image TEXT,
    points_awarded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    stocked INTEGER NOT NULL DEFAULT 0
);
"""

# ---------------------------------------------------------
# สินค้าตัวอย่างตอนสร้างฐานข้อมูลครั้งแรก
# ---------------------------------------------------------
SEED_PRODUCTS = [
    ("Pokemon - Scarlet & Violet '151' Booster Box",       "Pokemon",   "Box",    "JP", 11750, 1, PIC_POKEMON_151,      980, 25),
    ("One Piece [OP-05] Awakening of the New Era Box",     "One Piece", "Box",    "EN",  4500, 1, PIC_ONEPIECE_OP05,    870, 30),
    ("Pokemon - High Class Pack VSTAR Universe Box",       "Pokemon",   "Box",    "JP",  4900, 1, PIC_POKEMON_VSTAR,    640, 12),
    ("One Piece Championship Winner Promo Card (Luffy)",   "One Piece", "Single", "EN",  3500, 0, PIC_ONEPIECE_WINNER,  120, 0),
    ("Pokemon - Mega Evolution Ascended Heroes ETB",       "Pokemon",   "Box",    "EN",  2200, 1, PIC_POKEMON_ASCENDED, 410, 40),
]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def sync_admin(conn):
    """ให้บัญชีแอดมินในฐานข้อมูลตรงกับ ADMIN_USERNAME / ADMIN_PASSWORD ใน CONFIG"""
    if ADMIN_USERNAME != "admin":
        old = conn.execute("SELECT id, password FROM admins WHERE username = 'admin'").fetchone()
        if old and check_password_hash(old[1], "Admin@12345"):
            conn.execute("DELETE FROM admins WHERE id = ?", (old[0],))
    row = conn.execute("SELECT id, password FROM admins WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO admins (username, password, name) VALUES (?, ?, ?)",
                     (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD), ADMIN_DISPLAY_NAME))
    elif not check_password_hash(row[1], ADMIN_PASSWORD):
        conn.execute("UPDATE admins SET password = ? WHERE id = ?",
                     (generate_password_hash(ADMIN_PASSWORD), row[0]))


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    pcols = [r[1] for r in conn.execute("PRAGMA table_info(products)")]
    if "stock" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN stock INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE products SET stock = 10")
    icols = [r[1] for r in conn.execute("PRAGMA table_info(order_items)")]
    if "stocked" not in icols:
        conn.execute("ALTER TABLE order_items ADD COLUMN stocked INTEGER NOT NULL DEFAULT 0")
    sync_admin(conn)
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO products (name, brand, type, lang, price, ready_to_ship, image, sold, stock) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", SEED_PRODUCTS)
    conn.commit()
    conn.close()


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
@app.template_filter("baht")
def baht(v):
    return f"฿{float(v):,.0f}"


@app.template_filter("baht2")
def baht2(v):
    return f"฿{float(v):,.2f}"


@app.template_filter("compact")
def compact(n):
    n = int(n)
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


@app.template_filter("img_url")
def img_url(v):
    if not v:
        return url_for("static", filename=PIC_PLACEHOLDER)
    if v.startswith(("http://", "https://")):
        return v
    return url_for("static", filename=v)


def safe_next(default="shop"):
    nxt = request.form.get("next") or request.args.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return url_for(default)


def save_image(file, prefix):
    """บันทึกรูปที่อัปโหลด คืนค่า path แบบ relative ต่อ static/ หรือ None"""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return None
    name = secure_filename(f"{prefix}_{secrets.token_hex(6)}.{ext}")
    file.save(os.path.join(UPLOAD_DIR, name))
    return f"uploads/{name}"


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if "uid" not in session:
                flash("กรุณาเข้าสู่ระบบก่อน", "error")
                return redirect(url_for("login", next=request.path))
            if role and session.get("role") != role:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def cart_items():
    cart = session.get("cart", {})
    if not cart:
        return [], 0
    ids = [int(i) for i in cart]
    rows = get_db().execute(
        f"SELECT * FROM products WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    items, total = [], 0
    for r in rows:
        qty = cart[str(r["id"])]
        short = bool(r["ready_to_ship"]) and qty > r["stock"]
        items.append({"p": r, "qty": qty, "line": r["price"] * qty, "short": short})
        total += r["price"] * qty
    return items, total


@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400)


@app.context_processor
def inject_globals():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return {
        "csrf_token": session["_csrf"],
        "cart_count": sum(session.get("cart", {}).values()),
        "me": {"id": session.get("uid"), "role": session.get("role"), "name": session.get("name")},
        "ORDER_STATUS": ORDER_STATUS,
        "BRANDS": BRANDS, "TYPES": TYPES, "LANGS": LANGS, "BRAND_ICONS": BRAND_ICONS,
        "LOW_STOCK": LOW_STOCK, "STORE_NAME": STORE_NAME, "PIC_LOGO": PIC_LOGO, "VAT_PCT": round(VAT_RATE * 100),
    }


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def http_error(e):
    msgs = {400: "คำขอไม่ถูกต้อง หรือเซสชันหมดอายุ ลองรีเฟรชหน้าแล้วทำใหม่",
            403: "คุณไม่มีสิทธิ์เข้าถึงหน้านี้",
            404: "ไม่พบหน้าที่คุณต้องการ",
            413: "ไฟล์ใหญ่เกินไป (สูงสุด 5MB)"}
    return render_template("error.html", code=e.code, msg=msgs.get(e.code, "เกิดข้อผิดพลาด")), e.code


# ---------------------------------------------------------
# SHOP
# ---------------------------------------------------------
@app.route("/")
def shop():
    f = {
        "q": request.args.get("q", "").strip(),
        "ready": request.args.get("ready") == "1",
        "brand": request.args.get("brand", ""),
        "type": request.args.get("type", ""),
        "lang": request.args.get("lang", ""),
        "price": request.args.get("price", ""),
        "sort": request.args.get("sort", "best"),
        "view": request.args.get("view", "grid"),
    }
    if f["sort"] not in SORTS:
        f["sort"] = "best"
    if f["view"] not in ("grid", "list"):
        f["view"] = "grid"
    where, params = ["1=1"], []
    if f["q"]:
        where.append("name LIKE ?")
        params.append(f"%{f['q']}%")
    if f["ready"]:
        where.append("ready_to_ship = 1")
    for col in ("brand", "type", "lang"):
        if f[col]:
            where.append(f"{col} = ?")
            params.append(f[col])
    if f["price"] in PRICE_RANGES:
        _, lo, hi = PRICE_RANGES[f["price"]]
        where.append("price >= ? AND price <= ?")
        params += [lo, hi]
    sql = f"SELECT * FROM products WHERE {' AND '.join(where)} ORDER BY {SORTS[f['sort']][1]}"
    products = get_db().execute(sql, params).fetchall()
    has_filter = any([f["q"], f["ready"], f["brand"], f["type"], f["lang"], f["price"]])
    thumbs = {r["brand"]: r["image"] for r in get_db().execute(
        "SELECT brand, MAX(image) AS image FROM products WHERE image IS NOT NULL AND image != '' GROUP BY brand")}
    args = request.args.to_dict()
    view_urls = {v: url_for("shop", **{**args, "view": v}) for v in ("grid", "list")}
    return render_template("shop.html", products=products, f=f, has_filter=has_filter,
                           PRICE_RANGES=PRICE_RANGES, SORTS=SORTS, brand_thumbs=thumbs, view_urls=view_urls)


# ---------------------------------------------------------
# AUTH
# ---------------------------------------------------------
def validate_registration(d):
    """กฎเดียวกับโค้ด Tkinter เดิม"""
    if not all(d[k] for k in ("username", "password", "name", "surname", "phone", "email")):
        return "กรอกข้อมูลให้ครบทุกช่อง"
    if not d["phone"].isdigit() or len(d["phone"]) != 10:
        return "เบอร์โทรต้องเป็นตัวเลข 10 หลัก (ไม่ต้องใส่ขีด)"
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", d["email"]):
        return "รูปแบบอีเมลไม่ถูกต้อง เช่น user@example.com"
    u = d["username"]
    if len(u) < 8 or not any(c.isupper() for c in u) or not re.match(r"^[A-Za-z0-9]+$", u):
        return "ชื่อผู้ใช้ต้องยาวอย่างน้อย 8 ตัว มีตัวพิมพ์ใหญ่ 1 ตัว และใช้ได้เฉพาะ A-Z, a-z, 0-9"
    return validate_password(d["password"])


def validate_password(p):
    if (len(p) < 8 or not any(c.islower() for c in p) or not any(c.isupper() for c in p)
            or not any(c.isdigit() for c in p) or not re.search(r"[^A-Za-z0-9]", p)):
        return "รหัสผ่านต้องยาวอย่างน้อย 8 ตัว มีตัวพิมพ์เล็ก ตัวพิมพ์ใหญ่ ตัวเลข และอักขระพิเศษอย่างละ 1 ตัว"
    return None


@app.route("/register", methods=["GET", "POST"])
def register():
    form = {}
    if request.method == "POST":
        keys = ("username", "password", "name", "surname", "phone", "email")
        form = {k: request.form.get(k, "").strip() for k in keys}
        err = validate_registration(form)
        if err:
            flash(err, "error")
        else:
            try:
                db = get_db()
                db.execute(
                    "INSERT INTO users (username, password, name, surname, phone, email, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (form["username"], generate_password_hash(form["password"]), form["name"],
                     form["surname"], form["phone"], form["email"], now_str()))
                db.commit()
                flash("สมัครสมาชิกสำเร็จ เข้าสู่ระบบได้เลย", "ok")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("ชื่อผู้ใช้นี้ถูกใช้แล้ว เลือกชื่ออื่น", "error")
        form["password"] = ""
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = "admin" if request.form.get("role") == "admin" else "customer"
        table = "admins" if role == "admin" else "users"
        row = get_db().execute(f"SELECT * FROM {table} WHERE username = ?",
                               (request.form.get("username", "").strip(),)).fetchone()
        if row and check_password_hash(row["password"], request.form.get("password", "")):
            cart = session.get("cart")
            session.clear()
            session.update(uid=row["id"], role=role, name=row["name"])
            if cart:
                session["cart"] = cart
            return redirect(url_for("admin_dashboard") if role == "admin" else safe_next())
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("shop"))


# ---------------------------------------------------------
# ลืมบัญชี: แจ้งชื่อผู้ใช้ + ลิงก์ตั้งรหัสผ่านใหม่ ทางอีเมล Gmail
# ---------------------------------------------------------
def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def send_email(to_addr, subject, body):
    """ส่งอีเมลผ่าน Gmail SMTP ถ้ายังไม่ตั้งค่า Gmail จะพิมพ์ข้อความใน terminal แทน"""
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        print(f"\n[DEV] ยังไม่ได้ตั้งค่า Gmail - อีเมลถึง {to_addr}\n{subject}\n{body}\n")
        return
    msg = EmailMessage()
    msg["From"] = f"{STORE_NAME} <{GMAIL_ADDRESS}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD.replace(" ", ""))
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[ERROR] ส่งอีเมลถึง {to_addr} ไม่สำเร็จ: {exc}")


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("รูปแบบอีเมลไม่ถูกต้อง เช่น user@example.com", "error")
            return render_template("forgot.html", email=email)
        db = get_db()
        now = datetime.now()
        links = []
        for u in db.execute("SELECT id, username, name FROM users WHERE lower(email) = lower(?)", (email,)):
            recent = db.execute(
                "SELECT 1 FROM password_resets WHERE user_id=? AND created_at > ?",
                (u["id"], (now - timedelta(seconds=RESET_COOLDOWN_SEC)).strftime("%Y-%m-%d %H:%M:%S"))).fetchone()
            if recent:
                continue
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO password_resets (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
                       (u["id"], _hash_token(token),
                        (now + timedelta(minutes=RESET_TOKEN_MINUTES)).strftime("%Y-%m-%d %H:%M:%S"), now_str()))
            links.append((u["name"], u["username"], url_for("reset_password", token=token, _external=True)))
        db.commit()
        if links:
            lines = [f"สวัสดี คุณ{links[0][0]}", "",
                     f"เราได้รับคำขอกู้บัญชีของร้าน{STORE_NAME} บัญชีที่ผูกกับอีเมลนี้:", ""]
            for _, username, link in links:
                lines += [f"ชื่อผู้ใช้: {username}", f"ตั้งรหัสผ่านใหม่ (ใช้ได้ {RESET_TOKEN_MINUTES} นาที): {link}", ""]
            lines += ["หากคุณไม่ได้เป็นผู้ขอ ไม่ต้องทำอะไร บัญชีของคุณยังปลอดภัย", "", f"ทีมงาน{STORE_NAME}"]
            threading.Thread(target=send_email, daemon=True,
                             args=(email, f"[{STORE_NAME}] กู้คืนชื่อผู้ใช้และรหัสผ่าน", "\n".join(lines))).start()
        flash("หากอีเมลนี้มีบัญชีอยู่ในระบบ เราได้ส่งชื่อผู้ใช้และลิงก์ตั้งรหัสผ่านใหม่ไปให้แล้ว (ตรวจในกล่องสแปมด้วย)", "ok")
        return redirect(url_for("login"))
    return render_template("forgot.html", email="")


def _valid_reset(db, token):
    return db.execute(
        "SELECT * FROM password_resets WHERE token_hash=? AND used=0 AND expires_at > ?",
        (_hash_token(token), now_str())).fetchone()


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = get_db()
    row = _valid_reset(db, token)
    if not row:
        flash("ลิงก์นี้ไม่ถูกต้องหรือหมดอายุแล้ว กรุณาขอลิงก์ใหม่", "error")
        return redirect(url_for("forgot"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        err = validate_password(pw) or (None if pw == pw2 else "รหัสผ่านทั้งสองช่องไม่ตรงกัน")
        if err:
            flash(err, "error")
        else:
            db.execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(pw), row["user_id"]))
            db.execute("UPDATE password_resets SET used=1 WHERE user_id=?", (row["user_id"],))
            db.commit()
            flash("ตั้งรหัสผ่านใหม่สำเร็จ เข้าสู่ระบบได้เลย", "ok")
            return redirect(url_for("login"))
    return render_template("reset.html", token=token)


@app.route("/profile", methods=["GET", "POST"])
@login_required("customer")
def profile():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        surname = request.form.get("surname", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        if not name or not phone.isdigit() or len(phone) != 10 \
                or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("ตรวจสอบชื่อ เบอร์โทร (10 หลัก) และอีเมลอีกครั้ง", "error")
        else:
            db.execute("UPDATE users SET name=?, surname=?, phone=?, email=? WHERE id=?",
                       (name, surname, phone, email, session["uid"]))
            db.commit()
            session["name"] = name
            flash("บันทึกข้อมูลแล้ว", "ok")
        return redirect(url_for("profile"))
    user = db.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    orders = db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    return render_template("profile.html", user=user, orders=orders)


# ---------------------------------------------------------
# CART + ORDERS
# ---------------------------------------------------------
def stock_limit(p):
    """จำนวนสูงสุดที่สั่งได้: พร้อมส่ง = ตามสต็อก, พรีออเดอร์ = ไม่จำกัดสต็อก"""
    return min(p["stock"], 99) if p["ready_to_ship"] else 99


@app.post("/cart/add/<int:pid>")
def cart_add(pid):
    p = get_db().execute("SELECT name, ready_to_ship, stock FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    limit = stock_limit(p)
    cart = session.get("cart", {})
    cur = cart.get(str(pid), 0)
    if limit <= 0:
        flash(f"'{p['name']}' สินค้าหมดชั่วคราว", "error")
    elif cur >= limit:
        flash(f"'{p['name']}' มีในสต็อก {limit} ชิ้น คุณใส่ตะกร้าครบแล้ว", "error")
    else:
        cart[str(pid)] = cur + 1
        session["cart"] = cart
        flash(f"ใส่ '{p['name']}' ในตะกร้าแล้ว", "ok")
    return redirect(safe_next())


@app.post("/cart/update/<int:pid>")
def cart_update(pid):
    cart = session.get("cart", {})
    key, action = str(pid), request.form.get("action")
    if key in cart:
        if action == "inc":
            p = get_db().execute("SELECT name, ready_to_ship, stock FROM products WHERE id=?", (pid,)).fetchone()
            if p and cart[key] + 1 > stock_limit(p):
                flash(f"'{p['name']}' มีในสต็อกเพียง {stock_limit(p)} ชิ้น", "error")
            else:
                cart[key] = min(cart[key] + 1, 99)
        elif action == "dec":
            cart[key] -= 1
        elif action == "remove":
            cart[key] = 0
        if cart[key] <= 0:
            del cart[key]
    session["cart"] = cart
    return redirect(url_for("cart_page"))


@app.route("/cart")
def cart_page():
    items, total = cart_items()
    user = None
    if session.get("role") == "customer":
        user = get_db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    return render_template("cart.html", items=items, total=total, user=user)


@app.post("/checkout")
@login_required("customer")
def checkout():
    items, total = cart_items()
    if not items:
        flash("ตะกร้ายังว่าง", "error")
        return redirect(url_for("shop"))
    name = request.form.get("ship_name", "").strip()
    phone = request.form.get("ship_phone", "").strip()
    address = request.form.get("ship_address", "").strip()
    if not name or not address or not phone.isdigit() or len(phone) != 10:
        flash("กรอกชื่อ เบอร์โทร (10 หลัก) และที่อยู่จัดส่งให้ครบ", "error")
        return redirect(url_for("cart_page"))
    vat = total - total / (1 + VAT_RATE)
    db = get_db()
    short = []
    for it in items:
        p = it["p"]
        if p["ready_to_ship"]:
            cur = db.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                             (it["qty"], p["id"], it["qty"]))
            if cur.rowcount == 0:
                short.append(p["id"])
    if short:
        db.rollback()
        msgs = []
        for pid in short:
            r = db.execute("SELECT name, stock FROM products WHERE id=?", (pid,)).fetchone()
            msgs.append(f"{r['name']} (เหลือ {r['stock']} ชิ้น)")
        flash("สินค้าในสต็อกไม่พอ: " + ", ".join(msgs) + " กรุณาปรับจำนวนในตะกร้า", "error")
        return redirect(url_for("cart_page"))
    cur = db.execute(
        "INSERT INTO orders (user_id, total, vat_amount, ship_name, ship_phone, ship_address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session["uid"], total, vat, name, phone, address, now_str()))
    oid = cur.lastrowid
    for it in items:
        db.execute("INSERT INTO order_items (order_id, product_id, name, price, qty, stocked) VALUES (?, ?, ?, ?, ?, ?)",
                   (oid, it["p"]["id"], it["p"]["name"], it["p"]["price"], it["qty"], 1 if it["p"]["ready_to_ship"] else 0))
        db.execute("UPDATE products SET sold = sold + ? WHERE id = ?", (it["qty"], it["p"]["id"]))
    db.commit()
    session.pop("cart", None)
    flash("สร้างคำสั่งซื้อแล้ว โอนเงินและแนบสลิปได้ที่หน้านี้", "ok")
    return redirect(url_for("order_detail", oid=oid))


def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"


def _crc16(text):
    crc = 0xFFFF
    for b in text.encode("ascii"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def promptpay_payload(target, amount=None):
    """สร้างข้อความ EMVCo สำหรับ QR พร้อมเพย์ (target = เบอร์โทร 10 หลัก หรือเลข 13 หลัก)"""
    target = re.sub(r"\D", "", target or "")
    if len(target) == 10 and target.startswith("0"):
        sub = _tlv("01", "0066" + target[1:])
    elif len(target) == 13:
        sub = _tlv("02", target)
    else:
        raise ValueError("PROMPTPAY_ID ต้องเป็นเบอร์โทร 10 หลัก หรือเลข 13 หลัก")
    body = _tlv("00", "01")
    body += _tlv("01", "12" if amount else "11")
    body += _tlv("29", _tlv("00", "A000000677010111") + sub)
    body += _tlv("53", "764")
    if amount:
        body += _tlv("54", f"{float(amount):.2f}")
    body += _tlv("58", "TH")
    body += "6304"
    return body + _crc16(body)


def load_order(oid, owner_id=None):
    db = get_db()
    order = db.execute("SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?",
                       (oid,)).fetchone()
    if not order or (owner_id is not None and order["user_id"] != owner_id):
        abort(404)
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()
    return order, items


@app.route("/order/<int:oid>")
@login_required("customer")
def order_detail(oid):
    order, items = load_order(oid, session["uid"])
    qr = None
    if order["status"] in ("pending", "verifying"):
        try:
            payload = promptpay_payload(PROMPTPAY_ID, round(order["total"], 2))
            qr = qr_svg(payload, fg="#1f3f5a", bg="#ffffff")
        except ValueError:
            qr = None
    return render_template("order.html", order=order, items=items, BANK_INFO=BANK_INFO,
                           qr=qr, PROMPTPAY_NAME=PROMPTPAY_NAME)


@app.route("/order/<int:oid>/qr.svg")
@login_required("customer")
def order_qr(oid):
    order, _ = load_order(oid, session["uid"])
    if order["status"] not in ("pending", "verifying"):
        abort(403)
    try:
        svg = qr_svg(promptpay_payload(PROMPTPAY_ID, round(order["total"], 2)), fg="#1f3f5a", bg="#ffffff")
    except ValueError:
        abort(404)
    return Response(svg, mimetype="image/svg+xml")


@app.post("/order/<int:oid>/slip")
@login_required("customer")
def order_slip(oid):
    order, _ = load_order(oid, session["uid"])
    if order["status"] not in ("pending", "verifying"):
        abort(403)
    path = save_image(request.files.get("slip"), f"slip{oid}")
    if not path:
        flash("แนบไฟล์รูปสลิป (png, jpg, jpeg, webp) ให้ถูกต้อง", "error")
    else:
        db = get_db()
        db.execute("UPDATE orders SET slip_image=?, status='verifying' WHERE id=?", (path, oid))
        db.commit()
        flash("ส่งสลิปแล้ว รอแอดมินตรวจสอบ", "ok")
    return redirect(url_for("order_detail", oid=oid))


# ---------------------------------------------------------
# ADMIN
# ---------------------------------------------------------
PAID_IN = "(" + ",".join(f"'{x}'" for x in PAID_STATUSES) + ")"


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    db = get_db()
    one = lambda sql: db.execute(sql).fetchone()[0]
    stats = {
        "products": one("SELECT COUNT(*) FROM products"),
        "members": one("SELECT COUNT(*) FROM users"),
        "orders": one("SELECT COUNT(*) FROM orders"),
        "to_check": one("SELECT COUNT(*) FROM orders WHERE status='verifying'"),
        "revenue": one(f"SELECT COALESCE(SUM(total),0) FROM orders WHERE status IN {PAID_IN}"),
        "low_stock": db.execute("SELECT COUNT(*) FROM products WHERE ready_to_ship=1 AND stock <= ?",
                                (LOW_STOCK,)).fetchone()[0],
    }
    by_status = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM orders GROUP BY status")}
    recent = db.execute("SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id "
                        "ORDER BY o.id DESC LIMIT 8").fetchall()
    top = db.execute("SELECT name, sold FROM products ORDER BY sold DESC LIMIT 5").fetchall()
    return render_template("admin_dashboard.html", stats=stats, recent=recent, top=top, by_status=by_status)


@app.route("/admin/products")
@login_required("admin")
def admin_products():
    q = request.args.get("q", "").strip()
    brand = request.args.get("brand", "")
    low = request.args.get("low") == "1"
    where, params = ["1=1"], []
    if q:
        where.append("name LIKE ?")
        params.append(f"%{q}%")
    if brand in BRANDS:
        where.append("brand = ?")
        params.append(brand)
    if low:
        where.append("ready_to_ship = 1 AND stock <= ?")
        params.append(LOW_STOCK)
    order_by = "stock ASC, id DESC" if low else "id DESC"
    rows = get_db().execute(
        f"SELECT * FROM products WHERE {' AND '.join(where)} ORDER BY {order_by}", params).fetchall()
    return render_template("admin_products.html", products=rows, q=q, brand=brand, low=low)


@app.post("/admin/products/<int:pid>/stock")
@login_required("admin")
def admin_product_stock(pid):
    """ปรับจำนวนสต็อก: set = ตั้งเป็นจำนวนนี้, add = เพิ่ม/ลดจากของเดิม (ใส่ค่าติดลบได้)"""
    db = get_db()
    p = db.execute("SELECT name, stock FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    try:
        n = int(request.form.get("qty", ""))
    except ValueError:
        flash("ใส่จำนวนเป็นตัวเลขจำนวนเต็ม", "error")
        return redirect(request.referrer or url_for("admin_products"))
    new = n if request.form.get("mode") == "set" else p["stock"] + n
    if new < 0 or new > 1_000_000:
        flash("จำนวนสต็อกต้องอยู่ระหว่าง 0 ถึง 1,000,000", "error")
    else:
        db.execute("UPDATE products SET stock=? WHERE id=?", (new, pid))
        db.commit()
        flash(f"สต็อก '{p['name']}' = {new} ชิ้น", "ok")
    return redirect(request.referrer or url_for("admin_products"))


def read_product_form():
    f = request.form
    try:
        price = float(f.get("price", ""))
    except ValueError:
        price = -1
    try:
        stock = int(f.get("stock", "0") or 0)
    except ValueError:
        stock = -1
    data = {
        "name": f.get("name", "").strip(), "stock": stock, "brand": f.get("brand", ""), "type": f.get("type", ""),
        "lang": f.get("lang", ""), "price": price, "ready_to_ship": 1 if f.get("ready") else 0,
        "image": f.get("image_url", "").strip(),
    }
    ok = (data["name"] and data["brand"] in BRANDS and data["type"] in TYPES
          and data["lang"] in LANGS and price > 0 and 0 <= stock <= 1_000_000)
    return data, bool(ok)


@app.route("/admin/products/new", methods=["GET", "POST"])
@login_required("admin")
def admin_product_new():
    p = {"name": "", "brand": BRANDS[0], "type": "Box", "lang": "JP", "price": "",
         "ready_to_ship": 1, "image": "", "stock": 0}
    if request.method == "POST":
        data, ok = read_product_form()
        p = data
        if not ok:
            flash("กรอกชื่อ เลือกหมวด ใส่ราคาที่มากกว่า 0 และสต็อกเป็นจำนวนเต็มตั้งแต่ 0 ให้ถูกต้อง", "error")
        else:
            data["image"] = save_image(request.files.get("image_file"), "p") or data["image"]
            db = get_db()
            db.execute("INSERT INTO products (name, brand, type, lang, price, ready_to_ship, image, stock) "
                       "VALUES (:name, :brand, :type, :lang, :price, :ready_to_ship, :image, :stock)", data)
            db.commit()
            flash("เพิ่มสินค้าแล้ว", "ok")
            return redirect(url_for("admin_products"))
    return render_template("admin_product_form.html", p=p, editing=False)


@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required("admin")
def admin_product_edit(pid):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    if request.method == "POST":
        data, ok = read_product_form()
        if not ok:
            flash("กรอกชื่อ เลือกหมวด ใส่ราคาที่มากกว่า 0 และสต็อกเป็นจำนวนเต็มตั้งแต่ 0 ให้ถูกต้อง", "error")
            p = data
        else:
            data["image"] = save_image(request.files.get("image_file"), "p") or data["image"]
            data["id"] = pid
            db.execute("UPDATE products SET name=:name, brand=:brand, type=:type, lang=:lang, price=:price, "
                       "ready_to_ship=:ready_to_ship, image=:image, stock=:stock WHERE id=:id", data)
            db.commit()
            flash("บันทึกการแก้ไขแล้ว", "ok")
            return redirect(url_for("admin_products"))
    return render_template("admin_product_form.html", p=p, editing=True, pid=pid)


@app.post("/admin/products/<int:pid>/toggle")
@login_required("admin")
def admin_product_toggle(pid):
    db = get_db()
    db.execute("UPDATE products SET ready_to_ship = 1 - ready_to_ship WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("admin_products"))


@app.post("/admin/products/<int:pid>/delete")
@login_required("admin")
def admin_product_delete(pid):
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit()
    flash("ลบสินค้าแล้ว (ประวัติคำสั่งซื้อเดิมยังอยู่)", "ok")
    return redirect(url_for("admin_products"))


def query_orders():
    """ดึงรายการคำสั่งซื้อตามตัวกรอง (ใช้ทั้งหน้าจอและไฟล์ CSV)"""
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip()
    where, params = ["1=1"], []
    if status in ORDER_STATUS:
        where.append("o.status = ?")
        params.append(status)
    if q:
        where.append("(u.username LIKE ? OR o.ship_name LIKE ? OR o.id = ?)")
        params += [f"%{q}%", f"%{q}%", int(q.lstrip("#") or 0) if q.lstrip("#").isdigit() else -1]
    rows = get_db().execute(
        f"SELECT o.*, u.username FROM orders o JOIN users u ON u.id=o.user_id "
        f"WHERE {' AND '.join(where)} ORDER BY o.id DESC", params).fetchall()
    return rows, status, q


@app.route("/admin/orders")
@login_required("admin")
def admin_orders():
    rows, status, q = query_orders()
    return render_template("admin_orders.html", orders=rows, status=status, q=q)


@app.route("/admin/orders.csv")
@login_required("admin")
def admin_orders_csv():
    rows, _, _ = query_orders()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["เลขที่", "วันที่", "ลูกค้า", "ผู้รับ", "เบอร์โทร", "ที่อยู่", "ก่อน VAT", "VAT", "ยอดรวม", "สถานะ"])
    for o in rows:
        w.writerow([f"{o['id']:05d}", o["created_at"], o["username"], o["ship_name"], o["ship_phone"],
                    o["ship_address"], round(o["total"] - o["vat_amount"], 2), round(o["vat_amount"], 2),
                    round(o["total"], 2), ORDER_STATUS[o["status"]]])
    return Response(buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=orders.csv"})


@app.route("/admin/orders/<int:oid>", methods=["GET", "POST"])
@login_required("admin")
def admin_order(oid):
    order, items = load_order(oid)
    if request.method == "POST":
        new = request.form.get("status")
        if new not in ORDER_STATUS:
            abort(400)
        db = get_db()
        if (order["status"] == "cancelled") != (new == "cancelled"):
            for it in items:
                if it["product_id"] is None:
                    continue
                if new == "cancelled":
                    db.execute("UPDATE products SET stock = stock + ?, sold = MAX(sold - ?, 0) WHERE id = ?",
                               (it["qty"] if it["stocked"] else 0, it["qty"], it["product_id"]))
                else:
                    cur = db.execute("UPDATE products SET stock = stock - ?, sold = sold + ? "
                                     "WHERE id = ? AND stock >= ?",
                                     (it["qty"] if it["stocked"] else 0, it["qty"], it["product_id"],
                                      it["qty"] if it["stocked"] else 0))
                    if cur.rowcount == 0:
                        db.rollback()
                        flash(f"สต็อก '{it['name']}' ไม่พอที่จะเปิดออเดอร์นี้อีกครั้ง", "error")
                        return redirect(url_for("admin_order", oid=oid))
        db.execute("UPDATE orders SET status=? WHERE id=?", (new, oid))
        if new in ("paid", "shipped", "completed") and not order["points_awarded"]:
            db.execute("UPDATE users SET score = score + ? WHERE id=?", (int(order["total"] // POINTS_PER_BAHT), order["user_id"]))
            db.execute("UPDATE orders SET points_awarded=1 WHERE id=?", (oid,))
        db.commit()
        flash("อัปเดตสถานะแล้ว", "ok")
        return redirect(url_for("admin_order", oid=oid))
    return render_template("admin_order.html", order=order, items=items)


@app.route("/admin/members")
@login_required("admin")
def admin_members():
    q = request.args.get("q", "").strip()
    where, params = "", []
    if q:
        where = "WHERE u.username LIKE ? OR u.name LIKE ? OR u.surname LIKE ? OR u.phone LIKE ? OR u.email LIKE ?"
        params = [f"%{q}%"] * 5
    rows = get_db().execute(
        "SELECT u.*, (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id) AS order_count, "
        f"(SELECT COALESCE(SUM(total),0) FROM orders o WHERE o.user_id=u.id AND o.status IN {PAID_IN}) AS spent "
        f"FROM users u {where} ORDER BY u.id DESC", params).fetchall()
    return render_template("admin_members.html", members=rows, q=q)


@app.route("/admin/members/<int:uid>")
@login_required("admin")
def admin_member(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        abort(404)
    orders = db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    spent = sum(o["total"] for o in orders if o["status"] in PAID_STATUSES)
    return render_template("admin_member.html", user=user, orders=orders, spent=spent)


@app.route("/admin/sales")
@login_required("admin")
def admin_sales():
    db = get_db()
    tot = db.execute(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS total, COALESCE(SUM(vat_amount),0) AS vat "
        f"FROM orders WHERE status IN {PAID_IN}").fetchone()
    summary = {"orders": tot["n"], "total": tot["total"], "vat": tot["vat"],
               "net": tot["total"] - tot["vat"], "avg": (tot["total"] / tot["n"]) if tot["n"] else 0}
    months = db.execute(
        f"SELECT substr(created_at,1,7) AS m, COUNT(*) AS n, SUM(total) AS total, SUM(vat_amount) AS vat "
        f"FROM orders WHERE status IN {PAID_IN} GROUP BY m ORDER BY m DESC LIMIT 12").fetchall()
    top = db.execute(
        f"SELECT i.name, SUM(i.qty) AS qty, SUM(i.price * i.qty) AS rev FROM order_items i "
        f"JOIN orders o ON o.id=i.order_id WHERE o.status IN {PAID_IN} "
        f"GROUP BY i.name ORDER BY rev DESC LIMIT 10").fetchall()
    by_status = {r["status"]: (r["n"], r["total"]) for r in db.execute(
        "SELECT status, COUNT(*) AS n, COALESCE(SUM(total),0) AS total FROM orders GROUP BY status")}
    max_month = max([m["total"] for m in months], default=0) or 1
    max_top = max([t["rev"] for t in top], default=0) or 1
    pic = PIC_ADMIN_SALES if os.path.exists(os.path.join(STATIC_DIR, PIC_ADMIN_SALES)) else None
    return render_template("admin_sales.html", summary=summary, months=months, top=top,
                           by_status=by_status, max_month=max_month, max_top=max_top, sales_pic=pic)


init_db()

if __name__ == "__main__":
    app.run(debug=True)

