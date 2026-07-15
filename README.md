# RoomBooking: challenge técnico de Promtior

Chatbot con tool-calling que permite reservar salas de reunión de la oficina de
Cubo Itaú a través de una interfaz conversacional. El LLM solo elige qué
herramienta llamar; las reglas de negocio (slots de 30 min, máximo 3 horas, sin
solapamientos, capacidad por sala, cancelar solo lo propio) las hace cumplir el
código detrás de las tools, nunca el modelo ni el prompt.

Stack: FastAPI, LangChain (`create_agent` sobre LangGraph), SQLite y la API de
OpenAI (`gpt-4o` por defecto).

## Demo en vivo

- **URL:** https://promtior.manuanselmi.com
- **Usuarios:** `User1` / `User2`
- **Contraseña:** `TechnicalChallengePromtior`

## Documentación (`/doc`)

- **[Project Overview](doc/PROJECT_OVERVIEW.md):** cómo encaré y resolví el
  challenge, la arquitectura, los desafíos técnicos y cómo los superé.
- **[Diagrama de componentes](doc/component-diagram.png):** los componentes y sus
  interacciones desde que llega el mensaje hasta que se devuelve la respuesta
  ([versión interactiva](doc/component-diagram.html)).
- **[Notebook técnico](doc/notebook.ipynb):** las tecnologías con ejemplos de
  código ejecutables aplicados a esta solución.
- **[Log de decisiones](doc/DECISIONS.md):** cada decisión de diseño (D1 a D16)
  con su justificación y las alternativas descartadas.

## Cómo correr

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

La app queda en `http://localhost:8000`, con `User1` y `User2` ya sembrados.

## Tests

```bash
uv run pytest
```
