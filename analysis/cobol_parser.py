import re
import sys


# ============================================================
# PALABRAS RESERVADAS
# ============================================================

PALABRAS_RESERVADAS = {

    "THEN",
    "IF",
    "ELSE",
    "END-IF",
    "EVALUATE",
    "WHEN",
    "END-EVALUATE",
    "END",
    "OTHER",
    "MOVE",
    "COMPUTE",
    "PERFORM",
    "CALL",
    "GO",
    "GOBACK",
    "CONTINUE",
    "NEXT",
    "SENTENCE",
    "STOP",
    "RUN",
    "DISPLAY",
    "ACCEPT",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "OPEN",
    "CLOSE"
}


# ============================================================
# LIMPIAR LINEA
# ============================================================

def limpiar_linea(linea):

    linea = linea.rstrip()

    if not linea.strip():
        return ""

    # Comentario COBOL tradicional en columna 7
    if len(linea) >= 7:
        if linea[6] == "*":
            return ""

    texto = linea.strip()

    if texto.startswith("*"):
        return ""

    if texto.startswith("*>"):
        return ""

    return texto


# ============================================================
# DETECTAR VARIABLES USADAS
# ============================================================

def detectar_variables(texto, variables):
    """
    Detecta las variables utilizadas en una expresión
    respetando el orden en que aparecen en el texto.
    """

    encontrados = []

    for match in re.finditer(
        r"\b[A-Z0-9][A-Z0-9_-]*\b",
        texto.upper()
    ):

        nombre = match.group(0)

        if nombre in variables:
            if nombre not in encontrados:
                encontrados.append(nombre)

    return encontrados


# ============================================================
# NORMALIZAR CONDICION
# ============================================================

def normalizar_condicion(texto):
    """
    Normaliza condiciones COBOL manteniendo el significado.

    Ejemplos:

        WS-SALDO IS GREATER THAN 10000
            -> WS-SALDO > 10000

        WS-SALDO IS GREATER THAN OR EQUAL TO 10000
            -> WS-SALDO >= 10000

        WS-SALDO IS LESS THAN 10000
            -> WS-SALDO < 10000

        WS-SALDO IS LESS THAN OR EQUAL TO 10000
            -> WS-SALDO <= 10000

        WS-SALDO IS EQUAL TO 10000
            -> WS-SALDO = 10000

        WS-SALDO IS NOT EQUAL TO 10000
            -> WS-SALDO != 10000

        WS-SALDO NOT = 10000
            -> WS-SALDO != 10000
    """

    texto = texto.strip()

    # Normalizamos espacios múltiples
    texto = re.sub(r"\s+", " ", texto)

    # ============================================================
    # FORMAS LARGAS DE COBOL
    # ============================================================

    reemplazos = [
        (
            r"\bIS\s+GREATER\s+THAN\s+OR\s+EQUAL\s+TO\b",
            ">="
        ),
        (
            r"\bIS\s+LESS\s+THAN\s+OR\s+EQUAL\s+TO\b",
            "<="
        ),
        (
            r"\bIS\s+NOT\s+EQUAL\s+TO\b",
            "!="
        ),
        (
            r"\bIS\s+GREATER\s+THAN\b",
            ">"
        ),
        (
            r"\bIS\s+LESS\s+THAN\b",
            "<"
        ),
        (
            r"\bIS\s+EQUAL\s+TO\b",
            "="
        ),
    ]

    for patron, operador in reemplazos:
        texto = re.sub(
            patron,
            operador,
            texto,
            flags=re.IGNORECASE
        )

    # ============================================================
    # FORMAS CORTAS
    # ============================================================

    # NOT =  -> !=
    texto = re.sub(
        r"\bNOT\s*=",
        "!=",
        texto,
        flags=re.IGNORECASE
    )

    # NOT <  -> >=
    texto = re.sub(
        r"\bNOT\s*<",
        ">=",
        texto,
        flags=re.IGNORECASE
    )

    # NOT >  -> <=
    texto = re.sub(
        r"\bNOT\s*>",
        "<=",
        texto,
        flags=re.IGNORECASE
    )

    # ============================================================
    # LIMPIEZA FINAL
    # ============================================================

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


