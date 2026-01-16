import asyncio
import os
import time

from modules.audio.audioSegmentation import segment_audio, create_extended_segment
from modules.core.constants import SEGMENT_LENGTH, DOWNLOADS_DIR, RESULTS_DIR, AUDIO_SEGMENTS_DIR, SegmentStatus
from modules.core.helper import remove_files, format_timestamp, ensure_directory_exists, parse_timestamp
from modules.core.logger import logger
from modules.resultFileOperations import read_result_file, analyze_result_file, write_result_file
from modules.shazam.shazamApi import recognize_track


def process_audio_file(audio_file: str, output_filename: str, file_index: int, total_files: int, rescan_mode: bool = False) -> None:
    """
    Processes a single audio file: segments it, recognizes each segment,
    excludes duplicate tracks, and saves results.
    Supports selective rescanning of failed segments.
    """
    # If there are multiple files, display the file index
    if total_files > 2:
        logger.info(f"[{file_index}/{total_files}] Processing file: {audio_file}")
    else:
        logger.info(f"Processing file: {audio_file}")

    logger.debug(f"Starting processing for {audio_file}")
    unique_tracks = set()

    # Read existing results for rescan mode or initialize
    file_data = {"header": f"===== Scan results for {os.path.basename(audio_file)} ======", "segments": {}}
    rescan_info = {"rescan_segments": [], "max_segment": 0}

    if rescan_mode:
        file_data = read_result_file(output_filename)
        rescan_info = analyze_result_file(output_filename)
        if rescan_info["rescan_segments"]:
            logger.info(f"[RESCAN] Found {len(rescan_info['rescan_segments'])} TIMEOUT/ERROR segments to rescan")
        else:
            logger.info(f"[RESCAN] No TIMEOUT/ERROR segments need rescanning in {os.path.basename(audio_file)}")
            return


    logger.info("1/5 [CLEAN] Cleaning temporary files...")
    remove_files(AUDIO_SEGMENTS_DIR)

    logger.info("2/5 [CUT] Segmenting audio file...")
    segment_audio(audio_file)

    logger.info("3/5 [SCAN] Recognizing segments...")
    tmp_files = sorted(os.listdir(AUDIO_SEGMENTS_DIR), key=lambda x: int(os.path.splitext(x)[0]))
    total_segments = len(tmp_files)
    logger.debug(f"Found {total_segments} segments to process")

    for idx, file_name in enumerate(tmp_files, start=1):
        segment_path = os.path.join(AUDIO_SEGMENTS_DIR, file_name)

        # Skip segments that don't need rescanning
        if rescan_mode and idx not in rescan_info["rescan_segments"]:
            continue

        try:
            # Calculate timestamp for this segment (dynamic based on SEGMENT_LENGTH)
            start_time_seconds = (idx - 1) * (SEGMENT_LENGTH / 1000)
            timestamp = format_timestamp(start_time_seconds)

            logger.debug(f"Starting recognition for segment {idx}: {segment_path}")

            # Use modern asyncio pattern instead of deprecated get_event_loop()
            try:
                result = asyncio.run(recognize_track(segment_path))
                # get_name() now returns dict with status and track
                segment_status = result["status"]
                track_name = result["track"]
            except asyncio.TimeoutError:
                segment_status = SegmentStatus.TIMEOUT.value
                track_name = ""
            except Exception as seg_error:
                logger.debug(f"Segment {idx} error: {seg_error}")
                segment_status = SegmentStatus.ERROR.value
                track_name = ""

            # Build the progress output with timestamp and status
            if segment_status == SegmentStatus.FOUND.value:
                progress_str = f"[{idx}/{total_segments}] {timestamp}: {track_name}"
            else:
                progress_str = f"[{idx}/{total_segments}] {timestamp}: {segment_status}"
            logger.info(progress_str)

            # Update file_data structure
            file_data["segments"][timestamp] = {"status": segment_status, "track": track_name}

            if segment_status == SegmentStatus.FOUND.value and track_name not in unique_tracks:
                unique_tracks.add(track_name)
                logger.debug(f"Added new unique track at {timestamp}: {track_name}")
            else:
                status_msg = "duplicate" if track_name in unique_tracks else segment_status.lower()
                logger.debug(f"Segment {idx} - {status_msg}")

        except Exception as e:
            logger.error(f"Error processing segment {file_name} at {timestamp}: {e}")
            # Update file_data with error status
            file_data["segments"][timestamp] = {"status": SegmentStatus.ERROR.value, "track": "Processing failed"}
            logger.info(f"[{idx}/{total_segments}] {timestamp}: Error - skipping")
            continue

    # Write complete result file with new structure
    logger.info("4/5 [SAVE] Writing results...")
    write_result_file(output_filename, file_data["header"], file_data["segments"])

    logger.info("[CLEAN] Cleaning temporary files...")
    remove_files(AUDIO_SEGMENTS_DIR)
    logger.info(f"[OK] Successfully processed file: {audio_file}")
    logger.debug(f"Found {len(unique_tracks)} unique tracks in {audio_file}")


