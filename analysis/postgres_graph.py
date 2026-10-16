"""Construye el subgrafo COBOL desde las tablas normalizadas de PostgreSQL."""
from collections import defaultdict


NODOS_CON_PROGRAMA = [
    "Operation", "When", "Evaluate", "Paragraph", "Variable", "CobolVariable",
    "CobolFile", "CobolCall", "Copybook", "CobolRecord", "CobolField",
    "Condition88", "ConditionValue", "RecordEquivalence", "BusinessRule",
    "RuleField", "ParagraphField", "CobolDivision", "CobolSection",
    "JCL", "Step", "DDStatement", "JCLVariable", "Dependency",
]
ETIQUETAS_GRAFO = ["Program", "Member", "PDS", "RawData", *NODOS_CON_PROGRAMA]

DEPENDENCY_RELATIONS = {
    "INCLUDE": "INCLUDES", "PROC": "USES_PROC", "PROGRAM": "RUNS_PROGRAM",
    "COPYBOOK": "USES_COPYBOOK",
}


def _uid(tipo, valor):
    return f"{tipo}:{valor}"


def leer_programas(cur, pds=None, miembro=None):
    cur.execute(
        """SELECT c.id AS cobol_id, c.program_id, c.author, c.version,
                  c.timestamp, m.id AS miembro_id, m.nombre AS miembro,
                  m.tipo AS miembro_tipo, p.id AS pds_id, p.nombre AS pds,
                  m.raw_data_id
             FROM zdoc_cobol c
             LEFT JOIN zdoc_miembros m ON m.id = c.miembro_id
             LEFT JOIN zdoc_pds p ON p.id = m.pds_id
            WHERE (%s IS NULL OR p.nombre = %s)
              AND (%s IS NULL OR m.nombre = %s)
            ORDER BY p.nombre, m.nombre, c.id""",
        (pds, pds, miembro, miembro),
    )
    return [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]


