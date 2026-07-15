# Decisiones de diseño — Challenge RoomBooking (Promtior)

Log de las decisiones de diseño que tomé, con su justificación y las alternativas que
descarté. El resumen para leer de corrido está en el [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md);
este archivo es el detalle, con un ID por decisión que el código referencia en sus
comentarios.

---

## D1 — Orquestación del agente: LangChain

**Decisión:** uso LangChain para orquestar el agente con tool-calling.

**Por qué:**
- El challenge sugiere LangChain de forma explícita y repetida, así que uso la herramienta
  que Promtior usa.
- Lo importante es la arquitectura agéntica y el tool-calling limpio, no la librería en sí,
  pero me alineo con el stack que recomiendan.
- Cubre el único gap que tenía yo: venía de orquestar agentes in-house, no con LangChain.

**Alternativa descartada:** tool-calling nativo del proveedor (function calling de
OpenAI/Groq) hecho a mano. Da más control, pero no muestra LangChain, que es lo que piden.

---

## D2 — LLM: OpenAI, default `gpt-4o`, configurable por env var

**Decisión:** uso la API de OpenAI con `gpt-4o` como modelo por defecto, seleccionable con
una variable de entorno (`OPENAI_MODEL`).

**Por qué:**
- El PDF recomienda OpenAI API si uno tiene suscripción, y yo tengo crédito disponible.
- Arranqué con `gpt-4o-mini` por barato, pero lo subí a `gpt-4o` cuando vi que el mini no
  respetaba de forma confiable la instrucción de pedir los datos faltantes: ante "reservá
  la sala B a las 15 para 2" reservaba un slot de 30 minutos en silencio, aunque el prompt,
  el docstring de la tool y un ejemplo few-shot se lo prohibían. `gpt-4o` obedece. Los
  requests son chicos (system prompt corto y mensajes breves), así que el costo por
  conversación es marginal.
- Lo dejo configurable por env var para poder bajarlo o subirlo sin tocar código.

**Alternativas descartadas:** seguir en `gpt-4o-mini` (más barato, pero incumple el
requisito de preguntar en vez de asumir); Groq/Ollama/OpenRouter (las opciones que da el
PDF para quien no tiene suscripción, no es mi caso).

---

## D3 — Sin backoffice en el MVP (revertida en D16)

**Decisión inicial:** no construir un backoffice; dejarlo como extensión futura.

**Por qué en su momento:** no está en los requerimientos del challenge, y quería priorizar
un MVP que cumpliera el 100% de lo pedido dentro de los 7 días de validez.

**Actualización:** terminé construyéndolo igual porque me servía para verificar y corregir
las reservas durante la demo. La decisión final y su alcance están en D16.

---

## D4 — Persistencia: SQLite + SQLAlchemy

**Decisión:** SQLite como base de datos, accedida con SQLAlchemy.

**Por qué:**
- El dominio es relacional y transaccional: la regla central (no solapamiento) es una range
  query (`WHERE room = ? AND start < :end AND end > :start`) y la doble reserva se previene
  con una transacción, que es justo lo que un motor relacional resuelve.
- El alcance real es de 2 usuarios, 5 salas y una demo de días. Cero infra, cero costo.
- SQLAlchemy desacopla el motor: migrar a Postgres el día que haga falta es cambiar la
  connection string.

**Alternativas descartadas:**
- **NoSQL (DynamoDB/Mongo):** modelar el no-solapamiento necesita writes condicionales por
  slot o filtrado en la aplicación, y una reserva de 3 h implica transacciones sobre 6
  items. Más código para el mismo resultado, y las ventajas de NoSQL (esquema flexible,
  escala horizontal) no aplican a este dominio.
- **In-memory:** se pierde al reiniciar, inaceptable para una demo pública.

---

## D5 — Deploy: Docker en AWS Lightsail

**Decisión:** un único contenedor Docker corriendo en una instancia Lightsail (precio fijo
de unos 5 USD/mes, con IP y disco persistente incluidos).

**Por qué:**
- El disco persistente hace compatible el SQLite (D4): el archivo sobrevive a los
  reinicios.
- Paridad dev/prod total: el mismo Dockerfile corre local y en la nube, y es parte del
  entregable.
- Always-warm: sin cold starts cuando el evaluador entra.
- Uso AWS, que es mi experiencia real, cumpliendo el "deploy on a cloud of your choice".

