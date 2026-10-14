"""
PASO 1: verificar la conexion a PostgreSQL y ver que hay en las tablas zdoc_*.
Solo lectura: no modifica nada.

    python step1_postgres.py
"""
import sys

import psycopg2
from psycopg2 import sql

from config import PG_CONFIG

# Tablas que el modelo de grafo va a necesitar (segun ZDOCDB.sql)
ESPERADAS = [
    "zdoc_raw_data","zdoc_pds", "zdoc_miembros", "zdoc_jcl", "zdoc_steps", "zdoc_steps_dd",
    "zdoc_jcl_vars", "zdoc_cobol", "zdoc_cobol_archivos", "zdoc_cobol_copybooks",
    "zdoc_cobol_variables", "zdoc_cobol_calls", "zdoc_dependencies",
]


def main():
    faltan = [k for k in ("dbname", "user", "password") if not PG_CONFIG.get(k)]
    if faltan:
        sys.exit(f"Faltan en el .env: {', '.join(faltan)}")

    try:
        conn = psycopg2.connect(**PG_CONFIG)
    except psycopg2.OperationalError as e:
        sys.exit(f"No se pudo conectar a PostgreSQL:\n{e}")

    conn.set_session(readonly=True)  # garantia: este script no escribe

    with conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        print("Conectado:", cur.fetchone()[0])

        cur.execute("""
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name LIKE 'zdoc\\_%'
             ORDER BY table_name
        """)
        existentes = [r[0] for r in cur.fetchall()]

        print(f"\n{'tabla':<28}{'filas':>10}")
        print("-" * 38)
        for t in existentes:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t)))
            marca = "" if t in ESPERADAS else "  (extra)"
            print(f"{t:<28}{cur.fetchone()[0]:>10}{marca}")

        ausentes = [t for t in ESPERADAS if t not in existentes]
        if ausentes:
            print("\nFaltan tablas esperadas:", ", ".join(ausentes))
        else:
            print("\nTodas las tablas esperadas existen.")

    conn.close()


if __name__ == "__main__":
    main()
