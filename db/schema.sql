-- Esquema zdoc (subconjunto de ZDOCDB.sql con los ALTER ya incorporados).
-- Para una base local de desarrollo. Las tablas del extractor (zdoc_registro*, zdoc_flujo_parrafo...)
-- no estan aca; se agregan cuando las necesitemos.

CREATE TABLE IF NOT EXISTS zdoc_pds (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS zdoc_raw_data (
    id SERIAL PRIMARY KEY,
    contenido TEXT NOT NULL,
    tipo VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS zdoc_miembros (
    id SERIAL PRIMARY KEY,
    pds_id INT REFERENCES zdoc_pds(id) ON DELETE CASCADE,
    nombre VARCHAR(8) NOT NULL,
    raw_data_id INT REFERENCES zdoc_raw_data(id),
    tipo VARCHAR(50),
    UNIQUE (pds_id, nombre)
);

CREATE TABLE IF NOT EXISTS zdoc_jcl (
    id SERIAL PRIMARY KEY,
    miembro_id INT REFERENCES zdoc_miembros(id) ON DELETE CASCADE,
    version INT DEFAULT 1,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS zdoc_steps (
    id SERIAL PRIMARY KEY,
    jcl_id INT REFERENCES zdoc_jcl(id) ON DELETE CASCADE,
    nombre VARCHAR(8) NOT NULL,
    orden INT NOT NULL,
    pgm_nombre_raw VARCHAR(8),
    programa_miembro_id INT REFERENCES zdoc_miembros(id),
    proc_miembro_id INT REFERENCES zdoc_miembros(id),
    include_origen VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS zdoc_steps_dd (
    id SERIAL PRIMARY KEY,
    step_id INT REFERENCES zdoc_steps(id) ON DELETE CASCADE,
    dd_name VARCHAR(8) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    target_pds_id INT REFERENCES zdoc_pds(id),
    target_miembro_id INT REFERENCES zdoc_miembros(id),
    disp_status VARCHAR(20),
    inline_raw_id INT REFERENCES zdoc_raw_data(id),
    dsn_raw VARCHAR(255),
    member_raw VARCHAR(8)
);

CREATE TABLE IF NOT EXISTS zdoc_jcl_vars (
    id SERIAL PRIMARY KEY,
    jcl_id INTEGER REFERENCES zdoc_jcl(id) ON DELETE CASCADE,
    jcl_step_id INTEGER REFERENCES zdoc_steps(id) ON DELETE CASCADE,
    proc_miembro_id INTEGER REFERENCES zdoc_miembros(id) ON DELETE CASCADE,
    scope VARCHAR(20) NOT NULL,
    var_name VARCHAR(50) NOT NULL,
    var_value VARCHAR(100),
    include_origen VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS zdoc_cobol (
    id SERIAL PRIMARY KEY,
    miembro_id INT REFERENCES zdoc_miembros(id) ON DELETE CASCADE,
    program_id VARCHAR(30) NOT NULL,
    author VARCHAR(50),
    version INT DEFAULT 1,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS zdoc_cobol_archivos (
    id SERIAL PRIMARY KEY,
    cobol_id INT REFERENCES zdoc_cobol(id) ON DELETE CASCADE,
    nombre_archivo VARCHAR(50) NOT NULL,
    assign_dd VARCHAR(8) NOT NULL,
    organizacion VARCHAR(20),
    modo_acceso VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS zdoc_cobol_copybooks (
    id SERIAL PRIMARY KEY,
    cobol_id INT REFERENCES zdoc_cobol(id) ON DELETE CASCADE,
    copy_nombre_raw VARCHAR(8) NOT NULL,
    copy_miembro_id INT REFERENCES zdoc_miembros(id),
    reemplazos TEXT
);

CREATE TABLE IF NOT EXISTS zdoc_cobol_variables (
    id SERIAL PRIMARY KEY,
    cobol_id INT REFERENCES zdoc_cobol(id) ON DELETE CASCADE,
    seccion VARCHAR(30) NOT NULL,
    nivel INT NOT NULL,
    nombre_variable VARCHAR(50) NOT NULL,
    pic_clause VARCHAR(50),
    uso VARCHAR(20),
    valor_inicial TEXT,
    copybook_origen_id INT REFERENCES zdoc_cobol_copybooks(id) ON DELETE CASCADE,
    record_de_archivo VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS zdoc_cobol_calls (
    id SERIAL PRIMARY KEY,
    cobol_id INT REFERENCES zdoc_cobol(id) ON DELETE CASCADE,
    target_pgm_raw VARCHAR(50) NOT NULL,
    target_miembro_id INT REFERENCES zdoc_miembros(id),
    es_dinamico BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS zdoc_dependencies (
    id SERIAL PRIMARY KEY,
    parent_miembro_id INT NOT NULL,
    child_miembro_id INT NOT NULL,
    dependency_type VARCHAR(20) NOT NULL,
    context VARCHAR(255),
    UNIQUE (parent_miembro_id, child_miembro_id, dependency_type)
);