**Alternativas descartadas:**
- **Lambda + API Gateway:** cold starts en un chat, packaging pesado de LangChain, y un
  filesystem efímero que empuja a DynamoDB o RDS. Cuatro o cinco piezas de infra para 2
  usuarios.
- **Fargate / App Runner:** storage efímero (mata el SQLite) y más caro que Lightsail para
  un servicio always-on chico (con el balanceador que necesita para una IP estable, del
  orden de 25 USD/mes).
- **RDS (Postgres administrado):** unos 15 USD/mes y otra pieza que mantener, para un
  dominio que SQLite resuelve de sobra.
- **Railway (tip del PDF):** válido y rápido, pero no muestra AWS.

---

## D6 — Auth: login form + JWT, fuera del chat

**Decisión:** login clásico (form, `POST /login`, JWT firmado) antes de entrar al chat.
Cada request al chat lleva el token, el backend resuelve la identidad y las tools operan en
nombre del usuario autenticado. Passwords hasheados con bcrypt aunque sea una demo.

**Por qué:**
- El LLM nunca ve credenciales. Un login conversacional haría viajar el password por el
  historial del chat hacia la API de OpenAI y los logs, que es mala práctica de seguridad.
- La identidad llega al agente como contexto ya validado, no como texto del usuario: no se
  puede suplantar a otro prompteando al bot.
- JWT es estándar, stateless y simple de implementar en FastAPI.

**Alternativas descartadas:** login conversacional vía tool (password expuesto al LLM);
HTTP Basic (sin logout ni sesión, se siente un atajo).

---

## D7 — UI: página HTML/JS propia servida por FastAPI

**Decisión:** una única página estática (login más chat, JS vanilla) servida por el mismo
backend FastAPI. Un solo contenedor, un solo proceso.

**Por qué:**
- Dejo a la vista todo el flujo (login, token, chat, agente, tools, DB), sin capas mágicas.
- Control total del flujo de auth (D6), que es donde quería poner el foco.
- Un solo artefacto deployable (D5): sin CORS, sin build de frontend, sin un servicio extra.

**Alternativas descartadas:** Chainlit (rápido y con auth built-in, pero es una dependencia
opinionada que esconde el plumbing que quería mostrar); Streamlit/Gradio (auth y patrón de
chat incómodos).

---

## D8 — Agente: `create_agent` de LangChain 1.x (sobre LangGraph)

**Decisión:** construyo el agente con `create_agent`, la API estándar de LangChain 1.x, que
corre sobre LangGraph.

**Por qué:**
- Es el camino actual y recomendado de LangChain: trae el loop ReAct, el tool-calling
  nativo y el checkpointing para la memoria de conversación ya resueltos.
- `AgentExecutor` (el legacy) está deprecado, así que usarlo sería un retroceso.
- Un loop manual con `.bind_tools()` daría más control pero reinventa lo que la librería ya
  resuelve, y el challenge premia usar LangChain de forma idiomática.

---

## D9 — Tooling: uv + pyproject.toml, Python 3.12

**Decisión:** gestiono las dependencias con `uv` y `pyproject.toml` (con lockfile).

**Por qué:** es rápido, determinista y estándar moderno, y me simplifica el Dockerfile (D5).
Descarté pip/requirements.txt (sin lock real) y Poetry (más pesado, sin ventaja hoy).

---

## D10 — Defaults de dominio (lo que el PDF no especifica)

**Decisión:** donde el enunciado deja libertad, definí defaults simples y los dejé
documentados:

| Aspecto | Default elegido | Razón |
|---|---|---|
| Capacidades | A:2, B:4, C:6, D:8, E:10 | El PDF exige una capacidad máxima por sala pero no da valores; es una escalera fácil de recordar y testear. |
| Horario de oficina | Sin restricción (24/7) | El PDF no lo pide; no inventar reglas es menos edge cases. Extensión futura. |
| Timezone | America/Montevideo, única | Cubo Itaú está en Montevideo; multi-timezone queda fuera de alcance. |
| Idioma del bot | Responde en el idioma del usuario (ES/EN) | El LLM lo maneja sin lógica extra. |

---

## D11 — Guardrails del agente: limitar al LLM en todo lo posible

