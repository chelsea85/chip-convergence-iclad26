# Exact-version KLayout 0.30.1 (organizer scoring target) on Ubuntu 24.04 amd64.
# Host is Apple Silicon (arm64) → runs under Docker emulation; correctness over speed.
FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# KLayout 0.30.1 (pinned) — apt resolves its Qt/ruby runtime deps
RUN curl -fsSL https://www.klayout.org/downloads/Ubuntu-24/klayout_0.30.1-1_amd64.deb \
      -o /tmp/klayout.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/klayout.deb \
    && rm /tmp/klayout.deb && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages google-genai shapely

WORKDIR /asu
