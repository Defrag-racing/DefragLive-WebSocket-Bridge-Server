# DefragLive WebSocket Bridge Server

A WebSocket bridge server that connects the DefragLive Twitch bot running on Windows with the Twitch extension frontend, enabling real-time communication, game settings control, and translation services.

## Overview

This server acts as a bridge between:
- **DefragLive Bot** (Windows) - The main bot controlling the Quake 3 Defrag game
- **Twitch Extension** (Frontend) - The user interface viewers interact with on Twitch
- **Translation API** - Google Translate integration for chat messages

## Features

- Real-time message broadcasting between bot and extension
- Game settings synchronization and control
- Translation services relay (handled by extension)
- Console message history persistence
- Server state management
- AFK detection and control

## Requirements

- Python 3.7+
- Docker (recommended)
- WebSocket connections from DefragLive bot and Twitch extension

## Installation

### Docker Deployment (Recommended)

1. Clone this repository:
```bash
git clone <repository-url>
cd defrag-websocket-bridge
```

2. Build and run with Docker:
```bash
docker build -t defrag-bridge .
docker run -d --name defrag-bridge -p 8443:8443 -v $(pwd)/logs:/home/websocket_server/logs defrag-bridge
```

### Manual Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the server:
```bash
python server.py --host 0.0.0.0 --port 8443
```

## Configuration

### Environment Variables

The server requires a Google Translate API key for translation services. Create a `.env` file:

```bash
cp .env.example .env
# Edit .env with your actual Google Translate API key
```

**Required Variables:**
- `GOOGLE_TRANSLATE_API_KEY` - Your Google Cloud Translation API key

**Getting a Google Translate API Key:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Cloud Translation API
4. Create credentials (API Key)
5. Add the key to your `.env` file

## File Structure

```
/
├── server.py              # Main WebSocket server
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── .env                  # Your environment variables (create this)
├── Dockerfile            # Docker configuration
├── logs/                 # Log files directory
├── console.json          # Chat message history
├── serverstate.json      # Current game server state
└── current_settings.json # Current game settings
```

## Data Files

The server automatically creates and manages these files:

- **`console.json`** - Stores the last 100 chat messages for persistence
- **`serverstate.json`** - Current game server state (players, map, etc.)
- **`current_settings.json`** - Current game settings (brightness, graphics, etc.)

### Public API Access

These JSON files are automatically copied out of the Docker container via cron jobs to enable public HTTP access at:
- `https://tw.defrag.racing/console.json` - Chat message history
- `https://tw.defrag.racing/serverstate.json` - Current server state

This allows the Twitch extension and other services to access the data via standard HTTP requests without needing WebSocket connections.

#### Setting up the Cron Jobs

Create cron jobs to copy the JSON files from the Docker container to your web server directory. 

Add these lines to your crontab (`crontab -e`):

```bash
# Copy DefragLive data files every minute
* * * * * docker cp recursing_germain:/home/websocket_server/serverstate.json /var/www/html/
* * * * * docker cp recursing_germain:/home/websocket_server/console.json /var/www/html/
```

Replace `recursing_germain` with your actual Docker container name, and adjust the destination path (`/var/www/html/`) to match your web server's document root.

### File Persistence Issues in Docker

If you experience issues with files being copied out of the Docker container, this is likely due to volume mounting or permission issues. To resolve:

1. **Ensure proper volume mounting**:
```bash
docker run -d --name defrag-bridge \
  -p 8443:8443 \
  -v $(pwd)/logs:/home/websocket_server/logs \
  -v $(pwd)/data:/home/websocket_server/data \
  defrag-bridge
```

2. **Set correct permissions**:
```bash
mkdir -p logs data
chmod 755 logs data
```

3. **Alternative: Use Docker volumes**:
```bash
docker volume create defrag-logs
docker volume create defrag-data
docker run -d --name defrag-bridge \
  -p 8443:8443 \
  -v defrag-logs:/home/websocket_server/logs \
  -v defrag-data:/home/websocket_server/data \
  defrag-bridge
```

## Usage

### Starting the Server

```bash
python server.py --host 0.0.0.0 --port 8443
```

Or with Docker:
```bash
docker run -d --name defrag-bridge -p 8443:8443 defrag-bridge
```

### Connecting Clients

The server accepts WebSocket connections on `ws://your-server:8443/`

**DefragLive Bot Connection**:
- Bot identifies itself with `{"action": "identify_bot"}`
- Receives settings commands and sends game state updates

**Twitch Extension Connection**:
- Connects directly for real-time updates
- Sends user commands and receives game state/chat

## API Reference

### WebSocket Message Types

#### From DefragLive Bot
```json
{
  "action": "identify_bot"
}

{
  "action": "sync_settings",
  "source": "defrag_bot",
  "settings": {...}
}

{
  "action": "serverstate",
  "message": {...}
}
```

#### From Twitch Extension
```json
{
  "action": "ext_command",
  "message": {
    "content": {
      "action": "settings_batch",
      "settings": {...}
    }
  }
}

{
  "action": "ext_command",
  "message": {
    "content": {
      "action": "translate_message",
      "cache_key": "...",
      "text": "...",
      "message_id": "..."
    }
  }
}
```

### Settings Configuration

The server supports these game settings:

#### Visual Settings (Instant Apply)
- `triggers` - Show trigger brushes
- `sky` - Sky rendering
- `clips` - Show clip brushes  
- `slick` - Highlight slick surfaces
- `gamma` - Display gamma (1.0-1.6)

#### Visual Settings (Require vid_restart)
- `brightness` - Map brightness (1-5)
- `picmip` - Texture quality (0-5)
- `fullbright` - Fullbright mode (boolean)

#### HUD Settings
- `drawgun` - Draw weapon
- `angles` - Weapon angles display
- `lagometer` - Network lagometer
- `snaps` - Snaps HUD element
- `cgaz` - CGaz HUD element
- `speedinfo` - Speed info display
- `speedorig` - Original speed HUD
- `inputs` - Input display (WASD)
- `obs` - Overbounces indicator

#### Gameplay Settings
- `nodraw` - Player visibility
- `thirdperson` - Third person view
- `miniview` - Miniview window
- `gibs` - Gibs after kill
- `blood` - Blood after kill

## Translation System

The server includes a translation system with:

- **Caching**: Translations are cached to reduce API calls
- **Rate Limiting**: Prevents API quota exhaustion
- **Cache Management**: Automatically cleans old translations (max 500 entries)

## Monitoring and Logs

Logs are written to:
- Console output (stdout)
- `logs/` directory with timestamp-based filenames

Log format: `MM/DD/YYYY HH:MM:SS message`

## Troubleshooting

### Common Issues

1. **Connection Refused**:
   - Check if the server is running
   - Verify port 8443 is open
   - Check firewall settings

2. **Translation Not Working**:
   - Translation is handled by the extension
   - Check extension configuration
   - This server only relays translation requests

3. **Settings Not Syncing**:
   - Ensure DefragLive bot is connected and identified
   - Check WebSocket connection status
   - Review server logs for command errors

4. **File Persistence Issues**:
   - Check Docker volume mounts
   - Verify file permissions
   - Ensure sufficient disk space

### Debug Mode

Enable debug logging:
```bash
python server.py --host 0.0.0.0 --port 8443 --debug
```

## Development

### Local Development Setup

1. Clone the repository
2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. Create `.env` file with your configuration
5. Run server:
```bash
python server.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

[Specify your license here]

## Support

For issues and support:
- Open an issue on GitHub
- Check the logs directory for error details
- Verify your environment configuration