"""
Teste isolado de conexão com o Neon (fora do FastAPI, fora do SQLAlchemy).

Objetivo: descobrir se a demora é na CONEXAO (rede) ou em BUSCAR MUITAS LINHAS
(transferência de dados), sem nenhuma influência do app, do pool ou do
middleware do sistema.

COMO USAR:
1. Confirme que "psycopg2-binary" está instalado no seu ambiente
   (se não estiver: pip install psycopg2-binary)
2. Rode:  python teste_conexao_neon.py
3. Me mande o que aparecer no terminal (todas as linhas "TEMPO ...")
"""

import time
import psycopg2

# ⚠️ Troque pelos mesmos dados que estão no seu database.py
POSTGRES_USER = "neondb_owner"
POSTGRES_PASSWORD = "npg_3BO5YgUHpQlF"
POSTGRES_HOST = "ep-winter-unit-acjz4j3y-pooler.sa-east-1.aws.neon.tech"
POSTGRES_DB = "neondb"

# Troque pelo office_id que você usa (no seu teste anterior era 1)
OFFICE_ID = 1


def main():
    print("=" * 60)
    print("1) Testando apenas ABRIR a conexão...")
    t0 = time.time()
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        sslmode="require",
        connect_timeout=15,
    )
    t1 = time.time()
    print(f"   TEMPO PARA CONECTAR: {t1 - t0:.3f} segundos")

    cur = conn.cursor()

    print("=" * 60)
    print("2) Testando uma consulta BEM PEQUENA (SELECT 1)...")
    t0 = time.time()
    cur.execute("SELECT 1;")
    cur.fetchall()
    t1 = time.time()
    print(f"   TEMPO CONSULTA PEQUENA: {t1 - t0:.3f} segundos")

    print("=" * 60)
    print(f"3) Testando buscar TODOS os clientes do office_id={OFFICE_ID}...")
    t0 = time.time()
    cur.execute(
        "SELECT * FROM clients WHERE office_id = %s ORDER BY nome ASC;",
        (OFFICE_ID,),
    )
    linhas = cur.fetchall()
    t1 = time.time()
    print(f"   TEMPO PARA BUSCAR {len(linhas)} LINHAS: {t1 - t0:.3f} segundos")

    print("=" * 60)
    print("4) Testando a MESMA consulta de novo (conexão já aberta)...")
    t0 = time.time()
    cur.execute(
        "SELECT * FROM clients WHERE office_id = %s ORDER BY nome ASC;",
        (OFFICE_ID,),
    )
    linhas2 = cur.fetchall()
    t1 = time.time()
    print(f"   TEMPO PARA BUSCAR {len(linhas2)} LINHAS (2a vez): {t1 - t0:.3f} segundos")

    cur.close()
    conn.close()
    print("=" * 60)
    print("Teste concluído.")


if __name__ == "__main__":
    main()
