FROM python:3.12-slim AS builder

# Set up build environment
WORKDIR /build

# Add metadata labels
LABEL org.opencontainers.image.title="TwitchDropsMinerWeb"
LABEL org.opencontainers.image.description="A tool for mining Twitch drops with web interface"
LABEL org.opencontainers.image.source="https://github.com/Kaysharp42/TwitchDropsMinerWeb"
LABEL org.opencontainers.image.vendor="Kaysharp42"

# Install build dependencies
RUN apt-get update && apt-get install -y \
    libgirepository1.0-dev \
    gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    wget \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Final image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy metadata labels from builder
# (No need to copy .dockerenv; removed invalid COPY command)

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libgirepository1.0-dev \
    gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 \
    wget \
    tk \
    python3-tk \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/logs /app/cache /app/lang

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Set display variable to prevent tkinter from trying to use X server
ENV DISPLAY=''

# Copy source code
COPY *.py ./
COPY web/ ./web/
COPY icons/ ./icons/
COPY lang/ ./lang/

# Create a non-root user to run the application
RUN groupadd -r miner && useradd -r -g miner miner \
    && chown -R miner:miner /app

# Create volume mount points for persistent data
VOLUME ["/app/logs", "/app/cache", "/app/settings.json", "/app/cookies.jar"]

# Expose web interface port
EXPOSE 8080

# Switch to non-root user for better security
USER miner

# Set the entrypoint with web interface enabled and accessible from outside
ENTRYPOINT ["python", "main.py", "--web", "--web-host=0.0.0.0", "--web-port=8080", "--log"]
