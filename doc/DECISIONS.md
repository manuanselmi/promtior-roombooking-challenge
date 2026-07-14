# Decisiones de diseño — Challenge RoomBooking (Promtior)

Log cronológico de decisiones tomadas, con su justificación. Sirve como base para el
*Project Overview* del entregable final.

---

## D1 — Orquestación del agente: LangChain

**Decisión:** usar LangChain para orquestar el agente con tool-calling.

**Por qué:**
- El challenge sugiere LangChain de forma explícita y repetida; alinearse con la herramienta
  que Promtior usa demuestra adaptabilidad.
- Lo que se evalúa es la arquitectura agéntica y el tool-calling limpio, no la librería en sí,
  pero usar su stack recomendado es señal positiva en un challenge de evaluación.
- Cubre el único gap del candidato (experiencia previa en orquestación in-house, no LangChain).

**Alternativa descartada:** tool-calling nativo del proveedor (OpenAI/Groq function calling)
in-house. Más control y transparencia, pero no demuestra LangChain, que es lo que piden.

---

## D2 — LLM: OpenAI, default `gpt-4o`, configurable por env var

**Decisión:** usar la API de OpenAI con `gpt-4o` como modelo default, seleccionable vía
variable de entorno (`OPENAI_MODEL`).

**Por qué:**
- El PDF recomienda explícitamente OpenAI API si se tiene suscripción — el candidato tiene
  crédito disponible.
- El default arrancó en `gpt-4o-mini` (barato, suficiente para tool-calling estructurado),
  pero se subió a `gpt-4o` tras verificar que 4o-mini no respeta de forma confiable la
  instrucción de "pedir los datos faltantes, nunca asumir la duración ni inventar el
  título": reservaba slots de 30 minutos en silencio aunque el prompt, el docstring de la
  tool y un ejemplo few-shot se lo prohibían. `gpt-4o` sí obedece. Los requests son chicos
  (system prompt corto + mensajes breves), así que el costo por conversación es marginal.
- Configurable por env var: permite bajar a un modelo más barato o subir a uno más capaz
  sin tocar código.

**Alternativas descartadas:** seguir en `gpt-4o-mini` (más barato, pero incumple el
requisito de preguntar en vez de asumir); Groq/Ollama/OpenRouter (opciones que da el PDF
para quienes no tienen suscripción — no aplica).

---

## D3 — Sin backoffice en el MVP

**Decisión:** no construir backoffice/panel de administración; queda como extensión futura.

**Por qué:**
- No está en los requerimientos del challenge; lo evaluado es el chatbot con tool-calling,
  las reglas de negocio y la documentación.
- Prioridad: MVP que cumpla el 100% de lo pedido dentro de los 7 días de validez.
- Si sobra tiempo, se listará como "future work" en el Project Overview.

---

## D4 — Persistencia: SQLite + SQLAlchemy

**Decisión:** SQLite como base de datos, accedida vía SQLAlchemy.

**Por qué:**
- El dominio es inherentemente relacional y transaccional: la regla central (no solapamiento)
  es una range query (`WHERE room = ? AND start < :end AND end > :start`) y la doble reserva
  se previene con transacción + constraint — exactamente lo que un motor relacional resuelve.
- Alcance real: 2 usuarios, 5 salas, demo de días. Cero infra, cero costo.
- SQLAlchemy desacopla el motor: migrar a Postgres es cambiar la connection string.

**Alternativas descartadas:**
- **NoSQL (DynamoDB/Mongo):** modelar el no-solapamiento requiere writes condicionales por
  slot o filtrado en aplicación, y una reserva de 3 h implica transacciones sobre 6 items.
  Más código para el mismo resultado; las ventajas de NoSQL (esquema flexible, escala
  horizontal) no aplican a este dominio.
- **In-memory:** se pierde al reiniciar; inaceptable para una demo pública evaluada.

---

## D5 — Deploy: Docker en AWS Lightsail (o EC2)

**Decisión:** un único contenedor Docker corriendo en una instancia Lightsail (~5 USD/mes,
precio fijo, IP y disco persistente incluidos). EC2 t3.micro es equivalente si aplica free tier.