# ============================================================
# DETECTAR VARIABLES DE DATA DIVISION
# ============================================================

def detectar_variables_de_data_division(texto):

    variables = []

    for linea in texto.splitlines():

        linea_limpia = limpiar_linea(linea)

        if not linea_limpia:
            continue

        match = re.match(
            r"^\s*\d+\s+([A-Z0-9-]+)\s+PIC\b",
            linea_limpia,
            re.IGNORECASE
        )

        if match:

            variable = match.group(1).upper()

            if variable not in variables:
                variables.append(variable)

    return variables


# ============================================================
# CREAR MOVE
# ============================================================

def crear_move(
    value,
    target,
    variables,
    context=None,
    condition=None
):

    operacion = {
        "type": "MOVE",
        "value": value.strip(),
        "target": target.upper(),
        "uses": detectar_variables(
            value,
            variables
        ),
        "writes": [
            target.upper()
        ]
    }

    if context:
        operacion["context"] = context

    if condition:
        operacion["condition"] = condition

    return operacion


# ============================================================
# CREAR COMPUTE
# ============================================================

def crear_compute(
    target,
    expression,
    variables,
    context=None,
    condition=None
):

    operacion = {
        "type": "COMPUTE",
        "target": target.upper(),
        "expression": expression.strip(),
        "uses": detectar_variables(
            expression,
            variables
        ),
        "writes": [
            target.upper()
        ]
    }

    if context:
        operacion["context"] = context

    if condition:
        operacion["condition"] = condition

    return operacion
#============================= crear arbol logico
def crear_arbol_logico(expression):
    """
    Convierte una expresión lógica COBOL en un árbol.

    Soporta inicialmente:
        AND
        OR
        paréntesis

    Respeta la precedencia:
        AND antes que OR

    Ejemplo:

        A AND B OR C

    produce:

        OR
        ├── AND
        │   ├── A
        │   └── B
        └── C
    """

    tokens = re.findall(
        r"\(|\)|\bAND\b|\bOR\b|[^()\s]+(?:\s+(?:=|!=|>=|<=|>|<)\s+(?:'[^']*'|[^\s()]+))?",
        expression,
        re.IGNORECASE
    )

    tokens = [
        token.strip()
        for token in tokens
        if token.strip()
    ]

    posicion = 0

    def parse_expression():
        """
        OR tiene menor precedencia que AND.
        """

        nonlocal posicion

        nodo = parse_and()

        while (
            posicion < len(tokens)
            and tokens[posicion].upper() == "OR"
        ):

            posicion += 1

            derecho = parse_and()

            nodo = {
                "type": "LOGICAL",
                "operator": "OR",
                "left": nodo,
                "right": derecho
            }

        return nodo

    def parse_and():
        """
        AND tiene mayor precedencia que OR.
        """

        nonlocal posicion

        nodo = parse_factor()

        while (
            posicion < len(tokens)
            and tokens[posicion].upper() == "AND"
        ):

            posicion += 1

            derecho = parse_factor()

            nodo = {
                "type": "LOGICAL",
                "operator": "AND",
                "left": nodo,
                "right": derecho
            }

        return nodo

    def parse_factor():

        nonlocal posicion

        if posicion >= len(tokens):
            return None

        token = tokens[posicion]

        # --------------------------------
        # NOT
        # --------------------------------
        if token.upper() == "NOT":

            posicion += 1

            nodo = parse_factor()

            return {
                "type": "LOGICAL",
                "operator": "NOT",
                "operand": nodo
            }
        # --------------------------------
        # PARÉNTESIS
        # --------------------------------

        if token == "(":

            posicion += 1

            nodo = parse_expression()

            if (
                posicion < len(tokens)
                and tokens[posicion] == ")"
            ):
                posicion += 1

            return nodo

        # --------------------------------
        # COMPARACIÓN
        # --------------------------------

        partes = [token]

        posicion += 1

        while posicion < len(tokens):

            siguiente = tokens[posicion]

            if siguiente.upper() in (
                "AND",
                "OR"
            ):
                break

            if siguiente in (
                "(",
                ")"
            ):
                break

            partes.append(siguiente)

            posicion += 1

        return {
            "type": "COMPARISON",
            "expression": " ".join(partes)
        }

    if not tokens:
        return None

    return parse_expression()
