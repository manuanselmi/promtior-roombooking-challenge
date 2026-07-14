# syntax=docker/dockerfile:1

# RoomBooking — imagen de producción (D5: un contenedor, un proceso).
# Base oficial de Astral: trae uv + Python 3.12 sobre Debian slim, sin instalar uv a mano.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# uv: compilar a bytecode (arranque más rápido) y copiar en vez de symlinkear
# (symlinks rompen cuando el cache y el venv viven en capas distintas).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 1) Solo dependencias, en su propia capa: no se invalida al tocar el código de la app.
#    lock + pyproject se montan (no se copian) y --no-dev deja fuera pytest/ruff/httpx.
#    El proyecto no es un paquete instalable (sin [build-system]): --no-install-project.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# 2) El código: la app se corre desde el fuente, no se empaqueta.
COPY app ./app

# El venv de uv al frente del PATH → uvicorn/python salen del entorno del proyecto.
ENV PATH="/app/.venv/bin:$PATH"

# Usuario no-root con UID/GID 1000 (coincide con el usuario default de Ubuntu en la
# instancia Lightsail, así un bind mount del host queda con permisos correctos).
# /app/data se crea con este dueño: un named volume montado ahí hereda estos permisos,
# y SQLite (data/roombooking.db) puede escribir sin ajustes extra.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --no-create-home app \
    && mkdir -p /app/data \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Chequeo de salud contra /health, usando el python de la imagen (sin sumar curl).
# start-period cubre el import de langchain en el arranque.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# exec → uvicorn es PID 1 y recibe SIGTERM directo (docker stop apaga limpio, sin esperar 10s).
# El puerto sale de env para overridear sin reconstruir; default 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
