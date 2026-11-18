# kinda-frame renderer: art/photo modes (numpy, Pillow) and dashboard boards (Chromium via Playwright).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core libatomic1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY kindaframe ./kindaframe
RUN pip install . \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache

RUN useradd --system --uid 10001 --no-create-home kf \
 && mkdir -p /state /photos \
 && chown kf /state

USER kf
# HOME/TMPDIR on the tmpfs: the root filesystem is read-only, Chromium needs a scratch profile dir.
ENV KF_CONFIG=/app/config.toml \
    KF_STATE=/state \
    HOME=/tmp \
    TMPDIR=/tmp
EXPOSE 8787

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u, sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8787/healthz', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "--factory", "kindaframe.app:create_app", "--host", "0.0.0.0", "--port", "8787", "--no-server-header"]
