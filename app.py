import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, Response, g
)
from dotenv import load_dotenv
from items import ITEMS

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

DATABASE = os.environ.get("DATABASE_PATH", "sale.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
PHOTOS_URL = "https://1drv.ms/p/c/8acd4010be61d921/IQAgdjBPeYR2QLD1tQIOxiwvAfPDVtZ30KoCddJme7kC53M?e=Xsqg2C"
BANK_NAME = "우리은행"
BANK_ACCOUNT = "1005-503-534333"
BANK_HOLDER = "파라택시스코리아 주식회사"


# ─── Database ────────────────────────────────────────────────────────────────

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        # Items catalog
        db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                brand TEXT,
                qty_total INTEGER NOT NULL,
                qty_available INTEGER NOT NULL,
                price INTEGER NOT NULL,
                notes TEXT
            )
        """)
        # Orders
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                qty INTEGER NOT NULL,
                total_price INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id)
            )
        """)
        db.commit()

        # Seed items if table is empty
        count = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if count == 0:
            for item in ITEMS:
                db.execute(
                    """INSERT INTO items (category, name, brand, qty_total, qty_available, price, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (item["category"], item["name"], item["brand"],
                     item["qty"], item["qty"], item["price"], item["notes"])
                )
            db.commit()


# ─── Auth ─────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ─── Routes: User ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    lang = request.args.get("lang", session.get("lang", "ko"))
    session["lang"] = lang
    db = get_db()
    items = db.execute(
        "SELECT * FROM items ORDER BY category, name"
    ).fetchall()
    # Group by category
    categories = {}
    for item in items:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(dict(item))
    return render_template("index.html", lang=lang, categories=categories,
                           photos_url=PHOTOS_URL,
                           bank_name=BANK_NAME, bank_account=BANK_ACCOUNT,
                           bank_holder=BANK_HOLDER)

@app.route("/order", methods=["POST"])
def order():
    data = request.get_json()
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    cart = data.get("cart", [])  # [{item_id, qty}]

    if not name or not phone or not cart:
        return jsonify({"ok": False, "error": "missing fields"}), 400

    db = get_db()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    errors = []

    for entry in cart:
        item_id = entry.get("item_id")
        qty = int(entry.get("qty", 1))
        item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            errors.append(f"Item {item_id} not found")
            continue
        if item["qty_available"] < qty:
            errors.append(f"{item['name']}: 재고 부족 (남은 수량: {item['qty_available']})")
            continue

        total_price = item["price"] * qty
        db.execute(
            """INSERT INTO orders (requester_name, phone, item_id, item_name, qty, total_price, status, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (name, phone, item_id, item["name"], qty, total_price, ts)
        )
        db.execute(
            "UPDATE items SET qty_available = qty_available - ? WHERE id = ?",
            (qty, item_id)
        )
        saved += 1

    db.commit()

    if errors:
        return jsonify({"ok": False, "error": "\n".join(errors)}), 400

    return jsonify({"ok": True, "count": saved})


# ─── Routes: Admin ────────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "비밀번호가 틀렸습니다. / Wrong password."
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    orders = db.execute(
        "SELECT * FROM orders ORDER BY timestamp DESC"
    ).fetchall()
    items = db.execute(
        "SELECT * FROM items ORDER BY category, name"
    ).fetchall()
    total_revenue = db.execute(
        "SELECT SUM(total_price) FROM orders WHERE status = 'paid'"
    ).fetchone()[0] or 0
    return render_template("admin.html", orders=orders, items=items,
                           total_revenue=total_revenue)

@app.route("/admin/order/<int:order_id>/status", methods=["POST"])
@admin_required
def update_status(order_id):
    status = request.form.get("status")
    if status not in ("pending", "paid", "fulfilled", "cancelled"):
        return "invalid status", 400
    db = get_db()
    # If cancelling, restore stock
    if status == "cancelled":
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order and order["status"] != "cancelled":
            db.execute(
                "UPDATE items SET qty_available = qty_available + ? WHERE id = ?",
                (order["qty"], order["item_id"])
            )
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    db.commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/order/<int:order_id>/delete", methods=["POST"])
@admin_required
def delete_order(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order and order["status"] != "cancelled":
        db.execute(
            "UPDATE items SET qty_available = qty_available + ? WHERE id = ?",
            (order["qty"], order["item_id"])
        )
    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    db.commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/export")
@admin_required
def admin_export():
    db = get_db()
    orders = db.execute("SELECT * FROM orders ORDER BY timestamp DESC").fetchall()
    def generate():
        cols = ["id", "requester_name", "phone", "item_name", "qty", "total_price", "status", "timestamp"]
        yield ",".join(cols) + "\n"
        for row in orders:
            yield ",".join(f'"{str(row[c]).replace(chr(34), chr(39))}"' for c in cols) + "\n"
    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=orders.csv"})

@app.route("/admin/items")
@admin_required
def admin_items():
    db = get_db()
    items = db.execute("SELECT * FROM items ORDER BY category, name").fetchall()
    return render_template("admin_items.html", items=items)

@app.route("/admin/items/<int:item_id>/reset", methods=["POST"])
@admin_required
def reset_item_qty(item_id):
    db = get_db()
    db.execute("UPDATE items SET qty_available = qty_total WHERE id = ?", (item_id,))
    db.commit()
    return redirect(url_for("admin_items"))


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