# ============================================================
# CREAR CONDITION
# ============================================================

def crear_condition(expression, variables, nivel=0):
    raw_expression = expression.strip()

    normalized_expression = normalizar_condicion(
        raw_expression
    )

    logical_tree = crear_arbol_logico(
        normalized_expression
    )

    return {
        "type": "CONDITION",
        "expression": normalized_expression,
        "raw_expression": raw_expression,
        "normalized_expression": normalized_expression,
        "uses": detectar_variables(
            normalized_expression,
            variables
        ),
        "logical_tree": logical_tree,
        "level": nivel,
        "true": [],
        "false": []
    }

# ============================================================
# OBTENER CONTEXTO COMPLETO
# ============================================================

def obtener_contexto_condiciones(condition_stack):

    contexto = []

    for item in condition_stack:

        contexto.append({
            "condition": item["condition"]["expression"],
            "branch": item["branch"]
        })

    return contexto


# ============================================================
# OBTENER DESTINO DE UNA OPERACION
# ============================================================

def obtener_destino_operacion(
    paragraph_actual,
    condition_stack
):

    # No estamos dentro de ningún IF
    if not condition_stack:

        return paragraph_actual["operations"]

    # Estamos dentro del IF más interno
    condicion_actual = condition_stack[-1]["condition"]

    branch = condition_stack[-1]["branch"]

    return condicion_actual[
        branch.lower()
    ]


# ============================================================
# AGREGAR CONTEXTO COMPLETO A OPERACION
# ============================================================

def agregar_contexto_operacion(
    operacion,
    condition_stack
):

    if not condition_stack:
        return

    # --------------------------------------------------------
    # Guardamos TODO el camino de condiciones
    # --------------------------------------------------------

    contexto = obtener_contexto_condiciones(
        condition_stack
    )

    operacion["condition_context"] = contexto

    # --------------------------------------------------------
    # Mantenemos también estos campos por compatibilidad
    # con la versión anterior del parser.
    #
    # context  = rama de la condición más interna
    # condition = condición más interna
    # --------------------------------------------------------

    condicion_actual = condition_stack[-1]

    operacion["context"] = (
        condicion_actual["branch"]
    )

    operacion["condition"] = (
        condicion_actual["condition"]["expression"]
    )

def obtener_condicion_multilinea(lineas, indice):
    """
    Obtiene una condición IF que puede estar
    distribuida en varias líneas.

    Soporta:

        IF WS-SALDO > 10000
           AND WS-TIPO = 'A'
           OR WS-CATEGORIA = 'PREMIUM'

    y expresiones con paréntesis:

        IF NOT (
           WS-SALDO > 10000
           AND WS-TIPO = 'A'
        )

    Devuelve:

        expression
        índice de la primera línea que NO pertenece
        a la condición.
    """

    linea = limpiar_linea(
        lineas[indice]
    )

    match_if = re.match(
        r"IF\s+(.+)$",
        linea,
        re.IGNORECASE
    )

    if not match_if:
        return None, indice

    partes = []

    primera_parte = (
        match_if.group(1).strip()
    )

    partes.append(
        primera_parte
    )

    # --------------------------------------------------------
    # Profundidad de paréntesis
    # --------------------------------------------------------

    profundidad = (
        primera_parte.count("(")
        - primera_parte.count(")")
    )

    i = indice + 1

    while i < len(lineas):

        siguiente = limpiar_linea(
            lineas[i]
        )

        if not siguiente:
            i += 1
            continue

        # ----------------------------------------------------
        # Si estamos dentro de paréntesis, la expresión
        # continúa aunque la línea no empiece por AND/OR.
        # ----------------------------------------------------

        if profundidad > 0:

            partes.append(
                siguiente
            )

            profundidad += (
                siguiente.count("(")
                - siguiente.count(")")
            )

            i += 1

            continue

        # ----------------------------------------------------
        # Continuación con AND / OR
        # ----------------------------------------------------

        if re.match(
            r"^(AND|OR)\b",
            siguiente,
            re.IGNORECASE
        ):

            partes.append(
                siguiente
            )

            profundidad += (
                siguiente.count("(")
                - siguiente.count(")")
            )

            i += 1

            continue

        # ----------------------------------------------------
        # Continuación que comienza con )
        # ----------------------------------------------------

        if siguiente.startswith(")"):

            partes.append(
                siguiente
            )

            profundidad += (
                siguiente.count("(")
                - siguiente.count(")")
            )

            i += 1

            continue

        # ----------------------------------------------------
        # Ya terminó la condición
        # ----------------------------------------------------

        break

    expression = " ".join(
        partes
    )

    return expression, i
