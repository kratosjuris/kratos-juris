import sqlite3
from pathlib import Path

DB_PATH = Path(r"D:\PROJETO SISTEMA ESCRITÓRIO\PROJETO SISTEMA CSL\escritorio.db")

COLUNAS_DESEJADAS = {
    "rg": "VARCHAR(30)",
    "ssp_uf": "VARCHAR(10)",
    "estado_civil": "VARCHAR(30)",
    "profissao": "VARCHAR(120)",
}


def get_existing_columns(conn, table_name: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table_name})")
    rows = cur.fetchall()
    return {row[1] for row in rows}


def main():
    if not DB_PATH.exists():
        print(f"Banco não encontrado: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        existing = get_existing_columns(conn, "clients")
        print("Colunas atuais de clients:")
        for c in sorted(existing):
            print(" -", c)

        for col_name, col_type in COLUNAS_DESEJADAS.items():
            if col_name not in existing:
                sql = f"ALTER TABLE clients ADD COLUMN {col_name} {col_type};"
                print(f"Adicionando coluna: {col_name} ({col_type})")
                conn.execute(sql)
            else:
                print(f"Coluna já existe: {col_name}")

        conn.commit()
        print("\nAtualização concluída com sucesso.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()