import sqlite3

DB = r"C:\Users\tarci\AppData\Roaming\Sistema_Escritorio\escritorio.db"

def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    print(">> Desativando foreign_keys (reforma de tabela no SQLite)")
    cur.execute("PRAGMA foreign_keys=OFF;")

    # Confere se tabela existe
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_rows';"
    ).fetchone()
    if not row:
        raise RuntimeError("Tabela migration_rows não existe neste DB.")

    print(">> Criando tabela nova (sem UNIQUE global; UNIQUE apenas no batch_id+numero_processo)")
    cur.execute("""
    CREATE TABLE migration_rows_new (
        id INTEGER PRIMARY KEY,
        batch_id INTEGER NOT NULL,
        data_disponibilizacao DATE,
        data_publicacao DATE,
        numero_processo TEXT NOT NULL,
        diario TEXT,
        cliente TEXT,
        vara_tramitacao TEXT,
        observacao TEXT,
        rompe_em_dias INTEGER,
        enviar_para TEXT,
        enviado_em DATETIME,
        enviado_para_status TEXT,
        CONSTRAINT uq_migration_batch_numero_processo UNIQUE (batch_id, numero_processo),
        FOREIGN KEY(batch_id) REFERENCES migration_batches(id)
    );
    """)

    print(">> Copiando dados da tabela antiga para a nova")
    cur.execute("""
    INSERT INTO migration_rows_new (
        id, batch_id, data_disponibilizacao, data_publicacao, numero_processo, diario,
        cliente, vara_tramitacao, observacao, rompe_em_dias, enviar_para, enviado_em, enviado_para_status
    )
    SELECT
        id, batch_id, data_disponibilizacao, data_publicacao, numero_processo, diario,
        cliente, vara_tramitacao, observacao, rompe_em_dias, enviar_para, enviado_em, enviado_para_status
    FROM migration_rows;
    """)

    print(">> Removendo tabela antiga")
    cur.execute("DROP TABLE migration_rows;")

    print(">> Renomeando tabela nova para migration_rows")
    cur.execute("ALTER TABLE migration_rows_new RENAME TO migration_rows;")

    print(">> Recriando índices (não-unique)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_migration_rows_data_publicacao ON migration_rows(data_publicacao);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_migration_rows_data_disponibilizacao ON migration_rows(data_disponibilizacao);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_migration_rows_numero_processo ON migration_rows(numero_processo);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_migration_rows_id ON migration_rows(id);")

    con.commit()
    cur.execute("PRAGMA foreign_keys=ON;")
    con.close()

    print("✅ Correção finalizada com sucesso!")

if __name__ == "__main__":
    main()