def process_downloads(rescan_mode: bool = False) -> None:
    """
    Process all MP3 files in DOWNLOADS_DIR: recognize each and save results to separate files named after each MP3.
    Supports selective rescanning of failed segments.
    """
    ensure_directory_exists(RESULTS_DIR)
    ensure_directory_exists(DOWNLOADS_DIR)

    mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
    if not mp3_files:
        logger.warning(f"[ERROR] No MP3 files found in '{DOWNLOADS_DIR}' directory.")
        return

    total_files = len(mp3_files)
    action = "rescan" if rescan_mode else "process"
    logger.info(f"[INFO] Found {total_files} MP3 file(s) to {action}...")
    logger.info(f"[START] Starting {action}ing...")

    for idx, file_name in enumerate(mp3_files, start=1):
        full_path = os.path.join(DOWNLOADS_DIR, file_name)

        # Create output filename based on MP3 name (without timestamp for rescan analysis)
        mp3_base_name = os.path.splitext(file_name)[0]
        output_filename = os.path.join(RESULTS_DIR, f"{mp3_base_name}.txt")

        logger.debug(f"Processing file {idx}/{total_files}: {full_path}")
        logger.debug(f"Output will be saved to: {output_filename}")

        # For initial scan, create/overwrite the output file
        if not rescan_mode:
            try:
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(f"===== Scan results for {file_name} ======\n\n")
            except OSError as e:
                logger.error(f"Error creating output file {output_filename}: {e}")
                continue

        process_audio_file(full_path, output_filename, idx, total_files, rescan_mode)
        logger.info(f"[SAVED] Results for {file_name} saved to {output_filename}")

    logger.info(f"5/5 [DONE] All files successfully {action}ed!")


