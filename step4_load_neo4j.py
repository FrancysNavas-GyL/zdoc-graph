"""
PASO 4: primera carga a Neo4j. Lee los COBOL desde Postgres (zdoc_raw_data), los pasa por el
parser y escribe el grafo de LOGICA del programa en Neo4j. Postgres se abre en solo lectura.

    python step4_load_neo4j.py                        # carga todos los COBOL
    python step4_load_neo4j.py PGMCLI                 # carga un miembro
    python step4_load_neo4j.py --pds NOMBRE.PDS --limit 50
    python step4_load_neo4j.py --wipe                 # borra lo que cargo este script en Neo4j

Es re-ejecutable: cada programa se borra y se vuelve a escribir completo, asi que si el
fuente cambia en Postgres, el grafo se actualiza sin dejar restos.

Modelo (cada nodo lleva el programa en su clave, asi WS-SALDO de dos programas no se mezcla):
    (Program {name})-[:HAS_VARIABLE]->(Variable {uid: "PROG.VAR"})
    (Program)-[:CONTAINS]->(Paragraph {uid: "PROG.PARRAFO"})
    (Program|Paragraph)-[:PERFORMS]->(Paragraph)
    (Program)-[:CALLS]->(Program)            # destino externo => external=true
    (Paragraph)-[:HAS_OPERATION]->(Operation {type: MOVE|COMPUTE})-[:READS|WRITES]->(Variable)
    (Paragraph)-[:HAS_EVALUATE]->(Evaluate)-[:EVALUATES]->(Variable), (Evaluate)-[:HAS_WHEN]->(When)
"""
import argparse
import sys
import traceback

import psycopg2
from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from analysis.cobol_parser import parse_cobol
from config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, PG_CONFIG

# Etiquetas que llevan la propiedad "program" (se borran y recrean al recargar un programa)
POR_PROGRAMA = ["Operation", "When", "Evaluate", "Paragraph", "Variable"]
TODAS = ["Program"] + POR_PROGRAMA

SQL_FUENTES = """
    SELECT m.id, p.nombre AS pds, m.nombre AS miembro, r.contenido
      FROM zdoc_miembros m
      JOIN zdoc_pds p       ON p.id = m.pds_id
      JOIN zdoc_raw_data r  ON r.id = m.raw_data_id
     WHERE m.tipo = 'COBOL'
       AND (%(pds)s IS NULL OR p.nombre = %(pds)s)
       AND (%(miembro)s IS NULL OR m.nombre = %(miembro)s)
     ORDER BY p.nombre, m.nombre
"""


# ---------------------------------------------------------------------------
# Parte 1: del resultado del parser a filas para el grafo (funcion pura, sin BD)
# ---------------------------------------------------------------------------
def preparar(r):
    prog = r["program"]
    declaradas = set(r["variables"])

    def uid(nombre):
        return f"{prog}.{nombre}"

    d = {"prog": prog}
    d["variables"] = [{"uid": uid(v), "name": v} for v in dict.fromkeys(r["variables"])]

    # parrafos: los detectados + los que aparecen como destino en CONTAINS
    nombres = dict.fromkeys([p["name"] for p in r["paragraphs"]] + [c["to"] for c in r["contains"]])
    d["parrafos"] = [{"uid": uid(n), "name": n} for n in nombres]

    d["calls"] = [{"to": t} for t in dict.fromkeys(c["to"] for c in r["calls"])]

    desde_prog, desde_parr = [], []
    for e in r["performs"]:
        fila = {"from_uid": uid(e["from"]), "from_name": e["from"],
                "to_uid": uid(e["to"]), "to_name": e["to"]}
        (desde_prog if e["from"] == prog else desde_parr).append(fila)
    d["perform_prog"], d["perform_parr"] = desde_prog, desde_parr

    ops, escribe, lee, evals, evals_var, whens = [], [], [], [], [], []
    for p in r["paragraphs"]:
        puid = uid(p["name"])
        for i, op in enumerate(p["operations"]):
            if op["type"] not in ("MOVE", "COMPUTE"):
                continue  # CALL y PERFORM ya salen de r["calls"] y r["performs"]
            ouid = f"{puid}#{i}"
            ops.append({"uid": ouid, "par_uid": puid, "type": op["type"], "seq": i,
                        "value": op.get("value"), "expression": op.get("expression"),
                        "target": op.get("target")})
            for v in dict.fromkeys(op.get("writes", [])):
                escribe.append({"op_uid": ouid, "var_uid": uid(v), "var_name": v})
            for v in dict.fromkeys(op.get("uses", [])):
                lee.append({"op_uid": ouid, "var_uid": uid(v), "var_name": v})
        for ei, ev in enumerate(p["evaluates"]):
            euid = f"{puid}#E{ei}"
            evals.append({"uid": euid, "par_uid": puid, "expression": ev["expression"]})
            if ev["expression"] in declaradas:  # solo se enlaza si es realmente una variable
                evals_var.append({"e_uid": euid, "var_uid": uid(ev["expression"])})
            for wi, w in enumerate(ev["whens"]):
                whens.append({"uid": f"{euid}.W{wi}", "e_uid": euid, "value": w["when"], "seq": wi})
    d.update(ops=ops, escribe=escribe, lee=lee, evals=evals, evals_var=evals_var, whens=whens)
    return d


