import logging
import os

def setup_logger(log_level=logging.INFO):
    # Create logs directory if not exists
    os.makedirs('logs', exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/tile_downloader.log"),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger('tile_downloader')

logger = setup_logger()
