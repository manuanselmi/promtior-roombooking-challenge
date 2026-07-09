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

## D2 — LLM: OpenAI, default `gpt-4o-mini`, configurable por env var

**Decisión:** usar la API de OpenAI con `gpt-4o-mini` como modelo default, seleccionable
vía variable de entorno (`OPENAI_MODEL` o similar).

**Por qué:**
- El PDF recomienda explícitamente OpenAI API si se tiene suscripción — el candidato tiene
  crédito disponible.
- El deploy es público y consume crédito propio: `gpt-4o-mini` es barato y suficiente para
  tool-calling estructurado en un dominio acotado como este.
- Configurable por env var: permite subir a un modelo más capaz para la demo/evaluación
  sin tocar código.

**Alternativas descartadas:** Groq/Ollama/OpenRouter (opciones que da el PDF para quienes
no tienen suscripción — no aplica); modelos más caros como default (costo innecesario).

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
2. **Respuesta bloqueante, sin streaming.** Con `gpt-4o-mini` y respuestas cortas, la
   latencia percibida no justifica SSE/WebSockets en el MVP. La UI muestra un indicador
   de "escribiendo". Streaming queda listado como mejora futura.
3. **Token JWT solo en memoria del navegador** (variable JS, no `localStorage`): un
   refresh implica re-login. Menos superficie ante XSS y consistente con que la memoria
   de conversación del servidor también es volátil.
4. **Errores del agente → HTTP 502 genérico.** Si OpenAI falla, el detalle queda en el
   log del servidor; el cliente recibe un mensaje neutro (no se filtran internals).
