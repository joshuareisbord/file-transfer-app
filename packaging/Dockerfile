FROM ubuntu:latest AS builder

ARG DEBIAN_FRONTEND=noninteractive
ENV PATH="/opt/uv-bootstrap/bin:/root/.local/bin:$PATH"

RUN apt-get update
RUN apt-get install --yes --no-install-recommends \
    binutils \
    openssh-client \
    openssh-server \
    patchelf \
    python3 \
    python3-dev \
    python3-pip \
    python3-tk \
    python3-venv \
    xauth \
    xvfb

RUN python3 -m venv /opt/uv-bootstrap
RUN /opt/uv-bootstrap/bin/pip install uv

WORKDIR /source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY work_transfer_app ./work_transfer_app
COPY tests ./tests
COPY packaging/e2e ./packaging/e2e
COPY packaging/smoke-test.sh ./packaging/smoke-test.sh

RUN uv sync --frozen
RUN uv run pytest -q
RUN xvfb-run --auto-servernum uv run pytest -q tests/test_ui_shell.py
RUN PYTHONPATH=/source uv run python packaging/e2e/scp_loopback.py
RUN uv run pyinstaller \
    --clean \
    --noconfirm \
    --onefile \
    --name work-transfer \
    --collect-data work_transfer_app \
    --distpath /output \
    --workpath /tmp/work-transfer-build \
    --specpath /tmp \
    work_transfer_app/__main__.py
RUN /output/work-transfer --self-check
RUN ./packaging/smoke-test.sh /output/work-transfer

FROM scratch AS artifact
COPY --from=builder /output/work-transfer /work-transfer
