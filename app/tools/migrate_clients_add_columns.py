from sqlalchemy import text
from app.core.database import engine

COLUMNS = [
    ("rg", "VARCHAR"),
    ("ssp_uf", "VARCHAR"),
    ("estado_civil", "VARCHAR"),
    ("profissao", "VARCHAR"),
]

def run():
    with engine.begin() as conn:
        for col, coltype in COLUMNS:
            try:
                conn.execute(text(f"ALTER TABLE clients ADD COLUMN {col} {coltype};"))
                print(f"OK: adicionada coluna {col}")
            except Exception as e:
                print(f"SKIP: {col} ({e})")

if __name__ == "__main__":
    run()
