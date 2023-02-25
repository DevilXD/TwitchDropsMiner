FROM python:3.9-bullseye

# Install xvfb - a virtual display for the GUI to display to
RUN apt-get update && apt-get upgrade -y
RUN apt-get install xvfb -y

RUN git clone https://github.com/DevilXD/TwitchDropsMiner.git
WORKDIR /TwitchDropsMiner/

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Execute every command with the virtual display active
ENTRYPOINT ["xvfb-run"]
CMD ["timeout", "30m", "python", "main.py"]

# Example command to build:
# docker build -t twitch_drops_miner .

# Suggested command to run:
# docker run -it --init --restart=always -v ./cookies.jar:/TwitchDropsMiner/cookies.jar -v ./settings.json:/TwitchDropsMiner/settings.json:ro twitch_drops_miner
