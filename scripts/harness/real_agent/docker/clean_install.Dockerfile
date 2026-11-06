FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg nodejs && rm -rf /var/lib/apt/lists/*
WORKDIR /validation
COPY dist-runtime-exit/*.whl /wheels/
RUN pip install --no-cache-dir /wheels/*.whl 'mcp==2.2.0' 'pytest==9.0.2'
COPY tests tests
COPY scripts/harness scripts/harness
COPY web/dist web/dist
ENV PYTHONPATH=/validation/tests PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "server", "--stories-directory", "/tmp/stories"]