# ---------------------------------------------------------------------------
# Parte 2: escritura en Neo4j (una transaccion por programa)
# ---------------------------------------------------------------------------
def cargar_programa(tx, pds, miembro, member_id, d):
    prog = d["prog"]

    def ejecutar(consulta, **params):
        """Ejecuta, consume el resultado (para no dejar lecturas pendientes) y, si falla,
        dice QUE consulta fue."""
        try:
            tx.run(consulta, **params).consume()
        except Exception as e:
            q = " ".join(consulta.split())[:110]
            raise RuntimeError(f"{type(e).__name__}: {e} | consulta: {q}") from e

    # recarga limpia: se borra lo que este programa cargo antes
    for etiqueta in POR_PROGRAMA:
        ejecutar(f"MATCH (n:{etiqueta} {{program: $prog}}) DETACH DELETE n", prog=prog)
    ejecutar("MATCH (:Program {name: $prog})-[c:CALLS]->() DELETE c", prog=prog)

    ejecutar(
        "MERGE (p:Program {name: $prog}) "
        "SET p.external = false, p.pds = $pds, p.member = $miembro, p.member_pg_id = $mid",
        prog=prog, pds=pds, miembro=miembro, mid=member_id,
    )

    def run(consulta, filas):
        if filas:
            ejecutar(consulta, rows=filas, prog=prog)

    run("""UNWIND $rows AS r
           MATCH (p:Program {name: $prog})
           MERGE (v:Variable {uid: r.uid})
             SET v.name = r.name, v.program = $prog, v.declared = true
           MERGE (p)-[:HAS_VARIABLE]->(v)""", d["variables"])

    run("""UNWIND $rows AS r
           MATCH (p:Program {name: $prog})
           MERGE (g:Paragraph {uid: r.uid}) SET g.name = r.name, g.program = $prog
           MERGE (p)-[:CONTAINS]->(g)""", d["parrafos"])

    run("""UNWIND $rows AS r
           MATCH (p:Program {name: $prog})
           MERGE (t:Program {name: r.to}) ON CREATE SET t.external = true
           MERGE (p)-[:CALLS]->(t)""", d["calls"])

    run("""UNWIND $rows AS r
           MATCH (a:Program {name: $prog})
           MERGE (b:Paragraph {uid: r.to_uid}) ON CREATE SET b.name = r.to_name, b.program = $prog
           MERGE (a)-[:PERFORMS]->(b)""", d["perform_prog"])

    run("""UNWIND $rows AS r
           MERGE (a:Paragraph {uid: r.from_uid}) ON CREATE SET a.name = r.from_name, a.program = $prog
           MERGE (b:Paragraph {uid: r.to_uid})   ON CREATE SET b.name = r.to_name,   b.program = $prog
           MERGE (a)-[:PERFORMS]->(b)""", d["perform_parr"])

    run("""UNWIND $rows AS r
           MATCH (g:Paragraph {uid: r.par_uid})
           MERGE (o:Operation {uid: r.uid})
             SET o.type = r.type, o.seq = r.seq, o.value = r.value,
                 o.expression = r.expression, o.target = r.target, o.program = $prog
           MERGE (g)-[:HAS_OPERATION]->(o)""", d["ops"])

    for relacion, filas in (("WRITES", d["escribe"]), ("READS", d["lee"])):
        run(f"""UNWIND $rows AS r
                MATCH (o:Operation {{uid: r.op_uid}})
                MERGE (v:Variable {{uid: r.var_uid}})
                  ON CREATE SET v.name = r.var_name, v.program = $prog, v.declared = false
                MERGE (o)-[:{relacion}]->(v)""", filas)

    run("""UNWIND $rows AS r
           MATCH (g:Paragraph {uid: r.par_uid})
           MERGE (e:Evaluate {uid: r.uid}) SET e.expression = r.expression, e.program = $prog
           MERGE (g)-[:HAS_EVALUATE]->(e)""", d["evals"])

    run("""UNWIND $rows AS r
           MATCH (e:Evaluate {uid: r.e_uid}), (v:Variable {uid: r.var_uid})
           MERGE (e)-[:EVALUATES]->(v)""", d["evals_var"])

    run("""UNWIND $rows AS r
           MATCH (e:Evaluate {uid: r.e_uid})
           MERGE (w:When {uid: r.uid}) SET w.value = r.value, w.seq = r.seq, w.program = $prog
           MERGE (e)-[:HAS_WHEN]->(w)""", d["whens"])


