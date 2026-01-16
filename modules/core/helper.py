import os

from modules.core.logger import logger


def ensure_directory_exists(dir_path: str) -> None:
    """
    Checks if directory exists, creates it if it doesn't.
    """
    os.makedirs(dir_path, exist_ok=True)
    logger.debug(f"Ensured directory exists: {dir_path}")


def remove_files(directory: str) -> None:
    """
    Removes all files in specified directory. If directory doesn't exist,
    it will be created.
    """
    ensure_directory_exists(directory)
    file_count = 0
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        try:
            os.remove(file_path)
            file_count += 1
        except OSError as e:
            logger.error(f"Error deleting file {file_path}: {e}")
    logger.debug(f"Removed {file_count} files from {directory}")


def format_timestamp(seconds: float) -> str:
    """
    Converts seconds to HH:MM:SS format.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_timestamp(timestamp_str: str) -> float:
    """
    Converts HH:MM:SS format back to seconds.
    """
    parts = timestamp_str.split(':')
    hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
    return hours * 3600 + minutes * 60 + seconds
