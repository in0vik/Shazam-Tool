from enum import Enum

APP_TITLE = 'Shazam Tool'
"""Application title"""

APPLICATION_LOGS_DIR = 'logs'
"""Directory for application logs"""

DOWNLOADS_DIR = 'downloads'
"""Directory for downloaded mp3 files"""

RESULTS_DIR = 'recognised-lists'
"""Directory for result txt files"""

AUDIO_SEGMENTS_DIR = 'audio-segments'
"""Directory for audio segments"""

SEGMENT_LENGTH = 10 * 1000
"""Duration of each segment in milliseconds (10 seconds)"""

MAX_RETRIES = 3
"""Maximum number of retries for Shazam API requests"""

TIMEOUT = 40
"""Timeout for Shazam API requests"""

class SegmentStatus(Enum):
    """Enum for track recognition segment statuses."""
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    VALIDATION_VALIDATED = "VALIDATION_VALIDATED"
    VALIDATION_FALSE_POSITIVE = "VALIDATION_FALSE_POSITIVE"
    VALIDATION_UNCERTAIN = "VALIDATION_UNCERTAIN"
    VALIDATION_WRONG_VERSION = "VALIDATION_WRONG_VERSION"
    FOUND_MERGED = "FOUND_MERGED"
