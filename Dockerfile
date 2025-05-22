FROM python:3.12-slim AS builder

# Set working directory for the builder stage
WORKDIR /app

# Install build dependencies needed for pip, PyGObject and cairo dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    python3-dev \
    libcairo2-dev \
    libgirepository1.0-dev \
    libglib2.0-dev \
    gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file to install dependencies
COPY requirements.txt /app/

# Install Python dependencies in a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir wheel && \
    pip install --no-cache-dir yarl>=1.7.2 && \
    pip install --no-cache-dir multidict>=6.0.2 && \
    pip install --no-cache-dir aiohttp>=3.9.0 && \
    pip install --no-cache-dir requests>=2.28.0 && \
    pip install --no-cache-dir -r /app/requirements.txt

# Second stage: minimal runtime image
FROM python:3.12-slim

# Add metadata labels
LABEL org.opencontainers.image.title="TwitchDropsMinerWeb"
LABEL org.opencontainers.image.description="A tool for mining Twitch drops with web interface"
LABEL org.opencontainers.image.source="https://github.com/Kaysharp42/TwitchDropsMinerWeb"
LABEL org.opencontainers.image.vendor="Kaysharp42"

# Set working directory
WORKDIR /app

# Install only the minimal runtime dependencies needed
RUN apt-get update && apt-get install -y \
    wget \
    libcairo2 \
    libgirepository-1.0-1 \
    gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 \
    tk \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/logs /app/cache /app/lang

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Verify installations worked
RUN python -c "import yarl; print(f'yarl version: {yarl.__version__}')" && \
    python -c "import aiohttp; print(f'aiohttp version: {aiohttp.__version__}')" && \
    python -c "import requests; print(f'requests version: {requests.__version__}')" && \
    # Create a file listing all installed packages for debugging
    pip freeze > /app/installed_packages.txt

# Set display variable to prevent tkinter from trying to use X server
ENV DISPLAY=''

# Copy source code
COPY *.py ./
COPY web/ ./web/
COPY icons/ ./icons/
COPY lang/ ./lang/

RUN mkdir -p /data && \
    chown -R miner:miner /data && \
    chmod 755 /data \

# Create a non-root user to run the application
RUN groupadd -r miner && useradd -r -g miner miner \
    && chown -R miner:miner /app \
    # Set proper permissions for the virtual environment
    && chown -R miner:miner /opt/venv

# Clean up unnecessary cache files to reduce image size
RUN find /opt/venv -name __pycache__ -type d -exec rm -rf {} +  2>/dev/null || true && \
    find /opt/venv -name "*.pyc" -delete && \
    find /opt/venv -name "*.pyo" -delete && \
    find /opt/venv -name "*.pyd" -delete

# Create volume mount points for persistent data
VOLUME ["/app/logs", "/app/cache", "/data"]

# Expose web interface port
EXPOSE 8080

# Copy entrypoint script that handles data persistence
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh && \
    chown miner:miner /app/docker-entrypoint.sh && \
    ls -la /app/docker-entrypoint.sh

# Switch to non-root user for better security
USER miner

# Set the entrypoint with web interface enabled and accessible from outside
ENTRYPOINT ["/app/docker-entrypoint.sh"]
