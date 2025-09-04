from dotenv import load_dotenv
import requests
import threading
import asyncio
from aiorun import run
import json
import websockets
import argparse
import logging
from datetime import datetime
import os, sys
import ssl

# Load environment variables from .env file
load_dotenv()

# Add translation cache and locks
TRANSLATION_CACHE = {}
TRANSLATION_LOCKS = {}

# Add your Google Translate API key
GOOGLE_TRANSLATE_API_KEY = os.environ.get('GOOGLE_TRANSLATE_API_KEY', '')

CONSOLE_FILE = os.path.join(os.path.dirname(__file__), 'console.json')
SERVERSTATE_FILE = os.path.join(os.path.dirname(__file__), 'serverstate.json')
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'current_settings.json')

USERS = set()

MAX_CACHE_SIZE = 500  # Limit cache to 500 translations

def convert_settings_to_commands(settings):
    """Convert UI settings to game console commands"""
    commands = []
    needs_vid_restart = False

    # Setting configurations with toggle values and ranges
    setting_configs = {
        'triggers': {'cvar': 'r_rendertriggerBrushes', 'type': 'toggle', 'values': [0, 1]},
        'sky': {'cvar': 'r_fastsky', 'type': 'toggle', 'values': [1, 0]},
        'clips': {'cvar': 'r_renderClipBrushes', 'type': 'toggle', 'values': [0, 1]},
        'slick': {'cvar': 'r_renderSlickSurfaces', 'type': 'toggle', 'values': [0, 1]},
        'brightness': {'cvar': 'r_mapoverbrightbits', 'type': 'range', 'min': 1, 'max': 5, 'default': 2, 'vid_restart': True},
        'picmip': {'cvar': 'r_picmip', 'type': 'range', 'min': 0, 'max': 5, 'default': 0, 'vid_restart': True},
        'fullbright': {'cvar': 'r_fullbright', 'type': 'toggle', 'values': [0, 1], 'vid_restart': True},  # FIXED: Now toggle
        'gamma': {'cvar': 'r_gamma', 'type': 'range', 'min': 1.0, 'max': 1.6, 'default': 1.2, 'format_decimals': True},  # ADD format_decimals flag
        'drawgun': {'cvar': 'cg_drawgun', 'type': 'toggle', 'values': [2, 1]},
        'angles': {'cvar': 'df_chs1_Info6', 'type': 'toggle', 'values': [0, 40]},
        'lagometer': {'cvar': 'cg_lagometer', 'type': 'toggle', 'values': [0, 1]},
        'snaps': {'cvar': 'mdd_snap', 'type': 'toggle', 'values': [0, 3]},
        'cgaz': {'cvar': 'mdd_cgaz', 'type': 'toggle', 'values': [0, 1]},
        'speedinfo': {'cvar': 'df_chs1_Info5', 'type': 'toggle', 'values': [0, 23]},
        'speedorig': {'cvar': 'df_drawSpeed', 'type': 'toggle', 'values': [0, 1]},
        'inputs': {'cvar': 'df_chs0_draw', 'type': 'toggle', 'values': [0, 1]},
        'obs': {'cvar': 'df_chs1_Info7', 'type': 'toggle', 'values': [0, 50]},
        'nodraw': {'cvar': 'df_mp_NoDrawRadius', 'type': 'toggle', 'values': [100, 100000]},
        'thirdperson': {'cvar': 'cg_thirdperson', 'type': 'toggle', 'values': [0, 1]},
        'miniview': {'cvar': 'df_ghosts_MiniviewDraw', 'type': 'toggle', 'values': [0, 6]},
        'gibs': {'cvar': 'cg_gibs', 'type': 'toggle', 'values': [0, 1]},
        'blood': {'cvar': 'com_blood', 'type': 'toggle', 'values': [0, 1]}
    }

    for setting_key, setting_value in settings.items():
        if setting_key in setting_configs:
            config = setting_configs[setting_key]
            cvar = config['cvar']

            # Check if this setting needs vid_restart
            if config.get('vid_restart', False):
                needs_vid_restart = True

            if config['type'] == 'toggle':
                # For toggles, use the appropriate toggle value based on boolean state
                if isinstance(setting_value, bool):
                    value = config['values'][1] if setting_value else config['values'][0]
                else:
                    value = setting_value
            else:  # range type
                # For ranges, use the value directly
                value = setting_value
                
                # SPECIAL HANDLING FOR GAMMA TO PRESERVE DECIMALS
                if config.get('format_decimals', False):
                    # Format float to always show one decimal place
                    value = f"{float(value):.1f}"

            command = f"{cvar} {value}"
            commands.append(command)

    # Add vid_restart if needed - AFTER all the setting commands
    if needs_vid_restart:
        commands.append("vid_restart")
        logging.info("Added vid_restart command for video settings")

    return commands