def rescan_timeouts_with_retry(audio_file: str, output_filename: str, max_retries: int = 2) -> bool:
    """
    Rescans TIMEOUT segments with retry logic and delays.
    Returns True if any improvements were made.
    """
    logger.info("[PHASE 1] Starting TIMEOUT resolution with retry...")

    improvements_made = False
    retry_count = 0

    while retry_count < max_retries:
        # Analyze current results for timeouts
        rescan_info = analyze_result_file(output_filename)

        if not rescan_info["rescan_segments"]:
            logger.info(f"[PHASE 1] No TIMEOUT segments found after {retry_count} retries")
            break

        logger.info(f"[PHASE 1] Round {retry_count + 1}: Found {len(rescan_info['rescan_segments'])} TIMEOUT segments to retry")

        if retry_count > 0:
            logger.info(f"[PHASE 1] Waiting 60 seconds before retry...")
            time.sleep(60)

        # Read current file data
        file_data = read_result_file(output_filename)

        # Rescan only timeout segments
        logger.info("Segmenting audio file...")
        segment_audio(audio_file)

        tmp_files = sorted(os.listdir(AUDIO_SEGMENTS_DIR), key=lambda x: int(os.path.splitext(x)[0]))

        timeout_segments_processed = 0
        for idx, file_name in enumerate(tmp_files, start=1):
            if idx not in rescan_info["rescan_segments"]:
                continue

            segment_path = os.path.join(AUDIO_SEGMENTS_DIR, file_name)
            start_time_seconds = (idx - 1) * (SEGMENT_LENGTH / 1000)
            timestamp = format_timestamp(start_time_seconds)

            try:
                result = asyncio.run(recognize_track(segment_path))
                segment_status = result["status"]
                track_name = result["track"]

                # Update if status changed from TIMEOUT
                if segment_status != SegmentStatus.TIMEOUT.value:
                    file_data["segments"][timestamp] = {"status": segment_status, "track": track_name}
                    improvements_made = True
                    logger.info(f"[PHASE 1] Segment {idx} ({timestamp}): {segment_status}")
                else:
                    logger.info(f"[PHASE 1] Segment {idx} ({timestamp}): Still TIMEOUT")

                timeout_segments_processed += 1

            except Exception as e:
                logger.debug(f"Error rescanning segment {idx}: {e}")
                continue

        # Clean up and save results
        remove_files(AUDIO_SEGMENTS_DIR)
        write_result_file(output_filename, file_data["header"], file_data["segments"])

        logger.info(f"[PHASE 1] Round {retry_count + 1} complete: processed {timeout_segments_processed} segments")
        retry_count += 1

    logger.info(f"[PHASE 1] TIMEOUT resolution complete after {retry_count} rounds")
    return improvements_made


def find_consecutive_not_found_ranges(segments: dict, min_consecutive: int = 3) -> list:
    """
    Finds ranges of consecutive NOT_FOUND segments.
    Returns list of tuples: [(start_timestamp, end_timestamp, segment_count), ...]
    """
    sorted_timestamps = sorted(segments.keys(), key=lambda x: parse_timestamp(x))
    ranges = []
    current_range = []

    for timestamp in sorted_timestamps:
        if segments[timestamp]["status"] == SegmentStatus.NOT_FOUND.value:
            current_range.append(timestamp)
        else:
            # End of NOT_FOUND sequence
            if len(current_range) >= min_consecutive:
                ranges.append((current_range[0], current_range[-1], len(current_range)))
            current_range = []

    # Check final range
    if len(current_range) >= min_consecutive:
        ranges.append((current_range[0], current_range[-1], len(current_range)))

    return ranges


def update_segments_with_found_track(segments: dict, start_timestamp: str, end_timestamp: str, track_name: str) -> int:
    """
    Updates all segments in the range with the found track and FOUND_MERGED status.
    Returns number of segments updated.
    """
    start_seconds = parse_timestamp(start_timestamp)
    end_seconds = parse_timestamp(end_timestamp)

    updated_count = 0
    for timestamp, data in segments.items():
        timestamp_seconds = parse_timestamp(timestamp)
        if start_seconds <= timestamp_seconds <= end_seconds:
            segments[timestamp] = {"status": SegmentStatus.FOUND_MERGED.value, "track": track_name}
            updated_count += 1

    return updated_count


