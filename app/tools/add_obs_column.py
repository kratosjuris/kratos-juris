import sqlite3

DB = "escritorio.db"

con = sqlite3.connect(DB)
cur = con.cursor()

# verifica se coluna já existe
cur.execute("PRAGMA table_info(process_items);")
cols = [row[1] for row in cur.fetchall()]

if "obs" not in cols:
    cur.execute("ALTER TABLE process_items ADD COLUMN obs TEXT;")
    con.commit()
    print("✅ Coluna 'obs' criada em process_items.")
else:
    print("ℹ️ Coluna 'obs' já existe.")

con.close()