def crear_esquema(driver):
    """Claves unicas e indices (los indices evitan recorrer todo el grafo en cada recarga)."""
    for etiqueta, prop in [("Program", "name"), ("Paragraph", "uid"), ("Variable", "uid"),
                           ("Operation", "uid"), ("Evaluate", "uid"), ("When", "uid")]:
        driver.execute_query(
            f"CREATE CONSTRAINT zdoc_{etiqueta.lower()}_{prop} IF NOT EXISTS "
            f"FOR (n:{etiqueta}) REQUIRE n.{prop} IS UNIQUE", database_=NEO4J_DATABASE)
    for etiqueta in POR_PROGRAMA:
        driver.execute_query(
            f"CREATE INDEX zdoc_{etiqueta.lower()}_program IF NOT EXISTS "
            f"FOR (n:{etiqueta}) ON (n.program)", database_=NEO4J_DATABASE)


def wipe(driver):
    resp = input(f"Esto borra los nodos {', '.join(TODAS)} de la base '{NEO4J_DATABASE}'. Escribi SI para continuar: ")
    if resp.strip() != "SI":
        sys.exit("Cancelado.")
    for etiqueta in TODAS:
        while True:
            recs, _, _ = driver.execute_query(
                f"MATCH (n:{etiqueta}) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS borrados",
                database_=NEO4J_DATABASE)
            if recs[0]["borrados"] == 0:
                break
        print(f"  {etiqueta}: borrado")


def resumen(driver):
    nodos, _, _ = driver.execute_query(
        "MATCH (n) UNWIND labels(n) AS l RETURN l AS etiqueta, count(*) AS n ORDER BY n DESC",
        database_=NEO4J_DATABASE)
    rels, _, _ = driver.execute_query(
        "MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS n ORDER BY n DESC",
        database_=NEO4J_DATABASE)
    print(f"\nContenido de '{NEO4J_DATABASE}':")
    for r in nodos:
        print(f"  nodos      {r['etiqueta']:<12}{r['n']:>7}")
    for r in rels:
        print(f"  relaciones {r['tipo']:<12}{r['n']:>7}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("miembro", nargs="?", help="cargar solo este miembro")
    ap.add_argument("--pds", help="limitar a un PDS")
    ap.add_argument("--limit", type=int, help="procesar solo los primeros N")
    ap.add_argument("--wipe", action="store_true", help="borrar lo cargado por este script")
    args = ap.parse_args()

    if not NEO4J_PASSWORD:
        sys.exit("Falta NEO4J_PASSWORD en el .env")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except (AuthError, ServiceUnavailable) as e:
        sys.exit(f"No se pudo conectar a Neo4j: {e}")

    with driver:
        if args.wipe:
            wipe(driver)
            return

        conn = psycopg2.connect(**PG_CONFIG)
        conn.set_session(readonly=True)
        with conn, conn.cursor() as cur:
            cur.execute(SQL_FUENTES, {"pds": args.pds,
                                      "miembro": args.miembro.upper() if args.miembro else None})
            fuentes = cur.fetchall()
        conn.close()
        if not fuentes:
            sys.exit("No hay miembros COBOL con fuente en zdoc_raw_data para ese filtro.")
        if args.limit:
            fuentes = fuentes[:args.limit]

        crear_esquema(driver)

        cargados, problemas, vistos = 0, [], {}
        primer_error = True
        for member_id, pds, miembro, texto in fuentes:
            try:
                r = parse_cobol(texto)
                if not r["program"]:
                    raise ValueError("no se encontro PROGRAM-ID")
                if r["program"] in vistos:
                    raise ValueError(f"PROGRAM-ID duplicado (ya cargado desde {vistos[r['program']]})")
                d = preparar(r)
                # sesion nueva por programa: si una conexion se rompe, no arrastra a las demas
                with driver.session(database=NEO4J_DATABASE) as session:
                    session.execute_write(cargar_programa, pds, miembro, member_id, d)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                problemas.append((pds, miembro, msg))
                print(f"  ERROR  {pds}({miembro}): {msg}")
                if primer_error:
                    traceback.print_exc()
                    primer_error = False
                continue
            vistos[r["program"]] = f"{pds}({miembro})"
            cargados += 1
            print(f"  OK     {pds}({miembro}) -> {d['prog']}: {len(d['variables'])} vars, "
                  f"{len(d['parrafos'])} parrafos, {len(d['ops'])} operaciones, {len(d['calls'])} calls")

        print(f"\nCargados: {cargados}   Con problemas: {len(problemas)}")
        resumen(driver)


if __name__ == "__main__":
    main()