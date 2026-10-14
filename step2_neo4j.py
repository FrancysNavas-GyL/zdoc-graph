"""
PASO 2: verificar la conexion a Neo4j (Desktop) y ver que hay en la base configurada.
Solo lectura: no crea ni borra nada.

    python step2_neo4j.py
"""
import sys

from neo4j import GraphDatabase, RoutingControl
from neo4j.exceptions import AuthError, ServiceUnavailable

from config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


def main():
    if not NEO4J_PASSWORD:
        sys.exit("Falta NEO4J_PASSWORD en el .env")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except AuthError:
        sys.exit("Usuario o password incorrectos (revisa NEO4J_USER / NEO4J_PASSWORD).")
    except ServiceUnavailable as e:
        sys.exit(
            f"No se pudo conectar a {NEO4J_URI}.\n"
            "Revisa que la instancia este iniciada (verde) en Neo4j Desktop y que el puerto Bolt sea el correcto.\n"
            f"Detalle: {e}"
        )

    with driver:
        print(f"Conectado a {NEO4J_URI} como {NEO4J_USER}")

        # Bases disponibles (se consulta sobre 'system')
        dbs, _, _ = driver.execute_query(
            "SHOW DATABASES YIELD name, currentStatus RETURN name, currentStatus ORDER BY name",
            database_="system", routing_=RoutingControl.READ,
        )
        print("\nBases en la instancia:")
        for r in dbs:
            marca = "  <-- la que usamos" if r["name"] == NEO4J_DATABASE else ""
            print(f"  {r['name']:<20}{r['currentStatus']}{marca}")

        if NEO4J_DATABASE not in [r["name"] for r in dbs]:
            sys.exit(f"\nLa base '{NEO4J_DATABASE}' no existe en esta instancia.")

        # Contenido actual (solo conteos)
        etiquetas, _, _ = driver.execute_query(
            "MATCH (n) UNWIND labels(n) AS etiqueta RETURN etiqueta, count(*) AS n ORDER BY n DESC",
            database_=NEO4J_DATABASE, routing_=RoutingControl.READ,
        )
        rels, _, _ = driver.execute_query(
            "MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS n ORDER BY n DESC",
            database_=NEO4J_DATABASE, routing_=RoutingControl.READ,
        )

        print(f"\nNodos en '{NEO4J_DATABASE}':")
        for r in etiquetas or []:
            print(f"  {r['etiqueta']:<22}{r['n']:>8}")
        if not etiquetas:
            print("  (vacia)")

        print("\nRelaciones:")
        for r in rels or []:
            print(f"  {r['tipo']:<22}{r['n']:>8}")
        if not rels:
            print("  (ninguna)")


if __name__ == "__main__":
    main()
