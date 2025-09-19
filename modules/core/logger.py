import os
import logging

from modules.core.constants import APP_TITLE, APPLICATION_LOGS_DIR

logger = logging.getLogger(APP_TITLE)


def setup_logging(debug_mode=False):
    """
    Configure logging based on debug mode.
    When debug mode is enabled, detailed logs are written to both console and file.
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Reset handlers if they exist
    logger.handlers = []
    logger.setLevel(log_level)

    # Ensure logs directory exists
    os.makedirs(APPLICATION_LOGS_DIR, exist_ok=True)

    # File handler - always logs at DEBUG level to app.log
    file_handler = logging.FileHandler(f'{APPLICATION_LOGS_DIR}/app.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)

    # Console handler - level depends on debug_mode
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # Use simpler format for console if not in debug mode
    if not debug_mode:
        console_format = '%(message)s'
    else:
        console_format = log_format

    console_handler.setFormatter(logging.Formatter(console_format))
    logger.addHandler(console_handler)

    if debug_mode:
        logger.debug("Debug mode enabled - detailed logging activated")
