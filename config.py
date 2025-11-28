import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(','))) if os.getenv('ADMIN_IDS') else []

# Настройки бана и мута
BAN_DURATIONS = {
    '1h': 3600,
    '1d': 86400,
    '7d': 604800,
    'permanent': None
}

MUTE_DURATIONS = {
    '1h': 3600,
    '6h': 21600,
    '1d': 86400,
    '7d': 604800
}