**Por qué:**
- Disco persistente → compatible con SQLite (D4).
- Paridad dev/prod total: el mismo Dockerfile corre local y en cloud, y es parte del entregable.
- Always-warm: sin cold starts en la primera impresión del evaluador.
- Demuestra AWS (experiencia del candidato) cumpliendo "deploy on a cloud of your choice".

**Alternativas descartadas:**
- **Lambda + API Gateway:** cold starts en un chat, packaging pesado de LangChain, y
  empuja a DynamoDB o a Aurora/RDS Proxy (4-5 piezas de infra para 2 usuarios).
- **Fargate/App Runner:** storage efímero (mata SQLite) y más caro que Lightsail para
  un servicio always-on chico (~9 USD/mes la task mínima).
- **Railway (tip del PDF):** válido y rápido, pero no demuestra AWS.

---

## D6 — Auth: login form + JWT, fuera del chat

**Decisión:** login clásico (form → `POST /login` → JWT firmado) antes de entrar al chat.
Cada request al chat lleva el token; el backend resuelve la identidad y las tools operan
en nombre del usuario autenticado. Passwords hasheados (bcrypt) aunque sea una demo.

**Por qué:**
- **El LLM nunca ve credenciales.** Un login "conversacional" haría viajar el password por
  el historial del chat hacia la API de OpenAI y los logs — mala práctica de seguridad.
- La identidad llega al agente como contexto ya validado, no como texto del usuario:
  imposible suplantar a otro usuario prompteando al bot.
- JWT es estándar, stateless y simple de implementar en FastAPI.

**Alternativas descartadas:** login conversacional vía tool (password expuesto al LLM);
HTTP Basic (sin logout ni sesión, luce a atajo).

---

## D7 — UI: página HTML/JS propia servida por FastAPI

**Decisión:** una única página estática (login + chat, JS vanilla) servida por el mismo
backend FastAPI. Un solo contenedor, un solo proceso.

**Por qué:**
- Arquitectura transparente para el evaluador: se ve todo el flujo (login → token → chat →
  agente → tools → DB) sin capas mágicas.
- Control total del flujo de auth (D6), que es donde está la señal de seniority.
- Un solo artefacto deployable (D5): sin CORS, sin build de frontend, sin servicio extra.

**Alternativas descartadas:** Chainlit (rápido y con auth built-in, pero dependencia
opinionada que oculta el plumbing que queremos mostrar); Streamlit/Gradio (auth y patrón
chat incómodos).

---

## D8 — Agente: `create_agent` de LangChain 1.x (sobre LangGraph)

**Decisión:** construir el agente con `create_agent`, la API estándar de LangChain 1.x,
que corre sobre LangGraph.

**Por qué:**
- Es el camino recomendado y actual de LangChain: loop ReAct resuelto, tool-calling
  nativo, y checkpointing para memoria de conversación incluido.
- `AgentExecutor` (legacy) está deprecado — usarlo sería señal negativa.
- Un loop manual con `.bind_tools()` daría más control pero reinventa lo que la librería
  ya resuelve, y el challenge premia demostrar LangChain idiomático.

---

## D9 — Tooling: uv + pyproject.toml, Python 3.12

**Decisión:** gestionar dependencias con `uv` y `pyproject.toml` (lockfile incluido).

**Por qué:** rápido, determinista, estándar moderno; simplifica el Dockerfile (D5).
Se descartan pip/requirements.txt (sin lock real) y Poetry (más pesado, sin ventaja hoy).

---

## D10 — Defaults de dominio (lo que el PDF no especifica)

**Decisión:** donde el enunciado deja libertad, definimos defaults simples y los documentamos:

| Aspecto | Default elegido | Razón |
|---|---|---|
| Capacidades | A:2, B:4, C:6, D:8, E:10 | El PDF exige capacidad máxima por sala pero no da valores; escalera fácil de recordar y testear. |
| Horario de oficina | Sin restricción (24/7) | El PDF no lo pide; no inventar reglas = menos edge cases. Extensión futura. |
| Timezone | America/Montevideo, única | Cubo Itaú está en Montevideo; multi-TZ fuera de alcance. |
| Idioma del bot | Responde en el idioma del usuario (ES/EN) | El LLM lo maneja sin lógica extra. |

---

## D11 — Guardrails del agente: limitar al LLM en todo lo posible

