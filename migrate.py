import sqlite3, os
from items import ITEMS

db_path = os.environ.get("DATABASE_PATH", "sale.db")
conn = sqlite3.connect(db_path)

# Add new columns to items table if they don't exist
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

# Update existing items with English translations by matching name
item_map = {item["name"].strip(): item for item in ITEMS}
# Also try matching with stripped whitespace variants
for item in ITEMS:
    item_map[item["name"].strip()] = item

rows = conn.execute("SELECT id, name FROM items").fetchall()
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

conn.commit()
conn.close()
print(f"Migration complete. Updated {updated}/{len(rows)} items with English translations.")
