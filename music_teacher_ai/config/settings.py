from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# API credentials
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN", "")

# Storage paths
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "music.db")))
FAISS_INDEX_PATH = Path(os.getenv("FAISS_INDEX_PATH", str(BASE_DIR / "data" / "embeddings.index")))
PLAYLISTS_DIR = Path(os.getenv("PLAYLISTS_DIR", str(BASE_DIR / "data" / "playlists")))

# Ingestion settings
BILLBOARD_START_YEAR = 1960
BILLBOARD_CHART = "hot-100"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
