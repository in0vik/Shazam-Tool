import os
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment

from modules.core.constants import SEGMENT_LENGTH, AUDIO_SEGMENTS_DIR
from modules.core.helper import ensure_directory_exists
from modules.core.logger import logger


def segment_audio(audio_file: str, num_threads: int = 4) -> None:
    """
    Segments MP3 file into chunks of SEGMENT_LENGTH duration (in milliseconds)
    using parallel processing.
    """
    ensure_directory_exists(AUDIO_SEGMENTS_DIR)
    logger.debug(f"Segmenting audio file: {audio_file} with {num_threads} threads")
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        segments = [audio[i:i + SEGMENT_LENGTH] for i in range(0, len(audio), SEGMENT_LENGTH)]
        total_segments = len(segments)
        logger.debug(f"Created {total_segments} segments of {SEGMENT_LENGTH}ms each")

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for idx, seg in enumerate(segments, start=1):
                segment_file_path = os.path.join(AUDIO_SEGMENTS_DIR, f"{idx}.mp3")
                futures.append(
                    executor.submit(seg.export, segment_file_path, format="mp3")
                )

            for future in futures:
                future.result()

    except Exception as e:
        logger.error(f"Failed to segment audio file {audio_file}: {e}")


def create_extended_segment(audio_file: str, target_timestamp: str, mode: str = "both",
                          extension_seconds: int = 20) -> str:
    """
    Creates an extended audio segment by merging the target segment with surrounding segments.

    Args:
        audio_file: Path to the original audio file
        target_timestamp: Target timestamp (e.g., "00:01:30")
        mode: "before", "after", or "both" - which direction to extend
        extension_seconds: How many seconds to extend in each direction

    Returns:
        Path to the created extended segment file
    """
    try:
        # Parse target timestamp to get segment start time in seconds
        time_parts = target_timestamp.split(':')
        target_seconds = int(time_parts[0])*3600 + int(time_parts[1])*60 + int(time_parts[2])

        # Calculate extended segment boundaries
        if mode == "before":
            start_seconds = max(0, target_seconds - extension_seconds)
            end_seconds = target_seconds + (SEGMENT_LENGTH // 1000)  # Original segment length
        elif mode == "after":
            start_seconds = target_seconds
            end_seconds = target_seconds + (SEGMENT_LENGTH // 1000) + extension_seconds
        else:  # both
            start_seconds = max(0, target_seconds - extension_seconds)
            end_seconds = target_seconds + (SEGMENT_LENGTH // 1000) + extension_seconds

        # Load audio and extract extended segment
        audio = AudioSegment.from_file(audio_file, format="mp3")
        start_ms = start_seconds * 1000
        end_ms = min(end_seconds * 1000, len(audio))

        extended_segment = audio[start_ms:end_ms]

        # Create output filename
        ensure_directory_exists(AUDIO_SEGMENTS_DIR)
        output_filename = f"{AUDIO_SEGMENTS_DIR}/extended_{target_timestamp.replace(':', '')}__{mode}.mp3"

        # Export extended segment
        extended_segment.export(output_filename, format="mp3")

        duration = (end_ms - start_ms) / 1000
        logger.debug(f"Created extended segment: {output_filename} ({duration:.1f}s, mode: {mode})")

        return output_filename

    except Exception as e:
        logger.error(f"Failed to create extended segment for {target_timestamp}: {e}")
        return ""
