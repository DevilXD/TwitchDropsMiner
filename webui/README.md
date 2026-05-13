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

The WebUI requires NiceGUI to be installed:

```bash
pip install nicegui
```

## Usage

### Starting the WebUI

Run the application using `entrypoint.py` with the `UI_BACKEND` environment variable set to `nicegui`:

```bash
# Linux/Mac
UI_BACKEND=nicegui python entrypoint.py

# Windows
set UI_BACKEND=nicegui
python entrypoint.py
```

### Accessing the Interface

Once started, open your web browser and navigate to:
- **Default**: `http://localhost:5800`
- **Custom**: Depends on your `webui_host` and `webui_port` settings

The WebUI is accessible from any device on your network. Use your machine's IP address to access remotely (e.g., `http://192.168.1.100:5800`).

### Using tkinter Instead

To use the traditional desktop GUI instead, either omit the environment variable or set it to `tkinter`:

```bash
# Uses tkinter (default behavior)
python entrypoint.py

# Or explicitly
UI_BACKEND=tkinter python entrypoint.py
```

## Configuration

WebUI settings are stored in your standard Twitch Drops Miner settings file (`settings.json`):

- **webui_host**: Network interface to bind to (default: `0.0.0.0`)
  - `0.0.0.0` - Listen on all interfaces (accessible from other devices)
  - `127.0.0.1` or `localhost` - Local access only
  
- **webui_port**: Port to serve on (default: `5800`)

You can modify these settings in the WebUI's Settings tab or by editing `settings.json` directly.

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
- Use `127.0.0.1` as the host for local-only access
- No authentication is built-in - anyone on your network can access the interface
- Consider firewall rules or a reverse proxy if exposing beyond your local network

## Troubleshooting

**"NiceGUI is not installed" error**
```bash
pip install nicegui
```

**Cannot access from another device**
- Check that `webui_host` is set to `0.0.0.0` in settings
- Verify firewall rules allow connections on the configured port
- Use the host machine's IP address, not `localhost`

**Port already in use**
- Change `webui_port` to a different value (e.g., `8081` or `9000`)
- Find what's using the port: `lsof -i :5800` (Linux/Mac) or `netstat -ano | findstr :5800` (Windows)

## Technical Note

The WebUI implementation uses a single-threaded architecture where the NiceGUI server and Twitch backend share the same asyncio event loop. This eliminates the need for thread synchronization utilities and provides better performance.