**Principio:** el LLM solo elige qué tool llamar; ninguna regla de negocio ni dato sensible
depende de él.

**Decisiones concretas:**

1. **Identidad inyectada, no parametrizada.** Las tools se construyen por request con
   closures sobre el usuario autenticado (del JWT). `user_id` no es parámetro de ninguna
   tool, así que el LLM no puede reservar ni cancelar en nombre de otro, diga lo que diga el
   chat.
2. **Errores como datos, no excepciones.** Las violaciones de regla vuelven como strings
   (`BOOKING REJECTED: ...`); el agente solo puede relatarlas y ofrecer alternativas.
3. **Fecha y hora actual inyectadas en el system prompt** por request, porque el LLM no
   tiene reloj y sin eso no puede resolver "mañana a las 10".
4. **Memoria por sesión de login:** checkpointer `InMemorySaver` de LangGraph, un
   `thread_id` por sesión. Es volátil a propósito: un restart desloguea a todos igual.
5. **Ventana de contexto acotada:** `SummarizationMiddleware` (built-in de LangChain 1.x)
   comprime los turnos viejos al pasar los ~3000 tokens. El motivo principal es el techo de
   costo en un deploy público con mi crédito (cada turno reenvía el historial completo), no
   el límite de 128k. Lo preferí sobre un trimming a mano (la librería ya lo resuelve sin
   partir los pares tool-call/tool-result) y sobre no hacer nada (costo sin techo).
6. **Techo de iteraciones:** `ModelCallLimitMiddleware` con máximo 10 llamadas al modelo por
   mensaje, para cortar loops descontrolados y su costo.
7. **`temperature=0`:** es tool-calling estructurado, no creatividad.

---

## D12 — API de chat: `POST /chat` síncrono, sesión de chat = `jti` del JWT

**Decisiones concretas:**

1. **`thread_id` = claim `jti` del JWT.** Cada login genera un session-id aleatorio que
   LangGraph usa como clave de la conversación: login nuevo, conversación nueva, sin estado
   extra en el servidor (el JWT ya viaja en cada request). Coherente con la memoria volátil
   de D11.
2. **Respuesta bloqueante, sin streaming.** Con respuestas cortas la latencia percibida no
   justifica SSE/WebSockets en el MVP. La UI muestra un indicador de "escribiendo". El
   streaming queda como mejora futura.
3. **Token JWT solo en memoria del navegador** (variable JS, no `localStorage`): un refresh
   implica re-login. Menos superficie ante XSS, y coherente con que la memoria de
   conversación del servidor también es volátil.
4. **Errores del agente a HTTP 502 genérico.** Si OpenAI falla, el detalle queda en el log
   del servidor y el cliente recibe un mensaje neutro, sin filtrar internals.

---

## D13 — Carrera de doble reserva: cerrada con lock de proceso

**Problema:** FastAPI atiende los endpoints sync desde un threadpool, así que dos requests
simultáneos podían intercalarse entre el chequeo de solapamiento y el INSERT (un
check-then-insert no atómico) y crear dos reservas solapadas sin que ningún request viera
el conflicto.

**Decisión:** un `threading.Lock` de proceso alrededor de la sección chequeo-de-conflictos
más insert en `service.create_booking`. Lo verifiqué con un test de concurrencia real: 10
threads sincronizados con una barrera intentan la misma reserva y exactamente uno gana.

**Por qué alcanza:** el deploy es un único proceso (un contenedor, D5), así que no hay
concurrencia fuera de ese proceso y el lock cubre el 100% de los casos reales.

**Límite conocido:** con varios procesos o réplicas el lock dejaría de alcanzar; ahí la
garantía tendría que bajar a la base (un exclusion constraint de Postgres sobre
`(room_id, tsrange(start, end))`), que rechaza el segundo insert aunque la aplicación tenga
la carrera.

**Alternativas descartadas:** `BEGIN IMMEDIATE` (acopla el service al dialecto SQLite);
dejarlo solo documentado sin cerrar (defendible, pero cerrarlo me costó tres líneas y un
test).

---

## D14 — Una sesión de DB por invocación de tool

