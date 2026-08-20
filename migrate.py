import sqlite3, os
from items import ITEMS

db_path = os.environ.get("DATABASE_PATH", "sale.db")
conn = sqlite3.connect(db_path)

# ── 1. Add new columns if missing ────────────────────────────────────────────
cols = [i[1] for i in conn.execute("PRAGMA table_info(items)").fetchall()]

if "category_en" not in cols:
    conn.execute("ALTER TABLE items ADD COLUMN category_en TEXT")
    print("Added category_en column")
if "name_en" not in cols:
    conn.execute("ALTER TABLE items ADD COLUMN name_en TEXT")
    print("Added name_en column")
if "notes_en" not in cols:
    conn.execute("ALTER TABLE items ADD COLUMN notes_en TEXT")
    print("Added notes_en column")

conn.commit()

# ── 2. Update English fields on existing items ────────────────────────────────
item_map = {item["name"].strip(): item for item in ITEMS}
rows = conn.execute("SELECT id, name FROM items").fetchall()
existing_names = {row[1].strip() for row in rows}
updated = 0

for row_id, name in rows:
    key = name.strip()
    if key in item_map:
        item = item_map[key]
        conn.execute(
            "UPDATE items SET category_en=?, name_en=?, notes_en=? WHERE id=?",
            (item.get("category_en",""), item.get("name_en",""), item.get("notes_en",""), row_id)
        )
        updated += 1

print(f"Updated {updated}/{len(rows)} existing items with English translations")

# ── 3. Insert any new items not already in DB ─────────────────────────────────
inserted = 0
for item in ITEMS:
    if item["name"].strip() not in existing_names:
        conn.execute(
            """INSERT INTO items (category, category_en, name, name_en, brand, qty_total, qty_available, price, notes, notes_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["category"], item.get("category_en",""), item["name"], item.get("name_en",""),
             item["brand"], item["qty"], item["qty"], item["price"],
             item["notes"], item.get("notes_en",""))
        )
        inserted += 1
        print(f"Inserted new item: {item['name']}")

print(f"Inserted {inserted} new items")

# ── 4. Fix prices ─────────────────────────────────────────────────────────────
price_fixes = {
    "플라스틱 쓰레기통 (대)": 1000,
    "플라스틱 쓰레기통 (소)": 1000,
    "철제 쓰레기통": 1000,
}
for name, price in price_fixes.items():
    conn.execute("UPDATE items SET price=? WHERE name LIKE ?", (price, f"%{name}%"))
    print(f"Fixed price: {name} → ₩{price:,}")

# Fix Blue Yeti name and brand
conn.execute("UPDATE items SET name='Blue Yeti A00104 마이크', name_en='Blue Yeti A00104 Microphone', brand='Blue Yeti' WHERE name LIKE '%Yeti%' OR name LIKE '%Blue Yeti%'")
print("Fixed Blue Yeti name and brand")

# Fix binding machine category
conn.execute("UPDATE items SET category='가구', category_en='Furniture' WHERE name LIKE '%제본기%'")
print("Fixed binding machine category to 가구")

conn.commit()
conn.close()
print("Migration complete.")