# ============================================================
# PARSER PRINCIPAL
# ============================================================

def parse_cobol(texto):

    variables = detectar_variables_de_data_division(
        texto
    )

    result = {
        "program": None,
        "variables": variables,
        "calls": [],
        "contains": [],
        "performs": [],
        "paragraphs": []
    }

    paragraph_actual = None

    # ========================================================
    # PILA DE CONDICIONES
    # ========================================================

    condition_stack = []
    evaluate_stack = []
    evaluate_actual = None

    lineas = texto.splitlines()

    i = 0

    while i < len(lineas):

        linea_original = lineas[i]

        linea = limpiar_linea(
            linea_original
        )

        if not linea:
            i += 1
            continue

        linea_mayuscula = linea.upper()
        # ====================================================
        # PROGRAM-ID
        # ====================================================

        match_program = re.search(
            r"\bPROGRAM-ID\.\s*([A-Z0-9_-]+)",
            linea,
            re.IGNORECASE
        )
        if match_program:

            result["program"] = (
                match_program.group(1).upper()
            )

            i += 1
            continue
        # ====================================================
        # PARAGRAPH
        # ====================================================

        match_paragraph = re.match(
            r"^([A-Z0-9][A-Z0-9_-]*)\.\s*$",
            linea,
            re.IGNORECASE
        )

        if match_paragraph:

            nombre = (
                match_paragraph.group(1).upper()
            )

            if nombre not in PALABRAS_RESERVADAS:

                # Nuevo párrafo:
                # cualquier IF anterior queda fuera
                condition_stack = []

                paragraph_actual = {
                    "name": nombre,
                    "moves": [],
                    "calculations": [],
                    "conditions": [],
                    "evaluates": [],
                    "operations": []
                }

                result["paragraphs"].append(
                    paragraph_actual
                )

                if result["program"]:

                    result["contains"].append({
                        "from": result["program"],
                        "to": nombre
                    })
                i += 1
                continue
        # ====================================================
        # EVALUATE
        # ====================================================

        match_evaluate = re.match(
            r"EVALUATE\s+(.+)$",
            linea,
            re.IGNORECASE
        )

        if match_evaluate:

            expression = (
                match_evaluate.group(1)
                .strip()
            )

            evaluate_actual = {
                "expression": expression,
                "whens": []
            }

            if paragraph_actual is not None:
                paragraph_actual["evaluates"].append(
                    evaluate_actual
                )

            evaluate_stack.append(
                evaluate_actual
            )

            i += 1
            continue

        # ====================================================
        # END-EVALUATE
        # ====================================================

        if re.match(
            r"END-EVALUATE\b",
            linea,
            re.IGNORECASE
        ):

            if evaluate_stack:

                evaluate_actual = (
                    evaluate_stack.pop()
                )

                evaluate_actual.pop(
                    "current_when",
                    None
                )

            if evaluate_stack:
                evaluate_actual = (
                    evaluate_stack[-1]
                )
            else:
                evaluate_actual = None

            i += 1
            continue
        # ====================================================
        # WHEN
        # ====================================================

        match_when = re.match(
            r"WHEN\s+(.+)$",
            linea,
            re.IGNORECASE
        )

        if match_when and evaluate_stack:

            expresion_when = (
                match_when.group(1)
                .strip()
            )

            evaluate_actual = evaluate_stack[-1]

            nueva_rama = {
                "when": expresion_when,
                "operations": []
            }

            evaluate_actual["whens"].append(
                nueva_rama
            )

            evaluate_actual["current_when"] = (
                nueva_rama
            )
            i += 1
            continue
        # ====================================================
        # CALL
        # ====================================================

        match_call = re.match(
            r"CALL\s+'([^']+)'",
            linea,
            re.IGNORECASE
        )

        if match_call:

            programa_llamado = (
                match_call.group(1).upper()
            )

            origen = result["program"]

            result["calls"].append({
                "from": origen,
                "to": programa_llamado
            })

            if paragraph_actual is not None:

                operacion = {
                    "type": "CALL",
                    "target": programa_llamado
                }

                destino = obtener_destino_operacion(
                    paragraph_actual,
                    condition_stack
                )

                destino.append(
                    operacion
                )
            i += 1
            continue

        # ====================================================
        # PERFORM
        # ====================================================

        match_perform = re.match(
            r"PERFORM\s+([A-Z0-9_-]+)",
            linea,
            re.IGNORECASE
        )

        if match_perform:

            nombre = (
                match_perform.group(1).upper()
            )

            if nombre not in PALABRAS_RESERVADAS:

                origen = (
                    paragraph_actual["name"]
                    if paragraph_actual
                    else result["program"]
                )

                result["performs"].append({
                    "from": origen,
                    "to": nombre
                })

                if paragraph_actual is not None:

                    operacion = {
                        "type": "PERFORM",
                        "target": nombre
                    }

                    destino = obtener_destino_operacion(
                        paragraph_actual,
                        condition_stack
                    )

                    destino.append(
                        operacion
                    )
            i += 1
            continue

        # ====================================================
        # IF
        # ====================================================

        match_if = re.match(
            r"IF\s+(.+)$",
            linea,
            re.IGNORECASE
        )

        if match_if:

            expression, nuevo_indice = (
                obtener_condicion_multilinea(
                    lineas,
                    i
                )
            )

            expression = re.sub(
                r"\s+THEN\s*$",
                "",
                expression,
                flags=re.IGNORECASE
            )

            i = nuevo_indice

            nivel = len(
                condition_stack
            )

            nueva_condicion = crear_condition(
                expression,
                variables,
                nivel
            )

            # ----------------------------------------------
            # Índice CONDITIONS
            # ----------------------------------------------

            if paragraph_actual is not None:

                paragraph_actual[
                    "conditions"
                ].append(
                    nueva_condicion
                )

            # ----------------------------------------------
            # Colocar dentro del padre
            # ----------------------------------------------

            if paragraph_actual is not None:

                if condition_stack:

                    padre = condition_stack[-1]

                    destino_padre = (
                        padre["condition"]
                        [
                            padre["branch"].lower()
                        ]
                    )

                    destino_padre.append(
                        nueva_condicion
                    )

                else:

                    paragraph_actual[
                        "operations"
                    ].append(
                        nueva_condicion
                    )

            # ----------------------------------------------
            # Entramos en TRUE
            # ----------------------------------------------

            condition_stack.append({
                "condition": nueva_condicion,
                "branch": "TRUE"
            })

            continue

        # ====================================================
        # ELSE
        # ====================================================

        if re.match(
            r"^ELSE\b",
            linea_mayuscula
        ):

            if condition_stack:

                condition_stack[-1][
                    "branch"
                ] = "FALSE"
            i += 1
            continue

        # ====================================================
        # END-IF
        # ====================================================

        if re.match(
            r"^END-IF\b",
            linea_mayuscula
        ):

            if condition_stack:

                condition_stack.pop()
            i += 1
            continue

        # ====================================================
        # NEXT SENTENCE
        # ====================================================

        if re.match(
            r"^NEXT\s+SENTENCE\b",
            linea_mayuscula
        ):

            operacion = {
                "type": "NEXT-SENTENCE"
            }

            agregar_contexto_operacion(
                operacion,
                condition_stack
            )

            if paragraph_actual is not None:

                destino = obtener_destino_operacion(
                    paragraph_actual,
                    condition_stack
                )

                destino.append(
                    operacion
                )
            i += 1
            continue

        # ====================================================
        # MOVE
        # ====================================================

        match_move = re.match(
            r"MOVE\s+(.+?)\s+TO\s+([A-Z0-9_-]+)",
            linea,
            re.IGNORECASE
        )

        if match_move:

            value = (
                match_move.group(1).strip()
            )

            target = (
                match_move.group(2).upper()
            )

            operacion = crear_move(
                value,
                target,
                variables
            )

            agregar_contexto_operacion(
                operacion,
                condition_stack
            )

            if paragraph_actual is not None:

                # Índice especializado
                paragraph_actual[
                    "moves"
                ].append(
                    operacion
                )

                # Flujo
                destino = obtener_destino_operacion(
                    paragraph_actual,
                    condition_stack
                )

                destino.append(
                    operacion
                )
            # ------------------------------------------------
            # EVALUATE / WHEN
            # ------------------------------------------------

            if (
                evaluate_actual is not None
                and evaluate_actual.get(
                    "current_when"
                ) is not None
            ):

                evaluate_actual[
                   "current_when"
                ]["operations"].append(
                    operacion
                )

        # ====================================================
        # COMPUTE
        # ====================================================

        match_compute = re.match(
            r"COMPUTE\s+([A-Z0-9_-]+)\s*=\s*(.+)",
            linea,
            re.IGNORECASE
        )

        if match_compute:

            target = (
                match_compute.group(1).upper()
            )

            expression = (
                match_compute.group(2).strip()
            )

            operacion = crear_compute(
                target,
                expression,
                variables
            )

            agregar_contexto_operacion(
                operacion,
                condition_stack
            )

            if paragraph_actual is not None:

                # Índice especializado
                paragraph_actual[
                    "calculations"
                ].append(
                    operacion
                )

                # Flujo
                destino = obtener_destino_operacion(
                    paragraph_actual,
                    condition_stack
                )

                destino.append(
                    operacion
                )
            i += 1
            continue

        # ====================================================
        # CONTINUE
        # ====================================================

        if re.match(
            r"^CONTINUE\b",
            linea_mayuscula
        ):

            operacion = {
                "type": "CONTINUE"
            }

            agregar_contexto_operacion(
                operacion,
                condition_stack
            )

            if paragraph_actual is not None:

                destino = obtener_destino_operacion(
                    paragraph_actual,
                    condition_stack
                )

                destino.append(
                    operacion
                )
            i += 1
            continue

        # ====================================================
        # PUNTO FINAL
        # ====================================================

        if linea.endswith("."):

            # El punto puede cerrar el alcance
            # de construcciones IF legacy.

            if condition_stack:

                condition_stack = []
            i += 1
            continue
        # ====================================================
        # LÍNEA NO RECONOCIDA
        # ====================================================

        i += 1

    return result


