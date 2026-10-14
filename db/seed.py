"""
Carga datos de prueba en el Postgres LOCAL: los 3 COBOL de cobol/ + un JCL que ejecuta PGMMAIN.
Es idempotente: si el miembro ya existe, no lo vuelve a crear.

    python db/seed.py
"""
import re
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import PG_CONFIG  # noqa: E402

COBOL_PDS, JCL_PDS, LOAD_PDS = "FRAN.COBOL.SRC", "FRAN.JCL", "FRAN.LOAD"

JCL_JOBCLI = """//JOBCLI   JOB (ACCT),'PRUEBA',CLASS=A
//STEP010  EXEC PGM=PGMMAIN
//STEPLIB  DD DSN=FRAN.LOAD,DISP=SHR
//SYSOUT   DD SYSOUT=*
"""


def pds(cur, nombre):
    cur.execute("INSERT INTO zdoc_pds (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING", (nombre,))
    cur.execute("SELECT id FROM zdoc_pds WHERE nombre = %s", (nombre,))
    return cur.fetchone()[0]


def miembro(cur, pds_id, nombre, tipo, texto=None):
    """Devuelve (id, creado). Solo guarda el texto si el miembro es nuevo."""
    cur.execute("SELECT id FROM zdoc_miembros WHERE pds_id = %s AND nombre = %s", (pds_id, nombre))
    fila = cur.fetchone()
    if fila:
        return fila[0], False
    raw_id = None
    if texto is not None:
        cur.execute("INSERT INTO zdoc_raw_data (contenido, tipo) VALUES (%s, %s) RETURNING id",
                    (texto, f"{tipo}_SOURCE"))
        raw_id = cur.fetchone()[0]
    cur.execute("INSERT INTO zdoc_miembros (pds_id, nombre, raw_data_id, tipo) VALUES (%s,%s,%s,%s) RETURNING id",
                (pds_id, nombre, raw_id, tipo))
    return cur.fetchone()[0], True


def main():
    conn = psycopg2.connect(**PG_CONFIG)
    with conn, conn.cursor() as cur:
        p_cobol, p_jcl, p_load = pds(cur, COBOL_PDS), pds(cur, JCL_PDS), pds(cur, LOAD_PDS)

        ids = {}
        for ruta in sorted((ROOT / "cobol").glob("*.cbl")):
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            nombre = ruta.stem.upper()
            mid, nuevo = miembro(cur, p_cobol, nombre, "COBOL", texto)
            ids[nombre] = mid
            if nuevo:
                program_id = re.search(r"PROGRAM-ID\.\s*([A-Z0-9_-]+)", texto, re.I).group(1).upper()
                cur.execute("INSERT INTO zdoc_cobol (miembro_id, program_id) VALUES (%s,%s)", (mid, program_id))
            print(f"{'creado ' if nuevo else 'existia'} {COBOL_PDS}({nombre})")

        # Calls estaticos que se ven en los fuentes
        cur.execute("SELECT count(*) FROM zdoc_cobol_calls")
        if cur.fetchone()[0] == 0:
            for origen, destino, resuelto in [("PGMMAIN", "PGMCLI", True),
                                              ("PGMCLI", "PGM-EXTERNO", False),
                                              ("PGMCLI", "PGM-VALIDACION", False)]:
                cur.execute("SELECT id FROM zdoc_cobol WHERE miembro_id = %s", (ids[origen],))
                cobol_id = cur.fetchone()[0]
                cur.execute("INSERT INTO zdoc_cobol_calls (cobol_id, target_pgm_raw, target_miembro_id) VALUES (%s,%s,%s)",
                            (cobol_id, destino, ids[destino] if resuelto else None))

        # JCL de ejemplo
        jid, nuevo = miembro(cur, p_jcl, "JOBCLI", "JCL", JCL_JOBCLI)
        if nuevo:
            cur.execute("INSERT INTO zdoc_jcl (miembro_id) VALUES (%s) RETURNING id", (jid,))
            jcl_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO zdoc_steps (jcl_id, nombre, orden, pgm_nombre_raw, programa_miembro_id)
                           VALUES (%s,'STEP010',1,'PGMMAIN',%s) RETURNING id""", (jcl_id, ids["PGMMAIN"]))
            step_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO zdoc_steps_dd (step_id, dd_name, tipo, target_pds_id, disp_status, dsn_raw)
                           VALUES (%s,'STEPLIB','DSN',%s,'SHR','FRAN.LOAD')""", (step_id, p_load))
            cur.execute("""INSERT INTO zdoc_steps_dd (step_id, dd_name, tipo) VALUES (%s,'SYSOUT','SYSOUT')""", (step_id,))
            cur.execute("""INSERT INTO zdoc_dependencies (parent_miembro_id, child_miembro_id, dependency_type)
                           VALUES (%s,%s,'PROGRAM') ON CONFLICT DO NOTHING""", (jid, ids["PGMMAIN"]))
        print(f"{'creado ' if nuevo else 'existia'} {JCL_PDS}(JOBCLI)")
    conn.close()
    print("Seed OK")


if __name__ == "__main__":
    main()
