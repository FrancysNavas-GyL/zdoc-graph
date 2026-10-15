"""
Diagnostico de la conexion a Neo4j: aisla si el problema es el driver, la version o la carga.
Escribe solo un nodo temporal (:_Diag) y lo borra al final.

    python diagnostico_neo4j.py
"""
import platform
import traceback

import neo4j
from neo4j import GraphDatabase

from config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

print("Python        :", platform.python_version(), platform.system())
print("Driver neo4j  :", neo4j.__version__)


def prueba(nombre, fn):
    try:
        res = fn()
        print(f"OK     {nombre}" + (f"  -> {res}" if res else ""))
    except BaseException as e:
        print(f"FALLA  {nombre}\n       {type(e).__name__}: {e!r}")
        traceback.print_exc(limit=3)


driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

prueba("1. verify_connectivity", driver.verify_connectivity)

prueba("2. version del servidor", lambda: [
    (r["name"], r["versions"], r["edition"]) for r in driver.execute_query(
        "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition",
        database_="system")[0]])

prueba("3. execute_query de escritura", lambda: driver.execute_query(
    "MERGE (:_Diag {id: 1})", database_=NEO4J_DATABASE)[1].counters.nodes_created)


def sesion_sin_consumir():
    def fn(tx):
        tx.run("MERGE (:_Diag {id: 2})")
        tx.run("UNWIND $rows AS r MERGE (:_Diag {id: r})", rows=[3, 4, 5])
    with driver.session(database=NEO4J_DATABASE) as s:
        s.execute_write(fn)


def sesion_consumiendo():
    def fn(tx):
        tx.run("MERGE (:_Diag {id: 6})").consume()
        tx.run("UNWIND $rows AS r MERGE (:_Diag {id: r})", rows=[7, 8, 9]).consume()
    with driver.session(database=NEO4J_DATABASE) as s:
        s.execute_write(fn)


prueba("4. sesion + execute_write (sin consumir)", sesion_sin_consumir)
prueba("5. sesion + execute_write (consumiendo)", sesion_consumiendo)
prueba("6. limpieza", lambda: driver.execute_query(
    "MATCH (n:_Diag) DETACH DELETE n", database_=NEO4J_DATABASE)[1].counters.nodes_deleted)

driver.close()