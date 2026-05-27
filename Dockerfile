# YouTube Analyst — Node 20 server (serve.mjs) that spawns the Python pipeline.
# Single image carries both runtimes.
FROM node:20-bookworm-slim

# System Python + venv tooling
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps into an isolated venv (avoids Debian's externally-managed pip).
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# serve.mjs reads process.env.PYTHON to choose the interpreter.
ENV PYTHON=/opt/venv/bin/python

# App source (serve.mjs has no npm deps — built-ins only, so no npm install needed).
COPY . .

# Render injects $PORT at runtime; serve.mjs binds to it (falls back to 5173 locally).
EXPOSE 10000
CMD ["node", "serve.mjs"]
