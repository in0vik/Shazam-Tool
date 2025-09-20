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


def create_extended_segment(audio_file: str, target_timestamp: str = None, mode: str = "both",
                          extension_seconds: int = 20, start_timestamp: str = None,
                          end_timestamp: str = None) -> str:
    """
    Creates an extended audio segment by merging the target segment with surrounding segments,
    or creates a segment from start to end timestamps.

    Args:
        audio_file: Path to the original audio file
        target_timestamp: Target timestamp (e.g., "00:01:30") - for single segment extension
        mode: "before", "after", or "both" - which direction to extend (when using target_timestamp)
        extension_seconds: How many seconds to extend in each direction (when using target_timestamp)
        start_timestamp: Start timestamp for range-based segment creation (e.g., "00:01:00")
        end_timestamp: End timestamp for range-based segment creation (e.g., "00:01:30")

    Returns:
        Path to the created extended segment file
    """
    try:
        if start_timestamp and end_timestamp:
            # Range-based segment creation for merging consecutive segments
            start_parts = start_timestamp.split(':')
            start_seconds = int(start_parts[0])*3600 + int(start_parts[1])*60 + int(start_parts[2])

            end_parts = end_timestamp.split(':')
            end_seconds = int(end_parts[0])*3600 + int(end_parts[1])*60 + int(end_parts[2])

            # Create output filename for range
            start_clean = start_timestamp.replace(':', '')
            end_clean = end_timestamp.replace(':', '')
            output_filename = f"{AUDIO_SEGMENTS_DIR}/merged_{start_clean}_to_{end_clean}.mp3"

        elif target_timestamp:
            # Original single segment extension logic
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

            # Create output filename for extended segment
            output_filename = f"{AUDIO_SEGMENTS_DIR}/extended_{target_timestamp.replace(':', '')}__{mode}.mp3"
        else:
            raise ValueError("Either target_timestamp or both start_timestamp and end_timestamp must be provided")

        # Load audio and extract segment
        audio = AudioSegment.from_file(audio_file, format="mp3")
        start_ms = start_seconds * 1000
        end_ms = min(end_seconds * 1000, len(audio))

        extended_segment = audio[start_ms:end_ms]

        # Create output directory and export segment
        ensure_directory_exists(AUDIO_SEGMENTS_DIR)
        extended_segment.export(output_filename, format="mp3")

        duration = (end_ms - start_ms) / 1000
        if start_timestamp and end_timestamp:
            logger.debug(f"Created merged segment: {output_filename} ({duration:.1f}s, range: {start_timestamp}-{end_timestamp})")
        else:
            logger.debug(f"Created extended segment: {output_filename} ({duration:.1f}s, mode: {mode})")

        return output_filename

    except Exception as e:
        if start_timestamp and end_timestamp:
            logger.error(f"Failed to create merged segment for range {start_timestamp}-{end_timestamp}: {e}")
        else:
            logger.error(f"Failed to create extended segment for {target_timestamp}: {e}")
        return ""
