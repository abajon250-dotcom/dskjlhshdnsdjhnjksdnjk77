import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip()
if REQUIRED_CHANNEL and not REQUIRED_CHANNEL.startswith("@"):
    REQUIRED_CHANNEL = "@" + REQUIRED_CHANNEL
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) if os.getenv("ADMIN_CHAT_ID") and os.getenv("ADMIN_CHAT_ID").strip().isdigit() else None