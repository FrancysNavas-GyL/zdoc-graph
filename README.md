# zdoc-graph

Grafo en Neo4j a partir de la base zdoc (PostgreSQL) y del analisis de codigo COBOL.
Todo corre local: PostgreSQL + Neo4j Desktop + Python.

## Puesta en marcha

1. **Entorno Python**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows   (Linux/Mac: source .venv/bin/activate)
   pip install -r requirements.txt
   ```
2. **Postgres local**: crear la base y el esquema
   ```bash
   psql -U postgres -c "CREATE DATABASE zdoc_local;"
   psql -U postgres -d zdoc_local -f db/schema.sql
   ```
3. **.env**: copiar `.env.example` a `.env` y completar `DB_PASSWORD` y `NEO4J_PASSWORD`.
4. **Datos de prueba**: `python db/seed.py`
5. **Verificar Postgres**: `python step1_postgres.py`
6. **Neo4j Desktop**: iniciar la instancia y crear la base (en Neo4j Browser):
   `CREATE DATABASE zdocgraph`. Luego `python step2_neo4j.py`.

## Estructura

| Ruta | Para que |
|---|---|
| `config.py` | unico lugar que lee el `.env` |
| `db/schema.sql`, `db/seed.py` | esquema y datos de prueba del Postgres local |
| `cobol/` | fuentes COBOL de ejemplo |
| `step1_postgres.py`, `step2_neo4j.py` | verificacion de conexiones (solo lectura) |
