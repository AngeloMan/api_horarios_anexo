# ---------------------------------------------------------------------------
# Dockerfile Multi-stage: Build do fet-cl 7.8.5 + Runtime Python para API & Worker
# ---------------------------------------------------------------------------

# ---- Stage 1: Build do motor FET (fet-cl) --------------------------------
FROM ubuntu:24.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential qtbase5-dev qt5-qmake \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 https://github.com/bhavyasaggi/fet.git .

WORKDIR /src/src
RUN qmake src-cl.pro && make -j"$(nproc)" && strip ../fet-cl

# ---- Stage 2: Runtime Compartilhado (FastAPI + Celery Worker) ------------
FROM ubuntu:24.04 AS runtime

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libqt5core5t64 \
    python3 \
    python3-pip \
    python3-venv \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar binário fet-cl do stage de build
COPY --from=build /src/fet-cl /usr/local/bin/fet-cl
RUN chmod +x /usr/local/bin/fet-cl

WORKDIR /app

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copiar o código da aplicação
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]