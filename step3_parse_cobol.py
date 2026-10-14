"""
PASO 3: leer los COBOL guardados en Postgres (zdoc_raw_data) y pasarlos por el parser.
Solo lectura: no escribe en Postgres ni en Neo4j. Funciona igual con datos de prueba o reales.

    python step3_parse_cobol.py                    # resumen de todos los programas COBOL
    python step3_parse_cobol.py PGMCLI             # detalle de un miembro
    python step3_parse_cobol.py --pds FRAN.COBOL.SRC --limit 50
"""
import argparse
import sys

import psycopg2

from analysis.cobol_parser import parse_cobol
from config import PG_CONFIG

SQL_FUENTES = """
    SELECT p.nombre AS pds, m.nombre AS miembro, r.contenido
      FROM zdoc_miembros m
      JOIN zdoc_pds p       ON p.id = m.pds_id
      JOIN zdoc_raw_data r  ON r.id = m.raw_data_id
     WHERE m.tipo = 'COBOL'
       AND (%(pds)s IS NULL OR p.nombre = %(pds)s)
       AND (%(miembro)s IS NULL OR m.nombre = %(miembro)s)
     ORDER BY p.nombre, m.nombre
"""

# Todos los programas que Postgres conoce (zdoc_cobol), con sus CALL si los tienen
SQL_CALLS_PG = """
    SELECT c.program_id, cc.target_pgm_raw
      FROM zdoc_cobol c
      LEFT JOIN zdoc_cobol_calls cc ON cc.cobol_id = c.id
"""


def analizar(fuentes, calls_pg, detalle=False):
    """Parsea cada fuente. Un programa que falla no frena a los demas."""
    fallos, ok = [], 0
    print(f"{'PDS':<22}{'miembro':<10}{'program':<10}{'vars':>5}{'calls':>6}{'parr.':>6}{'perf.':>6}  vs Postgres")
    print("-" * 82)
    for pds, miembro, texto in fuentes:
        try:
            r = parse_cobol(texto)
        except Exception as e:  # el parser es por regex: con codigo real puede tropezar
            fallos.append((pds, miembro, f"{type(e).__name__}: {e}"))
            print(f"{pds:<22}{miembro:<10}{'ERROR':<10}  {type(e).__name__}")
            continue

        if not r["program"]:
            fallos.append((pds, miembro, "no se encontro PROGRAM-ID"))
            print(f"{pds:<22}{miembro:<10}{'(sin id)':<10}  no se encontro PROGRAM-ID")
            continue

        ok += 1
        destinos = {c["to"] for c in r["calls"]}
        if r["program"] not in calls_pg:
            estado = "sin fila en zdoc_cobol"
        elif destinos == calls_pg[r["program"]]:
            estado = "OK"
        else:
            estado = f"DIFIERE (pg: {sorted(calls_pg[r['program']])})"
        print(f"{pds:<22}{miembro:<10}{r['program']:<10}{len(r['variables']):>5}"
              f"{len(r['calls']):>6}{len(r['paragraphs']):>6}{len(r['performs']):>6}  {estado}")

        if detalle:
            print("\nVariables :", r["variables"])
            print("CALLs     :", [(c["from"], c["to"]) for c in r["calls"]])
            print("CONTAINS  :", [(c["from"], c["to"]) for c in r["contains"]])
            print("PERFORMs  :", [(c["from"], c["to"]) for c in r["performs"]])
            for p in r["paragraphs"]:
                print(f"\nParrafo {p['name']}:")
                for op in p.get("operations", []):
                    print("   ", op.get("type"), {k: v for k, v in op.items() if k != "type"})

    print(f"\nParseados: {ok}   Con problemas: {len(fallos)}")
    for pds, miembro, motivo in fallos:
        print(f"  - {pds}({miembro}): {motivo}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("miembro", nargs="?", help="nombre de un miembro (muestra el detalle)")
    ap.add_argument("--pds", help="limitar a un PDS")
    ap.add_argument("--limit", type=int, help="procesar solo los primeros N")
    args = ap.parse_args()

    conn = psycopg2.connect(**PG_CONFIG)
    conn.set_session(readonly=True)
    with conn, conn.cursor() as cur:
        cur.execute(SQL_FUENTES, {"pds": args.pds, "miembro": args.miembro.upper() if args.miembro else None})
        fuentes = cur.fetchall()
        cur.execute(SQL_CALLS_PG)
        calls_pg = {}
        for programa, destino in cur.fetchall():
            calls_pg.setdefault(programa, set())
            if destino:
                calls_pg[programa].add(destino)
    conn.close()

    if not fuentes:
        sys.exit("No hay miembros COBOL con fuente en zdoc_raw_data para ese filtro.")
    if args.limit:
        fuentes = fuentes[:args.limit]

    analizar(fuentes, calls_pg, detalle=bool(args.miembro))


if __name__ == "__main__":
    main()