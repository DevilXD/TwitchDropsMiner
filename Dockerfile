FROM python:3.10-slim

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y \
    libgirepository1.0-dev libcairo2-dev pkg-config python3-dev \
    libgtk-3-0 dbus-x11 libcanberra-gtk3-module \
    x11vnc xvfb fluxbox wget unzip curl \
    chromium \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Télécharger noVNC + websockify
RUN mkdir -p /opt/novnc && \
    curl -L https://github.com/novnc/noVNC/archive/refs/tags/v1.4.0.zip -o /tmp/novnc.zip && \
    unzip /tmp/novnc.zip -d /opt && \
    mv /opt/noVNC-1.4.0/* /opt/novnc && \
    curl -L https://github.com/novnc/websockify/archive/refs/tags/v0.11.0.zip -o /tmp/ws.zip && \
    unzip /tmp/ws.zip -d /opt && \
    mv /opt/websockify-0.11.0 /opt/novnc/utils/websockify

COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV DISPLAY=:1

# Dossier des données persistantes (cookies.jar, settings.json, cache...)
ENV TDM_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 6080

ENTRYPOINT ["/entrypoint.sh"]