**Problema:** el `ToolNode` de LangChain ejecuta las tool calls de un mismo turno del modelo
en threads paralelos (`executor.map`), y el modelo de OpenAI emite tool calls paralelas por
defecto ("reservá la sala B y la C" son dos calls simultáneas). Las tools compartían la
`Session` de SQLAlchemy del request (que no es thread-safe) vía closure. Lo reproduje: 24 de
40 iteraciones fallaban, la mitad con `sqlite3.InterfaceError` (que termina en 502) y la
otra mitad con resultados silenciosamente falsos ("Room 'C' does not exist") que el agente
relataba como ciertos.

**Decisión:** `build_tools` recibe un session factory (`Callable[[], Session]`) en lugar de
una sesión, y cada invocación de tool abre y cierra la suya. La identidad se captura como
valores planos (`user.id`, `user.username`), porque la instancia ORM pertenece a la sesión
del request, que no debe tocarse desde los threads de las tools. Lo verifiqué con un test
que ejecuta creates y lecturas concurrentes en threads, el mismo patrón de ejecución que el
`ToolNode`.

**Alternativas descartadas:** `parallel_tool_calls=False` en el modelo (no ataca la causa
raíz, pierde paralelismo legítimo y depende de un flag del proveedor); un lock por request
serializando las tools (un parche que deja la sesión compartida como fragilidad latente).

---

## D15 — Datetimes con timezone: rechazados, no convertidos

**Problema:** los docstrings de las tools piden ISO 8601; si el modelo agrega una `Z` o un
offset (o el usuario pega un timestamp con offset y el modelo lo copia), pydantic parsea un
datetime aware. Compararlo con el reloj naive del sistema tiraba un `TypeError` (que no es
`BookingError`, escapaba del agente y terminaba en 502), y en las queries SQL el offset se
ignoraba en silencio (SQLite compara strings).

**Decisión:** todo el dominio es hora local naive (America/Montevideo, D10); un datetime
aware se rechaza en `service.py` (la fuente de verdad) como `BookingError` con un mensaje
accionable, que el agente relata y corrige reenviando la hora local. Los docstrings de las
tools y el system prompt piden explícitamente "sin offset ni 'Z'" para que el caso pase lo
menos posible.

**Alternativas descartadas:** convertir a Montevideo (`astimezone`): cuando el modelo agrega
una `Z` por hábito (el caso típico), "10:00Z" se convertiría en 07:00 y la reserva quedaría
a la hora equivocada sin que nadie lo note; strip directo de `tzinfo` (acierta en el caso
típico pero miente cuando el offset era intencional, y lo hace en silencio).

---

## D16 — Backoffice: link público sin login que ve y cancela cualquier reserva

**Problema:** necesitaba una forma de verificar de un vistazo que las reservas se guardan
bien (qué sala, quién, cuándo) y de corregirlas (cancelar) sin pasar por el chat. El chat
está atado a un usuario y sus reglas (`cancel_booking` solo cancela lo propio), así que no
me servía como vista de operador.

**Decisión:** una página estática nueva (`/backoffice`) con vista semanal por sala, servida
por el mismo FastAPI y sin autenticación (se accede por link, decisión de producto para el
alcance del challenge). Se apoya en tres endpoints públicos (`/backoffice/api/rooms`,
`/backoffice/api/bookings`, `DELETE /backoffice/api/bookings/{id}`) y en dos helpers de
servicio nuevos: `list_bookings_in_range` (reservas de todos los usuarios en un rango) y
`admin_cancel_booking` (cancela cualquier reserva, sin el chequeo de propiedad). Los dos
viven en `service.py`, junto a las reglas que saltean a propósito, para que la historia de
"quién puede qué" quede en un solo lugar. El frontend es vanilla JS/CSS (sin build ni
librería de calendario), como el resto de la UI: pide la semana entera una vez y filtra por
sala del lado del cliente, así cambiar de sala es instantáneo.

**Riesgo asumido:** al estar deployado en una URL pública, cualquiera que la descubra puede
cancelar reservas. Es aceptable para una demo evaluable; en un entorno real lo protegería
con login o una red interna (ver "Mejoras futuras" en el overview).

**Alternativas descartadas:** meter la vista dentro del chat autenticado (mezcla el rol de
usuario final con el de operador, y arrastra las reglas de propiedad que acá no quiero); una
librería de calendario (FullCalendar y afines) traería un build y dependencias externas que
rompen la simplicidad de "un archivo estático, sin CDN" del resto del proyecto.