def construir_subgrafo(cur, programa, parser_result=None):
    """Lee entidades y relaciones del programa mediante las FK del esquema zdoc."""
    cid, mid = programa["cobol_id"], programa["miembro_id"]
    nodes = defaultdict(dict)
    edges = []

    def add(label, uid, **props):
        nodes[label][uid] = {"uid": uid, "props": props}
        return uid

    def edge(from_label, from_uid, rel, to_label, to_uid, **props):
        if from_uid is not None and to_uid is not None:
            edges.append({"from_label": from_label, "from_uid": from_uid,
                          "type": rel, "to_label": to_label, "to_uid": to_uid,
                          "props": props})

    def rows(sql, params):
        cur.execute(sql, params)
        names = [col[0] for col in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    prog = programa["program_id"]
    p_uid = add("Program", prog, name=prog, external=False, pds=programa["pds"],
                member=programa["miembro"], member_pg_id=mid,
                cobol_pg_id=cid, author=programa["author"], version=programa["version"])

    if mid is not None:
        m_uid = add("Member", _uid("MEMBER", mid), pg_id=mid,
                    name=programa["miembro"], type=programa["miembro_tipo"])
        edge("Program", p_uid, "HAS_MEMBER", "Member", m_uid)
        if programa["pds_id"] is not None:
            d_uid = add("PDS", _uid("PDS", programa["pds_id"]),
                        pg_id=programa["pds_id"], name=programa["pds"])
            edge("Member", m_uid, "IN_PDS", "PDS", d_uid)
        if programa["raw_data_id"] is not None:
            raw_uid = add("RawData", _uid("RAW", programa["raw_data_id"]),
                          pg_id=programa["raw_data_id"])
            edge("Member", m_uid, "HAS_RAW_DATA", "RawData", raw_uid)

    def query(sql, params=(cid,)):
        return rows(sql, params)

    def ensure_member(member_id):
        uid = _uid("MEMBER", member_id)
        if uid in nodes["Member"]:
            return uid
        member_rows = rows("""SELECT m.nombre, p.nombre AS pds, p.id AS pds_id, m.tipo
                               FROM zdoc_miembros m LEFT JOIN zdoc_pds p ON p.id = m.pds_id
                              WHERE m.id = %s""", (member_id,))
        if member_rows:
            member = member_rows[0]
            add("Member", uid, pg_id=member_id, name=member["nombre"], type=member["tipo"])
            if member["pds_id"] is not None:
                pds_uid = _uid("PDS", member["pds_id"])
                add("PDS", pds_uid, pg_id=member["pds_id"], name=member["pds"])
                edge("Member", uid, "IN_PDS", "PDS", pds_uid)
        return uid

    variables = query("""SELECT id, seccion, nivel, nombre_variable, pic_clause, uso,
                              valor_inicial, copybook_origen_id, record_de_archivo
                         FROM zdoc_cobol_variables WHERE cobol_id = %s ORDER BY id""")
    for r in variables:
        uid = add("CobolVariable", _uid("VARIABLE", r["id"]), **{
            k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "HAS_VARIABLE", "CobolVariable", uid)
        if r["nivel"] == 88:
            condition_uid = add("Condition88", _uid("CONDITION88", f"VARIABLE:{r['id']}"),
                                name=r["nombre_variable"], seccion=r["seccion"])
            edge("CobolVariable", uid, "HAS_CONDITION", "Condition88", condition_uid)
        section = r["seccion"]
        if section:
            sec_uid = add("CobolSection", _uid("SECTION", f"{cid}:{section}"), name=section)
            edge("Program", p_uid, "HAS_SECTION", "CobolSection", sec_uid)
            edge("CobolSection", sec_uid, "DECLARES", "CobolVariable", uid)
            division_name = "FILE" if section.upper() == "FILE" else "DATA"
            div_uid = add("CobolDivision", _uid("DIVISION", f"{cid}:{division_name}"), name=division_name)
            edge("Program", p_uid, "HAS_DIVISION", "CobolDivision", div_uid)
            edge("CobolDivision", div_uid, "HAS_SECTION", "CobolSection", sec_uid)
        if r["copybook_origen_id"] is not None:
            edge("CobolVariable", uid, "FROM_COPYBOOK", "Copybook",
                 _uid("COPYBOOK", r["copybook_origen_id"]))
        if r["record_de_archivo"]:
            edge("CobolVariable", uid, "BELONGS_TO_FILE_RECORD", "CobolFile",
                 _uid("FILE_NAME", f"{cid}:{r['record_de_archivo']}"))

    for r in query("""SELECT id, nombre_archivo, assign_dd, organizacion, modo_acceso
                         FROM zdoc_cobol_archivos WHERE cobol_id = %s ORDER BY id"""):
        uid = add("CobolFile", _uid("FILE", r["id"]), **{k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "HAS_FILE", "CobolFile", uid)
        file_name_uid = _uid("FILE_NAME", f"{cid}:{r['nombre_archivo']}")
        add("CobolFile", file_name_uid, nombre_archivo=r["nombre_archivo"],
            assign_dd=r["assign_dd"], organizacion=r["organizacion"],
            modo_acceso=r["modo_acceso"])
        edge("Program", p_uid, "HAS_FILE", "CobolFile", file_name_uid)

    for r in query("""SELECT id, target_pgm_raw, target_miembro_id, es_dinamico
                         FROM zdoc_cobol_calls WHERE cobol_id = %s ORDER BY id"""):
        uid = add("CobolCall", _uid("CALL", r["id"]), **{k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "HAS_CALL", "CobolCall", uid)
        target_name = (r["target_pgm_raw"] or "").strip().strip("\"'")
        if target_name:
            target_uid = add("Program", target_name, name=target_name, external=True)
            edge("CobolCall", uid, "CALLS", "Program", target_uid)
        if r["target_miembro_id"] is not None:
            target = ensure_member(r["target_miembro_id"])
            edge("CobolCall", uid, "RESOLVES_TO", "Member", target)

    for r in query("""SELECT id, copy_nombre_raw, copy_miembro_id, reemplazos
                         FROM zdoc_cobol_copybooks WHERE cobol_id = %s ORDER BY id"""):
        uid = add("Copybook", _uid("COPYBOOK", r["id"]), **{k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "USES_COPYBOOK", "Copybook", uid)
        if r["copy_miembro_id"] is not None:
            target = ensure_member(r["copy_miembro_id"])
            edge("Copybook", uid, "RESOLVES_TO", "Member", target)

    paragraph_names = set()
    for r in query("""SELECT id, parrafo_origen, tipo_llamada, parrafo_destino,
                              tipo_destino, condicion, orden
                         FROM zdoc_flujo_parrafo WHERE cobol_id = %s ORDER BY orden, id"""):
        source, target = r["parrafo_origen"], r["parrafo_destino"]
        paragraph_names.update((source, target))
        source_uid = _uid("PARAGRAPH", f"{cid}:{source}")
        target_uid = _uid("PARAGRAPH", f"{cid}:{target}")
        add("Paragraph", source_uid, name=source)
        add("Paragraph", target_uid, name=target)
        rel = "GO_TO" if "GO" in (r["tipo_llamada"] or "").upper() else "PERFORMS"
        edge("Paragraph", source_uid, rel, "Paragraph", target_uid,
             program=prog, condition=r["condicion"], seq=r["orden"],
             call_type=r["tipo_llamada"], target_type=r["tipo_destino"])
        edge("Program", p_uid, "HAS_PARAGRAPH", "Paragraph", source_uid)
        edge("Program", p_uid, "HAS_PARAGRAPH", "Paragraph", target_uid)

    for name in paragraph_names:
        puid = _uid("PARAGRAPH", f"{cid}:{name}")
        add("Paragraph", puid, name=name)
        edge("Program", p_uid, "HAS_PARAGRAPH", "Paragraph", puid)

    if parser_result and parser_result.get("paragraphs"):
        declared = set(parser_result.get("variables", []))
        variables_by_name = {}
        for r in variables:
            variables_by_name.setdefault(r["nombre_variable"], []).append(_uid("VARIABLE", r["id"]))
        for paragraph in parser_result["paragraphs"]:
            name = paragraph["name"]
            puid = _uid("PARAGRAPH", f"{cid}:{name}")
            add("Paragraph", puid, name=name)
            edge("Program", p_uid, "HAS_PARAGRAPH", "Paragraph", puid)
            evals = paragraph.get("evaluates", [])
            for eval_index, ev in enumerate(evals):
                eval_uid = _uid("EVALUATE", f"{cid}:{name}:{eval_index}")
                eval_node = add("Evaluate", eval_uid, expression=ev.get("expression"))
                edge("Paragraph", puid, "HAS_EVALUATE", "Evaluate", eval_node)
                expression = ev.get("expression")
                if expression in declared:
                    var_uids = variables_by_name.get(expression, [])
                    if var_uids:
                        edge("Evaluate", eval_node, "EVALUATES", "CobolVariable", var_uids[0])
                for when_index, when in enumerate(ev.get("whens", [])):
                    when_uid = _uid("WHEN", f"{cid}:{name}:{eval_index}:{when_index}")
                    when_node = add("When", when_uid, value=when.get("when"), seq=when_index)
                    edge("Evaluate", eval_node, "HAS_WHEN", "When", when_node)
            for index, op in enumerate(paragraph.get("operations", [])):
                op_type = op.get("type")
                if op_type in ("CALL", "PERFORM"):
                    continue
                op_uid = _uid("OPERATION", f"{cid}:{name}:{index}")
                operation_uid = add("Operation", op_uid, type=op_type, seq=index,
                                    value=op.get("value"), expression=op.get("expression"),
                                    target=op.get("target"), condition=op.get("condition"),
                                    condition_context=op.get("condition_context"),
                                    context=op.get("context"))
                edge("Paragraph", puid, "HAS_OPERATION", "Operation", operation_uid)
                for relation, field in (("WRITES", "writes"), ("READS", "uses")):
                    for var_name in dict.fromkeys(op.get(field, [])):
                        var_uid = (variables_by_name.get(var_name) or
                                   [_uid("VARIABLE", f"{cid}:{var_name}")])[0]
                        if var_uid not in nodes["CobolVariable"]:
                            add("CobolVariable", var_uid, nombre_variable=var_name,
                                inferred_from_parser=True)
                            edge("Program", p_uid, "HAS_VARIABLE", "CobolVariable", var_uid)
                        edge("Operation", operation_uid, relation, "CobolVariable", var_uid)

    for r in query("""SELECT parrafo, campo, modo, statement, orden, sentencia
                         FROM zdoc_parrafo_campo WHERE cobol_id = %s ORDER BY parrafo, orden"""):
        name = r["parrafo"]
        paragraph_names.add(name)
        puid = _uid("PARAGRAPH", f"{cid}:{name}")
        add("Paragraph", puid, name=name)
        ref_uid = _uid("PARAGRAPH_FIELD", f"{cid}:{name}:{r['orden']}:{r['campo']}")
        add("ParagraphField", ref_uid, campo=r["campo"], modo=r["modo"],
            statement=r["statement"], orden=r["orden"], sentencia=r["sentencia"])
        edge("Program", p_uid, "HAS_PARAGRAPH", "Paragraph", puid)
        edge("Paragraph", puid, "REFERENCES_FIELD", "ParagraphField", ref_uid)

    record_rows = query("""SELECT id, miembro_id, registro_copybook_id, seccion, copybook_nombre,
                              fragmento, fd, ddname, registro, nivel, longitud,
                              record_contains, redefine, avisos, fecha_extraccion
                         FROM zdoc_registro
                         WHERE cobol_id = %s OR miembro_id = %s ORDER BY id""", (cid, mid))
    record_ids = [r["id"] for r in record_rows]
    for r in record_rows:
        uid = add("CobolRecord", _uid("RECORD", r["id"]), **{k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "HAS_RECORD", "CobolRecord", uid)
        if r["registro_copybook_id"] is not None:
            edge("CobolRecord", uid, "COPYBOOK_FRAGMENT_OF", "CobolRecord",
                 _uid("RECORD", r["registro_copybook_id"]))
    fields_by_id = {}
    if record_ids:
        fields = rows("""SELECT id, registro_id, seq, padre_seq, nivel, nombre, filler, grupo,
                              tipo, pic, uso, signo, signo_separado, digitos, decimales,
                              posicion, longitud, occurs_min, occurs_max, occurs_depending,
                              redefine, valor_inicial, descripcion, tipo_logico, confianza,
                              origen_descripcion, modelo_llm, revisado, revisado_por
                         FROM zdoc_registro_campo WHERE registro_id = ANY(%s) ORDER BY registro_id, seq""",
                      (record_ids,))
        seq_to_uid = {}
        for r in fields:
            rid = r["registro_id"]
            uid = add("CobolField", _uid("FIELD", r["id"]), **{k: v for k, v in r.items() if k != "id"})
            fields_by_id[r["id"]] = uid
            seq_to_uid[(rid, r["seq"])] = uid
            edge("CobolRecord", _uid("RECORD", rid), "HAS_FIELD", "CobolField", uid)
        for r in fields:
            if r["padre_seq"] is not None:
                parent = seq_to_uid.get((r["registro_id"], r["padre_seq"]))
                if parent:
                    edge("CobolField", parent, "HAS_CHILD_FIELD", "CobolField", fields_by_id[r["id"]])
            if r["nivel"] == 88:
                condition_uid = add("Condition88", _uid("CONDITION88", r["id"]),
                                    name=r["nombre"], field_id=r["registro_id"])
                edge("CobolField", fields_by_id[r["id"]], "HAS_CONDITION", "Condition88", condition_uid)
        for r in rows("""SELECT id, campo_id, condicion, valor_desde, valor_hasta, orden
                          FROM zdoc_campo_valor88 WHERE campo_id = ANY(%s) ORDER BY campo_id, orden""",
                      ([r["id"] for r in fields],)):
            uid = add("ConditionValue", _uid("CONDITION_VALUE", r["id"]),
                      condicion=r["condicion"], valor_desde=r["valor_desde"],
                      valor_hasta=r["valor_hasta"], orden=r["orden"])
            edge("CobolField", fields_by_id[r["campo_id"]], "HAS_CONDITION_VALUE", "ConditionValue", uid)

    for r in query("""SELECT id, registro_plano_id, campo_estructura_id, tipo, parrafo,
                              prioridad, longitud_plano, longitud_estructura
                         FROM zdoc_registro_equivalencia WHERE cobol_id = %s ORDER BY id"""):
        uid = add("RecordEquivalence", _uid("EQUIVALENCE", r["id"]), **{k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "HAS_EQUIVALENCE", "RecordEquivalence", uid)
        edge("RecordEquivalence", uid, "MAPS_RECORD", "CobolRecord", _uid("RECORD", r["registro_plano_id"]))
        edge("RecordEquivalence", uid, "MAPS_FIELD", "CobolField", _uid("FIELD", r["campo_estructura_id"]))

    for r in query("""SELECT id, parrafo, descripcion, condicion, modelo_llm,
                              fecha_extraccion, estado, revisado_por
                         FROM zdoc_regla_negocio WHERE cobol_id = %s ORDER BY id"""):
        uid = add("BusinessRule", _uid("RULE", r["id"]), **{k: v for k, v in r.items() if k != "id"})
        edge("Program", p_uid, "HAS_BUSINESS_RULE", "BusinessRule", uid)
        name = r["parrafo"]
        puid = _uid("PARAGRAPH", f"{cid}:{name}")
        add("Paragraph", puid, name=name)
        edge("Program", p_uid, "HAS_PARAGRAPH", "Paragraph", puid)
        edge("BusinessRule", uid, "DEFINED_IN", "Paragraph", puid)
        for field in rows("SELECT id, campo FROM zdoc_regla_negocio_campo WHERE regla_id = %s ORDER BY id", (r["id"],)):
            fuid = add("RuleField", _uid("RULE_FIELD", field["id"]), name=field["campo"])
            edge("BusinessRule", uid, "REFERENCES_FIELD", "RuleField", fuid)

    # JCL y dependencias compartidos por miembro. Los nodos fuente son globales;
    # cada enlace al programa se marca con program para reemplazo idempotente.
    if mid is not None:
        for r in rows('''SELECT id, version, "timestamp" FROM zdoc_jcl WHERE miembro_id = %s ORDER BY id''', (mid,)):
            juid = add("JCL", _uid("JCL", r["id"]), **{k: v for k, v in r.items() if k != "id"})
            edge("Program", p_uid, "HAS_JCL", "JCL", juid)
            steps = rows("""SELECT id, nombre, orden, pgm_nombre_raw, programa_miembro_id,
                                 proc_miembro_id, include_origen FROM zdoc_steps
                           WHERE jcl_id = %s ORDER BY orden, id""", (r["id"],))
            for s in steps:
                suid = add("Step", _uid("STEP", s["id"]), **{k: v for k, v in s.items() if k != "id"})
                edge("JCL", juid, "HAS_STEP", "Step", suid)
                if s["programa_miembro_id"] is not None:
                    edge("Step", suid, "RUNS_MEMBER", "Member", ensure_member(s["programa_miembro_id"]))
                if s["proc_miembro_id"] is not None:
                    edge("Step", suid, "USES_PROC", "Member", ensure_member(s["proc_miembro_id"]))
                for dd in rows("""SELECT id, dd_name, tipo, target_pds_id, target_miembro_id,
                                       disp_status, inline_raw_id, dsn_raw, member_raw
                                  FROM zdoc_steps_dd WHERE step_id = %s ORDER BY id""", (s["id"],)):
                    duid = add("DDStatement", _uid("DD", dd["id"]), **{k: v for k, v in dd.items() if k != "id"})
                    edge("Step", suid, "HAS_DD", "DDStatement", duid)
                    if dd["target_miembro_id"] is not None:
                        edge("DDStatement", duid, "TARGETS_MEMBER", "Member", _uid("MEMBER", dd["target_miembro_id"]))
                    if dd["target_pds_id"] is not None:
                        edge("DDStatement", duid, "TARGETS_PDS", "PDS", _uid("PDS", dd["target_pds_id"]))
            for v in rows("""SELECT id, jcl_id, jcl_step_id, proc_miembro_id, scope,
                                   var_name, var_value, include_origen FROM zdoc_jcl_vars
                              WHERE jcl_id = %s OR proc_miembro_id = %s ORDER BY id""", (r["id"], mid)):
                vuid = add("JCLVariable", _uid("JCL_VAR", v["id"]), **{k: v for k, v in v.items() if k != "id"})
                edge("JCL", juid, "HAS_VARIABLE", "JCLVariable", vuid)

        for dep in rows("""SELECT id, parent_miembro_id, child_miembro_id, dependency_type, context
                            FROM zdoc_dependencies
                           WHERE parent_miembro_id = %s OR child_miembro_id = %s ORDER BY id""", (mid, mid)):
            duid = add("Dependency", _uid("DEPENDENCY", dep["id"]),
                       dependency_type=dep["dependency_type"], context=dep["context"])
            edge("Member", _uid("MEMBER", dep["parent_miembro_id"]), "HAS_DEPENDENCY", "Dependency", duid)
            dependency_rel = DEPENDENCY_RELATIONS.get(dep["dependency_type"].upper(), "DEPENDS_ON")
            edge("Dependency", duid, dependency_rel, "Member",
                 _uid("MEMBER", dep["child_miembro_id"]))

    return {"prog": prog, "nodes": {k: list(v.values()) for k, v in nodes.items()}, "edges": edges}


def cargar_subgrafo(tx, pds, miembro, member_id, data):
    prog = data["prog"]
    tx.run("MATCH ()-[r {program: $prog}]-() DELETE r", prog=prog).consume()
    tx.run("""MATCH (n)
              WHERE n.program = $prog
                AND NOT n:Program AND NOT n:Member AND NOT n:PDS AND NOT n:RawData
              DETACH DELETE n""", prog=prog).consume()
    tx.run("""MERGE (p:Program {name: $prog})
              SET p.external = false, p.pds = $pds, p.member = $miembro,
                  p.member_pg_id = $mid, p.uid = $prog""",
           prog=prog, pds=pds, miembro=miembro, mid=member_id).consume()

    node_groups = []
    for label, items in data["nodes"].items():
        if not items:
            continue
        identity_key = "name" if label == "Program" else "uid"
        rows = [{"identity": {identity_key: item["uid"]},
                 "props": {**item["props"], "program": prog}}
                for item in items]
        node_groups.append({"label": label, "rows": rows})
    tx.run("""UNWIND $groups AS group
              CALL {
                  WITH group
                  UNWIND group.rows AS row
                  CALL apoc.merge.node([group.label], row.identity, row.props, row.props)
                  YIELD node
                  RETURN count(node) AS created
              }
              RETURN sum(created) AS created""",
           groups=node_groups).consume()

    grouped_edges = {}
    for edge in data["edges"]:
        key = (edge["from_label"], edge["type"], edge["to_label"])
        grouped_edges.setdefault(key, []).append({
            "from_uid": edge["from_uid"], "to_uid": edge["to_uid"],
            "props": {**edge["props"], "program": prog},
        })
    grouped_rows = [{"from_label": from_label, "relation": relation,
                     "to_label": to_label, "rows": rows}
                    for (from_label, relation, to_label), rows in grouped_edges.items()]
    for group in grouped_rows:
        group["rows"] = [{"from_uid": row["from_uid"], "to_uid": row["to_uid"],
                          "props": row["props"]} for row in group["rows"]]
    tx.run("""UNWIND $groups AS group
              CALL {
                  WITH group
                  UNWIND group.rows AS row
                  MATCH (a) WHERE group.from_label IN labels(a)
                    AND CASE WHEN group.from_label = 'Program'
                             THEN a.name = row.from_uid ELSE a.uid = row.from_uid END
                  MATCH (b) WHERE group.to_label IN labels(b)
                    AND CASE WHEN group.to_label = 'Program'
                             THEN b.name = row.to_uid ELSE b.uid = row.to_uid END
                  CALL apoc.merge.relationship(a, group.relation,
                       {program: $prog}, row.props, b, row.props)
                  YIELD rel
                  RETURN count(rel) AS created
              }
              RETURN sum(created) AS created""",
           groups=grouped_rows, prog=prog).consume()