async def send_commands_to_defrag_bot(commands):
    """Send console commands to DefragLive bot"""
    defrag_connections = [ws for ws in USERS if hasattr(ws, 'is_defrag_bot') and ws.is_defrag_bot]

    if not defrag_connections:
        logging.warning("DefragLive bot not connected - cannot send commands")
        return

    try:
        # Send each command to the bot
        for command in commands:
            command_message = {
                'action': 'execute_command',
                'command': command,
                'timestamp': datetime.now().timestamp()
            }

            for bot_ws in defrag_connections:
                await bot_ws.send(json.dumps(command_message))
                logging.info(f"Sent command to DefragLive bot: {command}")

    except websockets.exceptions.ConnectionClosed:
        logging.error("DefragLive bot connection lost while sending commands")
    except Exception as e:
        logging.error(f"Failed to send commands to DefragLive bot: {e}")

async def handle_translation_request(cache_key, text, message_id=None):
    global TRANSLATION_CACHE, TRANSLATION_LOCKS

    if cache_key in TRANSLATION_CACHE:
        logging.info(f"Translation cache hit for: {text[:50]}...")
        logging.info(f"Current cache size: {len(TRANSLATION_CACHE)} translations")
        await broadcast_translation(cache_key, TRANSLATION_CACHE[cache_key])
        return

    if cache_key in TRANSLATION_LOCKS:
        logging.info(f"Translation already in progress for: {text[:50]}...")
        return

    TRANSLATION_LOCKS[cache_key] = True

    try:
        logging.info(f"Starting translation for: {text[:50]}...")

        if not GOOGLE_TRANSLATE_API_KEY:
            logging.error("Google Translate API key not found")
            return

        response = requests.post('https://translation.googleapis.com/language/translate/v2',
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'https://tw.defrag.racing'
            },
            data={
                'key': GOOGLE_TRANSLATE_API_KEY,
                'q': text,
                'target': 'en',
                'format': 'text'
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'translations' in data['data'] and len(data['data']['translations']) > 0:
                translation = data['data']['translations'][0]['translatedText']

                # Add cache size check before storing new translation
                if len(TRANSLATION_CACHE) >= MAX_CACHE_SIZE:
                    # Remove oldest entries (simple approach - clear half the cache)
                    items_to_remove = len(TRANSLATION_CACHE) // 2
                    keys_to_remove = list(TRANSLATION_CACHE.keys())[:items_to_remove]
                    for key in keys_to_remove:
                        del TRANSLATION_CACHE[key]
                    logging.info(f"Cache limit reached. Removed {items_to_remove} old translations. Cache size now: {len(TRANSLATION_CACHE)}")

                TRANSLATION_CACHE[cache_key] = translation
                await broadcast_translation(cache_key, translation)
                logging.info(f"Translation completed: {text[:30]} -> {translation[:30]} (Cache size: {len(TRANSLATION_CACHE)})")
        else:
            logging.error(f"Translation API error: {response.status_code}")

    except Exception as e:
        logging.error(f"Translation failed: {e}")
    finally:
        if cache_key in TRANSLATION_LOCKS:
            del TRANSLATION_LOCKS[cache_key]

async def broadcast_translation(cache_key, translation):
    translation_broadcast = {
        'action': 'translation_result',
        'cache_key': cache_key,
        'translation': translation,
        'timestamp': datetime.now().timestamp()
    }

    await broadcast(translation_broadcast)
    logging.info(f"Broadcasted translation to all viewers")

async def save_serverstate(data):
    try:
        with open(SERVERSTATE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f'Failed to save serverstate to file: {e}')

async def broadcast(message_obj):
    if USERS:  # asyncio.wait doesn't accept an empty list
        message = json.dumps(message_obj)
        websockets.broadcast(USERS, message)

async def notify_message(message_obj):
    if USERS:  # asyncio.wait doesn't accept an empty list
        message = json.dumps(message_obj)
        for user in USERS:
            task = asyncio.create_task(user.send(message))
            await asyncio.wait({task})

        # Deprecated for newer Python/asyncio versions
        # await asyncio.wait([user.send(message) for user in USERS])

def register(websocket):
    USERS.add(websocket)

def unregister(websocket):
    USERS.remove(websocket)

# This function was moved here to be properly called
async def save_message(message_obj):
    try:
        # Read the existing chat history
        if os.path.exists(CONSOLE_FILE):
            with open(CONSOLE_FILE, 'r') as f:
                history = json.load(f)
        else:
            history = []

        # Append the new message
        history.append(message_obj)

        # Keep only the last 100 messages to prevent the file from getting too big
        history = history[-100:]

        # Write the updated history back to the file
        with open(CONSOLE_FILE, 'w') as f:
            json.dump(history, f, indent=2)

    except (IOError, json.JSONDecodeError) as e:
        logging.error(f'Failed to save message to console.json: {e}')

async def handle_settings_request(websocket, content):
    """Handle settings-related requests from extension"""

    if content.get('action') == 'get_current_settings':
        logging.info("Handling get_current_settings request")
        # Read current settings from file or use defaults
        try:
            with open(SETTINGS_FILE, 'r') as f:
                current_settings = json.load(f)
                logging.info(f"Loaded settings from file: {current_settings}")
        except (FileNotFoundError, json.JSONDecodeError):
            # Default settings if file doesn't exist
            current_settings = {
                'brightness': 2, 'picmip': 0, 'fullbright': False, 'gamma': 1.2,
                'sky': True, 'triggers': False, 'clips': False, 'slick': False,
                'drawgun': False, 'angles': False, 'lagometer': False, 'snaps': True,
                'cgaz': True, 'speedinfo': True, 'speedorig': False, 'inputs': True,
                'obs': False, 'nodraw': False, 'thirdperson': False, 'miniview': False,
                'gibs': False, 'blood': False
            }
            logging.info("Using default settings")

        response = {
            'action': 'current_settings',
            'settings': current_settings
        }

        # Send response back to the requesting user only
        await websocket.send(json.dumps(response))
        logging.info("Sent current_settings response")
        return

    elif content.get('action') == 'settings_batch':
        settings = content.get('settings', {})
        timestamp = content.get('timestamp', datetime.now().timestamp())
        
        # EXTRACT USERNAME FROM THE COMMAND:
        username = content.get('username', 'Unknown User')
        user_id = content.get('user_id')
        opaque_id = content.get('opaque_id')

        logging.info(f"Handling settings_batch from {username}: {settings}")

        # Save settings to file
        try:
            # Read existing settings
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    current_settings = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                current_settings = {}

            # Update with new settings
            current_settings.update(settings)

            # Save back to file
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(current_settings, f, indent=2)

            logging.info(f"Settings saved to file by {username}: {current_settings}")

        except Exception as e:
            logging.error(f"Failed to save settings for {username}: {e}")

        # Convert settings to game commands and send to DefragLive bot
        commands = convert_settings_to_commands(settings)
        await send_commands_to_defrag_bot(commands)

        # Broadcast settings change to all viewers WITH USERNAME:
        broadcast_msg = {
            'action': 'settings_applied',
            'settings': settings,
            'timestamp': timestamp,
            'username': username,  # ADD THIS
            'user_id': user_id,    # ADD THIS (optional)
            'opaque_id': opaque_id # ADD THIS (optional)
        }
        await broadcast(broadcast_msg)
        logging.info(f"Broadcasted settings_applied from {username} to all users")
        return

async def ws_server(websocket, path):
    register(websocket)
    logging.info('New connection (%s total)!' % len(USERS))

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                logging.info(f"Received message with action: {data.get('action', 'unknown')}")

                # Check if this is a DefragLive bot connection
                if data.get('action') == 'identify_bot':
                    websocket.is_defrag_bot = True
                    logging.info("DefragLive bot identified and registered")
                    continue

                # Handle settings sync from DefragLive bot
                elif data.get('action') == 'sync_settings' and data.get('source') == 'defrag_bot':
                    logging.info("Received settings sync from DefragLive bot")
                    settings = data.get('settings', {})

                    # Update VPS settings file with current game state
                    try:
                        with open(SETTINGS_FILE, 'w') as f:
                            json.dump(settings, f, indent=2)
                        logging.info(f"Updated VPS settings from DefragLive bot: {settings}")
                        
                        # NEW: Broadcast current settings to all extensions to update their UI
                        current_settings_msg = {
                            'action': 'current_settings',
                            'settings': settings
                        }
                        await broadcast(current_settings_msg)
                        logging.info("Broadcasted current_settings to all extensions")
                        
                    except Exception as e:
                        logging.error(f"Failed to update VPS settings: {e}")
                    continue

                # Handle translation requests
                if data.get('action') == 'ext_command' and 'message' in data and 'content' in data['message']:
                    content = data['message']['content']

                    if isinstance(content, dict):
                        # Handle translation requests
                        if content.get('action') == 'translate_message':
                            cache_key = content['cache_key']
                            text = content['text']
                            message_id = content.get('message_id')

                            logging.info(f"[TRANSLATION REQUEST] Cache key: {cache_key[:50]}...")
                            await handle_translation_request(cache_key, text, message_id)
                            continue

                        # Handle settings requests
                        elif content.get('action') in ['get_current_settings', 'settings_batch']:
                            await handle_settings_request(websocket, content)
                            continue

                valid_actions = [
                    'message', 'command', 'ext_command', 'serverstate',
                    'afk_notification', 'afk_help', 'server_record_celebration',
                    'connect_error', 'connect_success', 'translation_result',
                    'settings_applied', 'current_settings'
                ]

                if data.get('action') in valid_actions:
                    await broadcast(data)

                    if data['action'] in ['message', 'command', 'ext_command', 'afk_notification', 'afk_help', 'server_record_celebration']:
                        await save_message(data)

                    if data['action'] == 'serverstate':
                        await save_serverstate(data['message'])

                else:
                    logging.warning(f"Unsupported message action: {data.get('action', 'unknown')}")

            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse JSON message: {e}")
            except Exception as e:
                logging.error(f"Error processing message: {e}")

    except websockets.exceptions.ConnectionClosedError:
        logging.info('Connection closed normally')
    except Exception as e:
        logging.error(f'Connection error: {e}')
    finally:
        unregister(websocket)
        logging.info(f'Connection removed (%s remaining)' % len(USERS))

async def main(args):
    logging.info(f'Starting WS server ({args.host}:{args.port})...\n')
    await websockets.serve(ws_server, args.host, args.port)
    await asyncio.sleep(1.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='WebSocket server for Defrag/Twitch bot.')
    parser.add_argument('--host', dest='host', default='0.0.0.0', help='Host or IP address to connect to.')
    parser.add_argument('--port', dest='port', default=8443, help='Port to connect to.')
    args = parser.parse_args()

    server_logfile =f'{datetime.now().strftime("%m-%d-%Y_%H-%M-%S")}.log'
    file_handler = logging.FileHandler(filename=os.path.join('logs', server_logfile))
    stdout_handler = logging.StreamHandler(sys.stdout)
    handlers = [file_handler, stdout_handler]
    logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %I:%M:%S', level=logging.INFO, handlers=handlers)

    run(main(args))
