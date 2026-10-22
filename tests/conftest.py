import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# config.py reads these at import time; give it harmless values so the modules
# can be imported without a real .env file. load_dotenv() does not override
# variables that are already set, so a developer's own .env cannot leak in.
os.environ.setdefault("DATABASE_URL", "mongodb://localhost:27017")
os.environ.setdefault("DATABASE_NAME", "filesharexbot")
os.environ.setdefault("CHANNEL_ID", "-1001234567890")
os.environ.setdefault("OWNER_ID", "8495104954")
os.environ.setdefault("TG_BOT_TOKEN", "1234567:TESTTOKEN")
os.environ.setdefault("API_ID", "22138159")
os.environ.setdefault("API_HASH", "3fe4592e4cad72f366b6c564505f2d57")