**Principio:** el agente propone, el código dispone. El LLM solo elige qué tool llamar;
ninguna regla de negocio ni dato sensible depende de él.

**Decisiones concretas:**

1. **Identidad inyectada, no parametrizada.** Las tools se construyen por request con
   closures sobre el usuario autenticado (del JWT). `user_id` no es parámetro de ninguna
   tool → el LLM no puede reservar ni cancelar en nombre de otro, diga lo que diga el chat.
2. **Errores como datos, no excepciones.** Las violaciones de reglas vuelven como strings
   (`BOOKING REJECTED: ...`); el agente solo puede relatarlas y ofrecer alternativas.
3. **Fecha/hora actual inyectada en el system prompt** por request — sin eso el LLM no
   puede resolver "mañana a las 10" (su reloj interno no existe).
4. **Memoria por sesión de login:** checkpointer `InMemorySaver` de LangGraph, un
   `thread_id` por sesión. Volátil a propósito: un restart desloguea a todos igualmente.
5. **Ventana de contexto acotada:** `SummarizationMiddleware` (built-in de LangChain 1.x)
   comprime turnos viejos al superar ~3000 tokens. Motivo principal: techo de costo en un
   deploy público con crédito propio (cada turno re-envía el historial completo), no el
   límite de 128k. Se eligió sobre trimming custom (la lib ya lo resuelve sin partir pares
   tool-call/tool-result) y sobre "no hacer nada" (costo sin techo).
6. **Techo de iteraciones:** `ModelCallLimitMiddleware` con máx. 10 llamadas al modelo por
   mensaje de usuario — corta loops descontrolados (y su costo).
7. **`temperature=0`:** tool-calling estructurado, no creatividad.

---

## D12 — API de chat: `POST /chat` síncrono, sesión de chat = `jti` del JWT

**Decisiones concretas:**

1. **`thread_id` = claim `jti` del JWT.** Cada login genera un session-id aleatorio que
   LangGraph usa como clave de la conversación → login nuevo = conversación nueva, sin
   estado extra en el servidor (el JWT ya viaja en cada request). Coherente con la
   memoria volátil de D11.
2. **Respuesta bloqueante, sin streaming.** Con respuestas cortas la latencia percibida
   no justifica SSE/WebSockets en el MVP. La UI muestra un indicador de "escribiendo".
   Streaming queda listado como mejora futura.
3. **Token JWT solo en memoria del navegador** (variable JS, no `localStorage`): un
   refresh implica re-login. Menos superficie ante XSS y consistente con que la memoria
   de conversación del servidor también es volátil.
4. **Errores del agente → HTTP 502 genérico.** Si OpenAI falla, el detalle queda en el
   log del servidor; el cliente recibe un mensaje neutro (no se filtran internals).

---

## D13 — Carrera de doble reserva: cerrada con lock de proceso

**Problema:** FastAPI atiende endpoints sync desde un threadpool, así que dos requests
simultáneos podían intercalarse entre el chequeo de solapamiento y el INSERT
(check-then-insert no atómico) y crear dos reservas solapadas sin que ningún request
"viera" el conflicto.

**Decisión:** un `threading.Lock` a nivel de proceso alrededor de la sección
chequeo-de-conflictos + insert en `service.create_booking`. Verificado con un test de
concurrencia real: 10 threads sincronizados con una barrera intentan la misma reserva y
exactamente uno gana.

**Por qué alcanza:** el deploy es un único proceso (un contenedor, D5) — no existe
concurrencia fuera de ese proceso, por lo que el lock cubre el 100% de los casos reales.

**Límite conocido:** con múltiples procesos/réplicas el lock dejaría de alcanzar; el
camino correcto ahí es una garantía a nivel de base de datos (exclusion constraint de
Postgres sobre `(room_id, tsrange(start, end))`), que rechaza el segundo insert aunque
la aplicación tenga la carrera.

**Alternativas descartadas:** `BEGIN IMMEDIATE` (acopla el service al dialecto SQLite);
dejarlo documentado sin cerrar (defendible, pero cerrarlo costó tres líneas y un test).

---

## D14 — Una sesión de DB por invocación de tool