def sliding_window_merge_recognition(audio_file: str, start_timestamp: str, end_timestamp: str,
                                   segment_count: int, segments: dict) -> tuple:
    """
    Applies sliding window approach to find tracks in consecutive NOT_FOUND segments.
    Returns (success: bool, track_name: str, successful_start: str, successful_end: str)
    """
    logger.info(f"[PHASE 2] Processing range {start_timestamp}-{end_timestamp} ({segment_count} segments)")

    # Get all timestamps in the range
    start_seconds = parse_timestamp(start_timestamp)
    end_seconds = parse_timestamp(end_timestamp)

    range_timestamps = []
    for timestamp in sorted(segments.keys(), key=lambda x: parse_timestamp(x)):
        timestamp_seconds = parse_timestamp(timestamp)
        if start_seconds <= timestamp_seconds <= end_seconds and segments[timestamp]["status"] == SegmentStatus.NOT_FOUND.value:
            range_timestamps.append(timestamp)

    # Try sliding windows of increasing size
    for window_size in range(3, len(range_timestamps) + 1):
        logger.debug(f"[PHASE 2] Trying window size {window_size}")

        for start_idx in range(len(range_timestamps) - window_size + 1):
            end_idx = start_idx + window_size - 1
            window_start = range_timestamps[start_idx]
            window_end = range_timestamps[end_idx]

            # Calculate end timestamp for the last segment in window
            window_end_seconds = parse_timestamp(window_end) + (SEGMENT_LENGTH // 1000)
            window_end_timestamp = format_timestamp(window_end_seconds)

            logger.debug(f"[PHASE 2] Trying window {window_start}-{window_end_timestamp} ({window_size} segments)")

            try:
                # Create merged segment
                merged_segment_path = create_extended_segment(
                    audio_file=audio_file,
                    start_timestamp=window_start,
                    end_timestamp=window_end_timestamp
                )

                if not merged_segment_path:
                    continue

                # Recognize merged segment
                result = asyncio.run(recognize_track(merged_segment_path))

                # Clean up merged segment file
                if os.path.exists(merged_segment_path):
                    os.remove(merged_segment_path)

                if result["status"] == SegmentStatus.FOUND.value:
                    logger.info(f"[PHASE 2] SUCCESS: Found '{result['track']}' in window {window_start}-{window_end_timestamp}")
                    return True, result["track"], window_start, window_end_timestamp

            except Exception as e:
                logger.debug(f"Error processing window {window_start}-{window_end_timestamp}: {e}")
                continue

    logger.debug(f"[PHASE 2] No tracks found in range {start_timestamp}-{end_timestamp}")
    return False, "", "", ""


def process_not_found_segments(audio_file: str, output_filename: str) -> bool:
    """
    Processes consecutive NOT_FOUND segments using sliding window approach.
    Returns True if any improvements were made.
    """
    logger.info("[PHASE 2] Starting NOT_FOUND segment merging...")

    # Read current results
    file_data = read_result_file(output_filename)
    segments = file_data["segments"]

    # Find consecutive NOT_FOUND ranges
    not_found_ranges = find_consecutive_not_found_ranges(segments)

    if not not_found_ranges:
        logger.info("[PHASE 2] No consecutive NOT_FOUND ranges found (minimum 3 segments)")
        return False

    logger.info(f"[PHASE 2] Found {len(not_found_ranges)} ranges with consecutive NOT_FOUND segments")

    improvements_made = False

    for i, (start_ts, end_ts, count) in enumerate(not_found_ranges, 1):
        logger.info(f"[PHASE 2] Processing range {i}/{len(not_found_ranges)}: {start_ts}-{end_ts} ({count} segments)")

        success, track_name, successful_start, successful_end = sliding_window_merge_recognition(
            audio_file, start_ts, end_ts, count, segments
        )

        if success:
            # Update all segments in the successful range
            updated_count = update_segments_with_found_track(
                segments, successful_start, successful_end, track_name
            )
            logger.info(f"[PHASE 2] Updated {updated_count} segments with track: {track_name}")
            improvements_made = True

    if improvements_made:
        # Save updated results
        write_result_file(output_filename, file_data["header"], segments)
        logger.info("[PHASE 2] NOT_FOUND segment merging complete - results updated")
    else:
        logger.info("[PHASE 2] NOT_FOUND segment merging complete - no improvements found")

    return improvements_made
