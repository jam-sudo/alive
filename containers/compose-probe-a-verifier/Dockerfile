# syntax=docker/dockerfile:1.7

# Both build inputs are mandatory platform-specific digest references.  Tags are
# intentionally absent; the owner build policy must reject non-@sha256 values.
ARG UV_IMAGE
FROM ${UV_IMAGE} AS uv_binary

ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE}

COPY --from=uv_binary /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONHASHSEED=0

WORKDIR /opt/alive
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN mkdir -p scripts/compose scripts/baselines
COPY scripts/compose/verify_gears_probe_a.py scripts/compose/gears_decision_probe.py ./scripts/compose/
COPY scripts/baselines/gears_worker.py ./scripts/baselines/

# uv.lock authenticates every downloaded wheel/sdist.  The project remains an
# editable source install so the bootstrap can require /opt/alive/src/alive as
# the maintained origin; the final OCI manifest digest covers the .pth startup
# files, interpreter, stdlib, native libraries, and every installed dependency.
RUN uv sync --frozen --no-install-package alive && \
    uv sync --frozen

ARG ALIVE_GIT_COMMIT
LABEL org.opencontainers.image.title="ALIVE COMPOSE Probe-A verifier" \
      org.opencontainers.image.revision="${ALIVE_GIT_COMMIT}"
RUN printf '%s\n' "$ALIVE_GIT_COMMIT" | grep -Eq '^([0-9a-f]{40}|[0-9a-f]{64})$' && \
    printf '%s\n' "$ALIVE_GIT_COMMIT" > /opt/alive/.alive-verifier-git-commit

RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin verifier
USER 65532:65532

ENTRYPOINT ["/opt/alive/.venv/bin/python", "-B", "-I", "/opt/alive/scripts/compose/verify_gears_probe_a.py"]
