# npc-cortex smoke image: pinned deps, isolated engine-wide test run.
# Build:  docker build -t npc-cortex-smoke .
# Run:    docker run --rm npc-cortex-smoke
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    PATH=/opt/cargo/bin:$PATH

# System libs: curl (rustup), cc (ring crate), GL/X (Panda3D wheels).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates build-essential libgl1 libglib2.0-0 \
    libsm6 libice6 libx11-6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Pinned Python deps (real Panda3D: no TaskManager stub in here).
RUN pip install "pytest==9.0.2" "panda3d==1.10.15"

# Pinned Rust toolchain (1.99+: bevy_ecs 0.20 needs rustc 1.95+).
RUN curl -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain 1.99.1 --no-modify-path \
    && rustc --version && cargo --version

WORKDIR /app
COPY . /app

# Pre-fetch + pre-compile Rust deps so the smoke run needs no network.
RUN cd clients/rust && cargo fetch && cargo build --tests \
    && cd ../bevy && cargo fetch && cargo build --tests

CMD ["sh", "docker/smoke.sh"]