**Problema:** el `ToolNode` de LangChain ejecuta las tool calls de un mismo turno del
modelo **en threads paralelos** (`executor.map`), y el modelo de OpenAI emite tool calls
paralelas por defecto ("reservá la sala B y la C" → dos calls simultáneas). Las tools
compartían la `Session` de SQLAlchemy del request — que no es thread-safe — vía closure.
Reproducido: 24 de 40 iteraciones fallaban, mitad con `sqlite3.InterfaceError` (→ 502),
mitad con resultados silenciosamente falsos ("Room 'C' does not exist") que el agente
relataba como ciertos.

**Decisión:** `build_tools` recibe un session factory (`Callable[[], Session]`) en lugar
de una sesión; cada invocación de tool abre y cierra su propia sesión. La identidad se
captura como valores planos (`user.id`, `user.username`) porque la instancia ORM
pertenece a la sesión del request, que no debe tocarse desde los threads de las tools.
Verificado con un test que ejecuta creates y lecturas concurrentes en threads (el mismo
patrón de ejecución que `ToolNode`).

**Alternativas descartadas:** `parallel_tool_calls=False` en el modelo (no ataca la causa
raíz, pierde paralelismo legítimo y depende de un flag del proveedor); un lock por request
serializando las tools (parche que mantiene la sesión compartida como fragilidad latente).

---

## D15 — Datetimes con timezone: rechazados, no convertidos

**Problema:** los docstrings de las tools piden ISO 8601; si el modelo agrega `Z` o un
offset (o el usuario pega un timestamp con offset y el modelo lo copia), pydantic parsea
un datetime *aware*. Compararlo con el reloj naive del sistema tiraba `TypeError` — que
no es `BookingError`, escapaba del agente y terminaba en 502 — y en las queries SQL el
offset se ignoraba silenciosamente (SQLite compara strings).

**Decisión:** todo el dominio es hora local naive (America/Montevideo, D10); un datetime
aware se rechaza en `service.py` (la fuente de verdad) como `BookingError` con mensaje
accionable, que el agente relata y corrige reenviando la hora local. Los docstrings de
las tools y el system prompt piden explícitamente "sin offset ni 'Z'" para minimizar la
frecuencia del caso.

**Alternativas descartadas:** convertir a Montevideo (`astimezone`): cuando el modelo
agrega `Z` por hábito — el caso típico — "10:00Z" se convertiría en 07:00 y la reserva
quedaría a la hora equivocada sin que nadie lo note; strip directo de `tzinfo` (acierta
en el caso típico pero miente cuando el offset era intencional, y lo hace en silencio).

---

## D16 — Backoffice: link público sin login que ve y cancela cualquier reserva

**Problema:** hacía falta una forma de verificar de un vistazo que las reservas se guardan
bien (qué sala, quién, cuándo) y de corregirlas (cancelar) sin pasar por el chat. El chat
está atado a un usuario y sus reglas (`cancel_booking` solo cancela lo propio), así que no
sirve como vista de operador.

**Decisión:** una página estática nueva (`/backoffice`) con vista semanal por sala, servida
por el mismo FastAPI y sin autenticación (se accede por link, decisión de producto para el
alcance del challenge). Se apoya en tres endpoints públicos (`/backoffice/api/rooms`,
`/backoffice/api/bookings`, `DELETE /backoffice/api/bookings/{id}`) y en dos helpers de
servicio nuevos: `list_bookings_in_range` (reservas de todos los usuarios en un rango) y
`admin_cancel_booking` (cancela cualquier reserva, sin el chequeo de propiedad). Ambos viven
en `service.py`, junto a las reglas que saltean a propósito, para que la historia de "quién
puede qué" quede en un solo lugar. El frontend es vanilla JS/CSS (sin build ni librerías de
calendario), como el resto de la UI: pide la semana entera una vez y filtra por sala del lado
del cliente, así cambiar de sala es instantáneo.

**Riesgo asumido:** al estar deployado en una URL pública, cualquiera que la descubra puede
cancelar reservas. Aceptable para una demo evaluable; en un entorno real se protegería con
login o una red interna (ver "Mejoras futuras").

**Alternativas descartadas:** meter la vista dentro del chat autenticado (mezcla el rol de
usuario final con el de operador, y arrastra las reglas de propiedad que acá no queremos);
una librería de calendario (FullCalendar y afines) traería un build y dependencias externas
que rompen la simplicidad de "un archivo estático, sin CDN" del resto del proyecto.
