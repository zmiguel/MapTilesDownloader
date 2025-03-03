import os

# Server configuration
SERVER_PORT = int(os.environ.get("TILE_DOWNLOADER_PORT", 8080))

# Directory paths
TEMP_DIR = "temp"
OUTPUT_DIR = "output"
UI_DIR = "./UI/"

# Default parameters
DEFAULT_TILE_FORMAT = "png"
DEFAULT_PROFILE = "mercator"
DEFAULT_TILE_SIZE = 256
DEFAULT_OUTPUT_SCALE = 1

# Request timeouts (seconds)
DOWNLOAD_TIMEOUT = 30
