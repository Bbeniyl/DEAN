FROM ghcr.io/browserless/chromium:latest

ENV HOST=0.0.0.0
ENV TIMEOUT=-1
ENV MAX_RECONNECT_TIME=-1
ENV CONCURRENT=1
ENV QUEUED=2

# Render injects PORT at runtime. Browserless reads PORT directly.