# ============================================================
# MOSTRAR CONTEXTO COMPLETO
# ============================================================

def mostrar_contexto_completo(
    operation,
    indent
):

    if "condition_context" not in operation:
        return

    print(
        indent,
        "CONDITION CONTEXT:"
    )

    for contexto in operation[
        "condition_context"
    ]:

        print(
            indent,
            f"  {contexto['branch']}: "
            f"{contexto['condition']}"
        )
#==================================================================
def mostrar_arbol_logico(nodo, indent="", prefijo=""):

    if not nodo:
        return

    tipo = nodo.get("type")

    if tipo == "LOGICAL":

        operador = nodo.get("operator")

        print(
            indent +
            prefijo +
            operador
        )

        # ----------------------------
        # NOT
        # ----------------------------

        if operador == "NOT":

            mostrar_arbol_logico(
                nodo.get("operand"),
                indent + "    ",
                "└── "
            )

            return

        # ----------------------------
        # AND / OR
        # ----------------------------

        mostrar_arbol_logico(
            nodo.get("left"),
            indent + "    ",
            "├── "
        )

        mostrar_arbol_logico(
            nodo.get("right"),
            indent + "    ",
            "└── "
        )

    elif tipo == "COMPARISON":

        print(
            indent +
            prefijo +
            nodo.get("expression", "")
        )
