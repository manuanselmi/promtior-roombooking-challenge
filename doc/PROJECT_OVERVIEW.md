# Project Overview: RoomBooking

Asistente conversacional para reservar salas de reunión en la oficina de Cubo Itaú. El
usuario escribe en lenguaje natural (por ejemplo "reservá la sala B mañana a las 10 para
3 personas, reunión de equipo") y el sistema crea, consulta o cancela reservas según las
reglas del enunciado.

Stack: FastAPI, LangChain (`create_agent` sobre LangGraph), SQLite y la API de OpenAI
(`gpt-4o` por defecto, configurable por variable de entorno). Todo corre en un
único proceso que sirve la interfaz web, la API y el agente.

- **Demo:** https://promtior.manuanselmi.com (usuarios `User1` / `User2`, contraseña
  `TechnicalChallengePromtior`).
- **Repositorio:** https://github.com/manuanselmi/promtior-roombooking-challenge

## El proceso que seguí

Antes de escribir código hice dos cosas: pensar la arquitectura a nivel general y decidir
cómo lo iba a desplegar. Recién después empecé con las decisiones técnicas, y las tomé
todas antes de ponerme a programar. Cada una quedó registrada en
[`DECISIONS.md`](DECISIONS.md) con su justificación y las alternativas que descarté.

Fue un ida y vuelta. La idea que quedó como columna vertebral es que el LLM se limita a
llamar herramientas, y las reglas de negocio las define y las hace cumplir el código que
está detrás de esas herramientas, no el modelo ni el prompt. El prompt puede enumerar las
reglas para ahorrar idas y vueltas, pero si se borra entero, ninguna regla se puede
violar.

## Arquitectura

La solución está organizada en capas, cada una con una responsabilidad:

| Capa | Archivo | Responsabilidad |
|------|---------|-----------------|
| Modelo de datos | `app/booking/models.py` | Tablas User, Room, Booking |
| Reglas de negocio | `app/booking/service.py` | Única fuente de verdad de las reglas |
| Herramientas del LLM | `app/agent/tools.py` | Wrappers finos que traducen del LLM al service |
| Ensamblado del agente | `app/agent/agent.py` | Prompt, middleware y memoria de conversación |
| Autenticación | `app/auth.py` | Login con JWT y hashing con bcrypt |
| Capa HTTP | `app/main.py` | Endpoints de login, chat y la página estática |

Una reserva se modela como un único rango contiguo `[start, end)` alineado a slots de 30
minutos. Combinar slots no contiguos es imposible por diseño, así que no hay que validar
algo que no se puede escribir.

El agente se arma por request con `create_agent`, la API actual de LangChain 1.x que
compila un grafo de LangGraph. En cada mensaje decide si responde o si llama a una de las
cinco herramientas: crear una reserva, listar salas libres, ver la agenda de una sala,
listar las reservas propias y cancelar. Las herramientas no razonan: delegan en el
service, que valida todo y toca la base.

Además del chat hay un backoffice simple en `/backoffice`: una vista de operador que
lista todas las reservas en un calendario semanal por sala y permite cancelar cualquiera.
Es deliberadamente sin login y sus endpoints son públicos, se entra por link. Lo sumé
para verificar durante la demo que las reservas quedan bien guardadas y poder
corregirlas, no como una consola con control de acceso; esa decisión, con su límite de
seguridad, queda documentada en D16.

El detalle de cada componente y el flujo completo de un mensaje están en
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Los desafíos principales

**1. La identidad del usuario.** Había que garantizar que las operaciones se hicieran
siempre sobre el usuario correcto, sin que el chat pudiera suplantarlo (por ejemplo con
un "cancelá la reserva 3" ajena o un "reservá a nombre de User2"). La identidad no es un
parámetro de ninguna herramienta: las tools se construyen dentro de una función que ya
recibió al usuario autenticado del JWT y lo capturan por closure, así que el LLM no tiene
forma de pasar otro usuario. Además el service vuelve a verificar la propiedad antes de
cancelar.

**2. El LLM no tiene reloj.** Sin la fecha actual, un pedido como "mañana a las 10" es
irresoluble y el bot reservaría en el pasado. La fecha y hora actual se inyectan en el
system prompt en cada request, así siempre están frescas.

**3. La doble reserva.** FastAPI atiende los endpoints sync desde un threadpool, así que
dos requests simultáneos podían intercalarse entre el chequeo de solapamiento y el INSERT,
y crear dos reservas solapadas sin que ninguno viera el conflicto. Lo resolví con un lock
de proceso alrededor de la sección crítica (chequeo más insert), verificado con un test
donde 10 threads sincronizados por una barrera intentan la misma reserva y exactamente
uno gana.

Ya con el sistema andando, probando aparecieron dos bugs de robustez que cerré y
documenté. Las tool calls en paralelo de un mismo turno compartían una sesión de
SQLAlchemy, que no es thread-safe; ahora cada invocación de tool abre su propia sesión
(D14). Y un datetime con timezone que a veces mandaba el modelo rompía la comparación con
el reloj naive del sistema; ahora se rechaza con un mensaje accionable que el agente
corrige (D15).

## Deploy

Un único contenedor Docker en una instancia de AWS Lightsail, con la base SQLite en un
volumen persistente. Adelante, un reverse proxy Caddy termina TLS y gestiona el
certificado de Let's Encrypt de forma automática, sirviendo la app por HTTPS en un
subdominio propio. El mismo `Dockerfile` corre local y en la nube. El porqué de Lightsail
en lugar de Lambda o Fargate está en la decisión D5.

## Testing

82 tests que cubren cada capa determinista sin gastar una llamada al LLM: las reglas de
negocio del service (con base en memoria y un `now` inyectado), las tools directo (strings
de rechazo y binding de identidad), los contratos HTTP (login, 401, sesión por token) y
los endpoints del backoffice. El LLM es no determinista, así que no se testea con asserts;
se prueba manualmente.

## Cómo correr el proyecto

Local con uv:

```bash
uv sync
echo "OPENAI_API_KEY=sk-..." > .env
uv run uvicorn app.main:app --reload
```

Con Docker:

```bash
docker build -t roombooking .
docker run -d -p 8000:8000 -v roombooking-data:/app/data \
  -e OPENAI_API_KEY=sk-... roombooking
```

En ambos casos la app queda en `http://localhost:8000`, con `User1` y `User2` ya
sembrados.
