import asyncio
import os

from modules.audio.audioSegmentation import segment_audio
from modules.core.constants import SEGMENT_LENGTH, DOWNLOADS_DIR, RESULTS_DIR, AUDIO_SEGMENTS_DIR
from modules.core.helper import remove_files, format_timestamp, ensure_directory_exists
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
        logger.info(f"\n[{file_index}/{total_files}] Processing file: {audio_file}")
    else:
        logger.info(f"\nProcessing file: {audio_file}")

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
                segment_status = "TIMEOUT"
                track_name = ""
            except Exception as seg_error:
                logger.debug(f"Segment {idx} error: {seg_error}")
                segment_status = "ERROR"
                track_name = ""

            # Build the progress output with timestamp and status
            if segment_status == "FOUND":
                progress_str = f"[{idx}/{total_segments}] {timestamp}: {track_name}"
            else:
                progress_str = f"[{idx}/{total_segments}] {timestamp}: {segment_status}"
            logger.info(progress_str)

            # Update file_data structure
            file_data["segments"][timestamp] = {"status": segment_status, "track": track_name}

            if segment_status == "FOUND" and track_name not in unique_tracks:
                unique_tracks.add(track_name)
                logger.debug(f"Added new unique track at {timestamp}: {track_name}")
            else:
                status_msg = "duplicate" if track_name in unique_tracks else segment_status.lower()
                logger.debug(f"Segment {idx} - {status_msg}")

        except Exception as e:
            logger.error(f"Error processing segment {file_name} at {timestamp}: {e}")
            # Update file_data with error status
            file_data["segments"][timestamp] = {"status": "ERROR", "track": "Processing failed"}
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

    logger.info(f"\n5/5 [DONE] All files successfully {action}ed!")