# ============================================================
# MOSTRAR OPERACION
# ============================================================

def mostrar_operacion(
    operation,
    indent
):

    tipo = operation.get(
        "type"
    )

    # --------------------------------------------------------
    # MOVE
    # --------------------------------------------------------

    if tipo == "MOVE":

        print(
            indent,
            f"MOVE: {operation['value']} "
            f"-> {operation['target']}"
        )

        print(
            indent,
            f"  USES: "
            f"{operation.get('uses', [])}"
        )

        if operation.get("logical_tree"):

            print(
                indent +
                "  LOGICAL TREE:"
            )

            mostrar_arbol_logico(
                operation["logical_tree"],
                indent + "    "
            )
        print(
            indent,
            f"  WRITES: "
            f"{operation.get('writes', [])}"
        )

        mostrar_contexto_completo(
            operation,
            indent + "  "
        )

    # --------------------------------------------------------
    # COMPUTE
    # --------------------------------------------------------

    elif tipo == "COMPUTE":

        print(
            indent,
            f"COMPUTE: {operation['target']} "
            f"= {operation['expression']}"
        )

        print(
            indent,
            f"  USES: "
            f"{operation.get('uses', [])}"
        )

        if operation.get("logical_tree"):

            print(
                indent +
                "  LOGICAL TREE:"
            )

            mostrar_arbol_logico(
                operation["logical_tree"],
                indent + "    "
            )
        print(
            indent,
            f"  WRITES: "
            f"{operation.get('writes', [])}"
        )

        mostrar_contexto_completo(
            operation,
            indent + "  "
        )

    # --------------------------------------------------------
    # CALL
    # --------------------------------------------------------

    elif tipo == "CALL":

        print(
            indent,
            f"CALL: {operation['target']}"
        )

    # --------------------------------------------------------
    # PERFORM
    # --------------------------------------------------------

    elif tipo == "PERFORM":

        print(
            indent,
            f"PERFORM: {operation['target']}"
        )

    # --------------------------------------------------------
    # NEXT SENTENCE
    # --------------------------------------------------------

    elif tipo == "NEXT-SENTENCE":

        print(
            indent,
            "NEXT SENTENCE"
        )

        mostrar_contexto_completo(
            operation,
            indent + "  "
        )

    # --------------------------------------------------------
    # CONTINUE
    # --------------------------------------------------------

    elif tipo == "CONTINUE":

        print(
            indent,
            "CONTINUE"
        )

        mostrar_contexto_completo(
            operation,
            indent + "  "
        )

    # --------------------------------------------------------
    # CONDITION
    # --------------------------------------------------------

    elif tipo == "CONDITION":

        print(
            indent,
            "CONDITION:"
        )

        print(
            indent,
            f"  RAW: "
            f"{operation.get('raw_expression', '')}"
        )

        print(
            indent,
            f"  NORMALIZED: "
            f"{operation.get('normalized_expression', operation.get('expression', ''))}"
        )

        print(
            indent,
            f"  USES: "
            f"{operation.get('uses', [])}"
        )

        if operation.get("logical_tree"):

            print(
                indent +
                "  LOGICAL TREE:"
            )

            mostrar_arbol_logico(
                operation["logical_tree"],
                indent + "    "
            )
        # ----------------------------------------------------
        # TRUE
        # ----------------------------------------------------

        print(
            indent,
            "  TRUE:"
        )

        for child in operation[
            "true"
        ]:

            mostrar_operacion(
                child,
                indent + "    "
            )

        # ----------------------------------------------------
        # FALSE
        # ----------------------------------------------------

        print(
            indent,
            "  FALSE:"
        )

        for child in operation[
            "false"
        ]:

            mostrar_operacion(
                child,
                indent + "    "
            )


