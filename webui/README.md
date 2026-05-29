# Web UI for Twitch Drops Miner

The Twitch Drops Miner includes a modern web-based interface using [NiceGUI](https://nicegui.io/). Access your mining dashboard from any device on your network through a web browser - no desktop environment required.

## How It Works

The WebUI runs entirely within a single asyncio event loop alongside the Twitch backend. This single-threaded architecture eliminates thread synchronization issues and provides better performance and reliability compared to the previous threading-based implementation.

When you start the WebUI:
1. The NiceGUI server starts and serves the web interface
2. The Twitch backend runs within the same event loop
3. You access the dashboard through any web browser
4. Multiple browser tabs can connect simultaneously with full state synchronization

## Installation

The WebUI requires the NiceGUI dependencies:

```bash
pip install -r requirements-nicegui.txt
```

## Usage

### Starting the WebUI

Run the dedicated WebUI entry point:

```bash
python main_webui.py
```

See `python main_webui.py --help` for available command-line options (e.g. `--stdlog`, `-v`).

### Accessing the Interface

Once started, open your web browser and navigate to:
- **Default**: `http://localhost:5800` (or `https://localhost:5800` with `SECURE_CONNECTION=1`)
- **Custom**: Set via the `WEBUI_HOST`, `WEBUI_PORT`, and `SECURE_CONNECTION` environment variables

The WebUI is accessible from any device on your network. Use your machine's IP address to access remotely (e.g., `http://192.168.1.100:5800`).

### Using tkinter Instead

To use the traditional desktop GUI, run the original entry point:

```bash
python main.py
```

## Configuration

The WebUI host, port, and authentication are configured via environment variables:

- **WEBUI_HOST**: Network interface to bind to (default: `0.0.0.0`)
  - `0.0.0.0` - Listen on all interfaces (accessible from other devices)
  - `127.0.0.1` or `localhost` - Local access only

- **WEBUI_PORT**: Port to serve on, must be an integer between 1 and 65535 (default: `5800`)

- **WEBUI_AUTH**: Enable login authentication (default: `0`)
  - `1` - Require username/password to access the WebUI
  - `0` - No authentication (auth system is completely disabled)

- **SECURE_CONNECTION**: Enable HTTPS (default: `0`)
  - `1` - Serve the WebUI over HTTPS using TLS certificates
  - `0` - Serve the WebUI over plain HTTP

  When `1`, certificates are read from `config/certs/`:
  - `web-privkey.pem` — Web server's private key
  - `web-fullchain.pem` — Web server's certificate, bundled with any root and intermediate certificates

  If either file is missing, a self-signed certificate is automatically generated and written to those paths. Self-signed certs include `localhost` and `127.0.0.1` as Subject Alternative Names, plus the container hostname and its resolved IP when running in Docker with `--hostname`.

```bash
WEBUI_HOST=127.0.0.1 WEBUI_PORT=8080 WEBUI_AUTH=1 SECURE_CONNECTION=1 python main_webui.py
```

## Features

The WebUI provides all the functionality of the traditional GUI:

- **Main Tab**: Real-time console output, status monitoring, progress tracking, and channel management
- **Inventory Tab**: View available drops and campaigns  
- **Settings Tab**: Configure games, priorities, and WebUI settings
- **Help Tab**: Application information and links

## Comparison with tkinter GUI

| Feature | WebUI | tkinter GUI |
|---------|-------|-------------|
| Access | Any browser on network | Desktop only |
| Multiple views | Multiple browser tabs | Single window |
| Remote access | Yes | No |
| System tray | Not available | Supported |
| Architecture | Single event loop | Separate threads |

## Security Notes

- By default, the WebUI listens on all interfaces (`0.0.0.0`), making it accessible from other devices
- Set `WEBUI_HOST=127.0.0.1` for local-only access
- Consider firewall rules or a reverse proxy if exposing beyond your local network

### Authentication

When enabled, the WebUI requires a login before accessing the dashboard:

- **First visit** (no users exist): You'll be prompted to register an admin account with a username, password, and confirmation
- **Subsequent visits**: Sign in with the registered username and password
- Credentials are stored hashed (argon2) in `config/webui_auth.db`
- A random JWT signing secret is auto-generated and stored in the same database
- Login attempts are rate-limited to 5 per minute per IP address
- A logout button appears in the header bar when auth is enabled
- Sessions last 30 days via an httponly cookie

Authentication is disabled by default (`WEBUI_AUTH=0`). The entire auth system is skipped — no middleware, no login page, no database is created.

## Troubleshooting

**"NiceGUI is not installed" error**
```bash
pip install nicegui
```

**Cannot access from another device**
- Check that `WEBUI_HOST` is set to `0.0.0.0`
- Verify firewall rules allow connections on the configured port
- Use the host machine's IP address, not `localhost`

**Port already in use**
- Change `WEBUI_PORT` to a different value (e.g., `8081` or `9000`)
- Find what's using the port: `lsof -i :5800` (Linux/Mac) or `netstat -ano | findstr :5800` (Windows)

## Technical Note

The WebUI implementation uses a single-threaded architecture where the NiceGUI server and Twitch backend share the same asyncio event loop. This eliminates the need for thread synchronization utilities and provides better performance.
