# syntax=docker/dockerfile:1
# ============================================================================
# LSE Terminal - web deployment image.
#
# The desktop builds (desktop/build-mac.sh, desktop/build-win.ps1) freeze the
# same engine into a PyInstaller sidecar for Mac and Windows. This image is
# that engine on a public host, and three decisions shape it:
#
# 1. HOSTED MODE IS THE SECURITY BOUNDARY, NOT A PREFERENCE.
#    LSE_TERMINAL_HOSTED=1 selects the app's own public-embed policy
#    (engine/server.py): the endpoints that write to the host machine or
#    execute user Python - backtests, the workspace IDE, the PTY sockets,
#    broker connections, pip installs - answer 403, because this process is
#    shared by every visitor instead of owned by one user. It is set in the
#    image ENV *and* in render.yaml so neither can drift away from the other.
#
# 2. NO NODE TOOLCHAIN HERE.
#    frontend/ needs Node at DEVELOPMENT time only. The compiled chart bundle
#    is committed at lse_terminal/ui/static/chart/chart.js and ships inside
#    the wheel, so this image stays a single Python layer.
#
# 3. NO COMPILER HERE EITHER.
#    Every dependency (pandas, numpy, pyarrow, orjson) publishes manylinux
#    wheels; installing from source in a slim image would need build-essential
#    and a much larger image for no benefit.
# ============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LSE_TERMINAL_HOSTED=1

WORKDIR /app

# curl is for the container healthcheck below; the app itself needs nothing
# from the OS beyond the Python stdlib and its wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Metadata first, package second: the dependency layer then caches across
# edits to the Python source, which is most of a redeploy's build time.
COPY pyproject.toml README.md LICENSE ./
COPY lse_terminal ./lse_terminal
RUN pip install .

# Never root. The engine writes its config, workspace and identity cache
# under $HOME (engine/config.py), so that tree belongs to the unprivileged
# user rather than being root-owned and unwritable at runtime.
RUN useradd --create-home --uid 10001 lse \
 && mkdir -p /home/lse/.config/lse-terminal \
 && chown -R lse:lse /home/lse
USER lse
ENV HOME=/home/lse

# Render injects $PORT and routes to it; 10000 is its convention, kept as the
# fallback so the image also runs standalone with `docker run -p 10000:10000`.
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-10000}/api/health" || exit 1

# sh -c so ${PORT} is expanded when the container STARTS. `PORT=x lset --port
# $PORT` would expand before the assignment and pass an empty string, which
# argparse rejects - a real trap, hit and fixed while testing this image.
CMD ["sh", "-c", "exec lset --no-browser --host 0.0.0.0 --port ${PORT:-10000}"]