# ============================================================
# MOSTRAR RESULTADO
# ============================================================

def mostrar_resultado(
    result
):

    print()
    print(
        "PROGRAM:"
    )

    print(
        result["program"]
    )

    print()
    print(
        "VARIABLES:"
    )

    for variable in result[
        "variables"
    ]:

        print(
            " ",
            variable
        )

    # ========================================================
    # CALLS
    # ========================================================

    print()
    print(
        "CALLS:"
    )

    for call in result[
        "calls"
    ]:

        print(
            f"  {call['from']} -> "
            f"{call['to']}"
        )

    # ========================================================
    # CONTAINS
    # ========================================================

    print()
    print(
        "CONTAINS:"
    )

    for contains in result[
        "contains"
    ]:

        print(
            f"  {contains['from']} -> "
            f"{contains['to']}"
        )

    # ========================================================
    # PERFORMS
    # ========================================================

    print()
    print(
        "PERFORMS:"
    )

    for perform in result[
        "performs"
    ]:

        print(
            f"  {perform['from']} -> "
            f"{perform['to']}"
        )

    # ========================================================
    # PARAGRAPHS
    # ========================================================

    print()
    print(
        "PARAGRAPHS:"
    )

    for paragraph in result[
        "paragraphs"
    ]:

        print()
        print(
            f"  {paragraph['name']}"
        )

        # ----------------------------------------------------
        # OPERATIONS
        # ----------------------------------------------------

        print(
            "    OPERATIONS:"
        )

        for operation in paragraph[
            "operations"
        ]:

            mostrar_operacion(
                operation,
                "      "
            )

        # ----------------------------------------------------
        # MOVES
        # ----------------------------------------------------

        print()
        print(
            "    MOVES:"
        )

        for move in paragraph[
            "moves"
        ]:

            print(
                f"       "
                f"{move['value']} -> "
                f"{move['target']}"
            )

            mostrar_contexto_completo(
                move,
                "         "
            )

        # ----------------------------------------------------
        # CALCULATIONS
        # ----------------------------------------------------

        print()
        print(
            "    CALCULATIONS:"
        )

        for calc in paragraph[
            "calculations"
        ]:

            print(
                f"       "
                f"{calc['target']} = "
                f"{calc['expression']}"
            )

            mostrar_contexto_completo(
                calc,
                "         "
            )

        # ----------------------------------------------------
        # CONDITIONS
        # ----------------------------------------------------

        print()
        print(
            "    CONDITIONS:"
        )

        for condition in paragraph[
            "conditions"
        ]:

            print(
                f"       "
                f"{condition['expression']}"
            )

            print(
                f"        USES: "
                f"{condition.get('uses', [])}"
            )

        # ----------------------------------------------------
        # EVALUATES
        # ----------------------------------------------------

        print()

        print(
            "    EVALUATES:"
        )

        for evaluate in paragraph.get(
            "evaluates",
            []
        ):

            print(
                f"       EVALUATE "
                f"{evaluate['expression']}"
            )

            for when in evaluate.get(
                "whens",
                []
            ):

                print(
                    f"          WHEN "
                    f"{when['when']}"
                )

                for operation in when.get(
                    "operations",
                    []
                ):

                    mostrar_operacion(
                        operation,
                        "             "
                    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:

        print(
            "Uso:"
        )

        print(
            "  python3 cobol_parser.py "
            "archivo.cbl"
        )

        sys.exit(1)

    archivo = sys.argv[1]

    try:

        with open(
            archivo,
            "r",
            encoding="utf-8"
        ) as f:

            texto = f.read()

    except UnicodeDecodeError:

        with open(
            archivo,
            "r",
            encoding="latin-1"
        ) as f:

            texto = f.read()

    result = parse_cobol(
        texto
    )

    mostrar_resultado(
        result
    )