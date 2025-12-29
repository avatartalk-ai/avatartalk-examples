import os

from dotenv import load_dotenv

load_dotenv()

YOUTUBE_RTMP_URL = os.getenv("YOUTUBE_RTMP_URL")
YOUTUBE_STREAM_KEY = os.getenv("YOUTUBE_STREAM_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_LIVE_ID = os.getenv("YOUTUBE_LIVE_ID")
GOOGLE_CLIENT_SECRETS_PATH = os.getenv("GOOGLE_CLIENT_SECRETS_PATH")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_SECRET = os.getenv("LIVEKIT_API_SECRET")
AVATARTALK_URL = os.getenv("AVATARTALK_URL")
AVATARTALK_API_KEY = os.getenv("AVATARTALK_API_KEY")
AVATARTALK_AVATAR = os.getenv("AVATARTALK_AVATAR")
AVATARTALK_LANGUAGE = os.getenv("AVATARTALK_LANGUAGE", "en")
AVATARTALK_DEFAULT_BACKGROUND_URL = "https://avatartalk.ai/images/backgrounds/feng_shui_1.png"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AVATARTALK_PROMPT_PATH = os.getenv("AVATARTALK_PROMPT_PATH")

# Teacher setup
AVATARTALK_MODEL = os.getenv("AVATARTALK_MODEL", "gpt-4o-mini")
AVATARTALK_TOPICS_FILE = os.getenv("AVATARTALK_TOPICS_FILE", "topics.txt")

# GeneFace
GENEFACE_URL = os.getenv("GENEFACE_URL")

if not GENEFACE_URL:
    raise ValueError("GeneFace URL not provided!")
