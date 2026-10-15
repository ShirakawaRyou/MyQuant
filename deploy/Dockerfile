FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
COPY research/protocol.json ./research/protocol.json
COPY services/dashboard ./services/dashboard
WORKDIR /app/services/dashboard
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/proxy_ca > /tmp/build-ca.pem; \
      export SSL_CERT_FILE=/tmp/build-ca.pem UV_SYSTEM_CERTS=true; \
    fi; \
    chmod 755 /app/research && chmod 644 /app/research/protocol.json && \
    uv sync --frozen --no-dev --no-editable && \
    groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home app && \
    mkdir -p /app/runtime/trading /app/runtime/auth && chown -R app:app /app/runtime && \
    rm -f /tmp/build-ca.pem
ENV PATH="/app/services/dashboard/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MYQUANT_RUNTIME=/app/runtime RESEARCH_PROTOCOL=/app/research/protocol.json
USER 10001:10001
CMD ["myquant-web", "--host", "0.0.0.0", "--port", "8090"]
