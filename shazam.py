import os
import sys
import asyncio
from datetime import datetime
import subprocess
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment
from shazamio import Shazam
from yt_dlp import YoutubeDL


# Duration of each segment in milliseconds (10 seconds)
SEGMENT_LENGTH = 10 * 1000

# Directory for downloaded files
DOWNLOADS_DIR = 'downloads'

# Logger setup
logger = logging.getLogger('shazam_tool')

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
    ensure_directory_exists('logs')

    # File handler - always logs at DEBUG level to app.log
    file_handler = logging.FileHandler('logs/app.log')
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


def analyze_result_file(result_file_path: str) -> dict:
    """
    Analyzes existing result file to determine which segments need rescanning.
    Returns dict with segments to rescan (timeout/error/not_found).
    """
    if not os.path.exists(result_file_path):
        return {"rescan_segments": [], "max_segment": 0}

    rescan_segments = []
    max_segment = 0
    in_scan_log = False

    try:
        with open(result_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                # Identify when we're in the scan log section
                if line == "===== Scan Log =====":
                    in_scan_log = True
                    continue
                elif line.startswith("=====") and in_scan_log:
                    # End of scan log section
                    break

                # Only process lines when we're in the scan log section
                if in_scan_log and " - " in line and not line.startswith("====="):
                    parts = line.split(" - ")
                    if len(parts) >= 2:
                        timestamp_str = parts[0]
                        # Handle multiple formats: old, new with tracks, and validation statuses
                        if len(parts) >= 3 and parts[1] in ["FOUND", "FOUND_VALIDATED", "FOUND_FALSE_POSITIVE", "FOUND_UNCERTAIN"]:
                            status = parts[1]  # FOUND, FOUND_VALIDATED, etc.
                        else:
                            status = parts[1]  # NOT_FOUND, TIMEOUT, ERROR

                        # Calculate segment number from timestamp
                        try:
                            timestamp_seconds = parse_timestamp(timestamp_str)
                            segment_num = int(timestamp_seconds / (SEGMENT_LENGTH / 1000)) + 1
                            max_segment = max(max_segment, segment_num)

                            # Mark segments that need rescanning (TIMEOUT and ERROR for rescan mode)
                            if status in ["TIMEOUT", "ERROR"]:
                                rescan_segments.append(segment_num)
                        except (ValueError, IndexError):
                            # Skip malformed timestamp lines
                            continue

    except Exception as e:
        logger.debug(f"Error analyzing result file {result_file_path}: {e}")
        return {"rescan_segments": [], "max_segment": 0}

    return {"rescan_segments": rescan_segments, "max_segment": max_segment}


def read_result_file(result_file_path: str) -> dict:
    """
    Reads existing result file and returns structured data.
    Parses both old and new format with separate Tracklist and Scan Log sections.
    """
    if not os.path.exists(result_file_path):
        return {"header": "", "segments": {}}

    segments = {}
    header = ""
    current_section = "none"
    track_data = {}  # timestamp -> {"track": track_name}

    try:
        with open(result_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()

            # Identify main header
            if line.startswith("===== Scan results for"):
                header = line
            # Identify sections
            elif line == "===== Tracklist =====":
                current_section = "tracklist"
            elif line == "===== Scan Log =====":
                current_section = "scan_log"
            # Parse content based on current section
            elif " - " in line and not line.startswith("=====") and not line.startswith("nr - time") and not line.startswith("number - time"):
                # First split to get timestamp, then handle the rest based on section
                parts = line.split(" - ")
                if len(parts) >= 2:
                    timestamp_str = parts[0]

                    if current_section == "tracklist":
                        # Handle both old and new formats
                        if timestamp_str.isdigit():
                            # New format: "01 - 00:01:10 - Artist - Title" (genre removed)
                            if len(parts) >= 4:
                                timestamp_str = parts[1]
                                artist = parts[2].strip()
                                title = " - ".join(parts[3:])
                                track_name = f"{artist} - {title}"
                                track_data[timestamp_str] = {"track": track_name}
                        else:
                            # Old format: "timestamp - artist - title"
                            track_name = " - ".join(parts[1:])
                            track_data[timestamp_str] = {"track": track_name}
                    elif current_section == "scan_log":
                        # Handle multiple formats: old "timestamp - status" and new "timestamp - FOUND_STATUS - track_name"
                        if len(parts) >= 3 and parts[1] in ["FOUND", "FOUND_VALIDATED", "FOUND_FALSE_POSITIVE", "FOUND_UNCERTAIN"]:
                            # New format with validation: "timestamp - FOUND_STATUS - track_name"
                            status = parts[1]
                            track_name = " - ".join(parts[2:])  # Join remaining parts in case track name contains " - "
                            if timestamp_str not in segments:
                                segments[timestamp_str] = {"status": status, "track": track_name}
                            else:
                                segments[timestamp_str]["status"] = status
                                segments[timestamp_str]["track"] = track_name
                        else:
                            # Old format: "timestamp - status" (for NOT_FOUND, TIMEOUT, ERROR)
                            status = parts[1]
                            if timestamp_str not in segments:
                                segments[timestamp_str] = {"status": status, "track": ""}
                            else:
                                segments[timestamp_str]["status"] = status

        # Merge track data with segments
        for timestamp, track_info in track_data.items():
            if timestamp in segments:
                segments[timestamp]["track"] = track_info["track"]
            else:
                # Track found but no scan log entry - assume FOUND status
                segments[timestamp] = {"status": "FOUND", "track": track_info["track"]}

        # Fill in missing track data for segments that don't have tracks
        for timestamp, segment in segments.items():
            if not segment["track"]:
                if segment["status"] == "FOUND":
                    segment["track"] = "Unknown Track"
                else:
                    segment["track"] = ""

    except Exception as e:
        logger.debug(f"Error reading result file {result_file_path}: {e}")

    return {"header": header, "segments": segments}


def generate_tracklist_and_log(segments: dict) -> tuple:
    """
    Generates condensed tracklist with numbered rows and aligned columns, plus scan log from segment data.
    """
    tracklist_data = []
    scan_log = []
    seen_tracks = set()

    # Sort segments by timestamp
    sorted_timestamps = sorted(segments.keys(), key=lambda x: parse_timestamp(x))

    for timestamp in sorted_timestamps:
        data = segments[timestamp]
        status = data["status"]
        track = data["track"]

        # Add to scan log with proper status
        if status in ["FOUND", "FOUND_VALIDATED", "FOUND_FALSE_POSITIVE", "FOUND_UNCERTAIN"] and track:
            scan_log.append(f"{timestamp} - {status} - {track}")
        else:
            scan_log.append(f"{timestamp} - {status}")

        # Add to tracklist only if found (but not false positive) and not already seen
        if status in ["FOUND", "FOUND_VALIDATED"] and track not in seen_tracks:
            # Split track into artist and title
            if " - " in track:
                artist, title = track.split(" - ", 1)
            else:
                artist = "Unknown Artist"
                title = track

            tracklist_data.append({
                "timestamp": timestamp,
                "artist": artist,
                "title": title
            })
            seen_tracks.add(track)

    # Generate formatted tracklist without header and minimal spacing
    tracklist = []

    # Add tracks with compact formatting
    for idx, item in enumerate(tracklist_data, 1):
        # Format number with leading spaces instead of zeros
        if idx < 10:
            number = f"  {idx}"  # 2 spaces for single digits
        elif idx < 100:
            number = f" {idx}"   # 1 space for double digits
        else:
            number = f"{idx}"    # no space for triple digits

        # Simple format: number - time - artist - title (no extra padding)
        formatted_line = f"{number} - {item['timestamp']} - {item['artist']} - {item['title']}"
        tracklist.append(formatted_line)

    return tracklist, scan_log


def write_result_file(result_file_path: str, header: str, segments: dict):
    """
    Writes complete result file with tracklist and scan log.
    """
    tracklist, scan_log = generate_tracklist_and_log(segments)

    try:
        with open(result_file_path, "w", encoding="utf-8") as f:
            f.write(f"{header}\n\n")

            # Write tracklist
            f.write("===== Tracklist =====\n")
            for track in tracklist:
                f.write(f"{track}\n")

            f.write("\n===== Scan Log =====\n")
            for log_entry in scan_log:
                f.write(f"{log_entry}\n")

    except OSError as e:
        logger.error(f"Error writing result file {result_file_path}: {e}")


def write_to_file(data: str, filename: str, timestamp: str = None) -> None:
    """
    Appends text string to specified file if data is not a failure status.
    Optionally includes timestamp if provided.
    """
    if data not in ["NOT_FOUND", "TIMEOUT", "ERROR"]:
        try:
            with open(filename, "a", encoding="utf-8") as f:
                if timestamp:
                    f.write(f"{timestamp} - {data}\n")
                else:
                    f.write(f"{data}\n")
        except OSError as e:
            print(f"Error writing to file {filename}: {e}")


def download_soundcloud(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download audio from a SoundCloud URL using yt-dlp.
    """
    ensure_directory_exists(output_path)
    logger.debug(f"Attempting to download from SoundCloud: {url}")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        logger.info("[OK] Successfully downloaded from SoundCloud!")
    except Exception as e:
        logger.error(f"[ERROR] Failed to download from SoundCloud {url}: {e}")


def download_youtube(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download the audio track from a YouTube video and convert to mp3 using yt-dlp.
    """
    ensure_directory_exists(output_path)
    logger.debug(f"Attempting to download from YouTube: {url}")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Title')
            logger.info(f"[OK] Successfully downloaded: {title}!")
    except Exception as e:
        logger.error(f"[ERROR] Error downloading from YouTube {url}: {e}")


def download_from_url(url: str) -> None:
    """
    Determines if URL is YouTube or SoundCloud and calls appropriate download function.
    """
    logger.info("[START] Starting download...")
    lower_url = url.lower()
    logger.debug(f"Processing URL: {url}")
    if 'soundcloud.com' in lower_url:
        logger.info("[MUSIC] SoundCloud URL detected")
        download_soundcloud(url)
    elif 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        logger.info("[VIDEO] YouTube URL detected")
        download_youtube(url)
    else:
        logger.error("[ERROR] Unsupported URL format. Please provide a YouTube or SoundCloud link.")


def segment_audio(audio_file: str, output_directory: str = "tmp", num_threads: int = 4) -> None:
    """
    Segments MP3 file into chunks of SEGMENT_LENGTH duration (in milliseconds)
    using parallel processing.
    """
    ensure_directory_exists(output_directory)
    logger.debug(f"Segmenting audio file: {audio_file} with {num_threads} threads")
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        segments = [audio[i:i + SEGMENT_LENGTH] for i in range(0, len(audio), SEGMENT_LENGTH)]
        total_segments = len(segments)
        logger.debug(f"Created {total_segments} segments of {SEGMENT_LENGTH}ms each")

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for idx, seg in enumerate(segments, start=1):
                segment_file_path = os.path.join(output_directory, f"{idx}.mp3")
                futures.append(
                    executor.submit(seg.export, segment_file_path, format="mp3")
                )

            for future in futures:
                future.result()

    except Exception as e:
        logger.error(f"Failed to segment audio file {audio_file}: {e}")


async def get_name(file_path: str, max_retries: int = 3, timeout: int = 40) -> dict:
    """
    Uses Shazam to recognize the song with retry logic, timeout, and error handling.
    Returns dict with 'status' and 'track' keys, or dict with error status.
    """
    import time
    shazam = Shazam()
    logger.debug(f"Attempting to recognize: {file_path} (max retries: {max_retries}, timeout: {timeout}s)")

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            logger.debug(f"Recognition attempt {attempt+1}/{max_retries} starting...")

            # Add timeout to prevent hanging
            data = await asyncio.wait_for(shazam.recognize(file_path), timeout=timeout)

            elapsed = time.time() - start_time
            logger.debug(f"API call completed in {elapsed:.2f}s")

            if 'track' not in data:
                logger.debug(f"No track data found in attempt {attempt+1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # Increased delay between retries
                    continue
                logger.debug("Recognition failed after all attempts - no track data")
                return {"status": "NOT_FOUND", "track": ""}

            title = data['track']['title']
            subtitle = data['track']['subtitle']

            track_string = f"{subtitle} - {title}"
            result = {"status": "FOUND", "track": track_string}
            logger.debug(f"Recognition successful in {elapsed:.2f}s: {track_string}")
            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(f"Recognition attempt {attempt+1} timed out after {elapsed:.2f}s")
            if attempt < max_retries - 1:
                logger.debug(f"Retrying with increased timeout...")
                await asyncio.sleep(3)  # Longer delay after timeout
                continue
            logger.warning("Recognition failed after all attempts due to timeout")
            return {"status": "TIMEOUT", "track": ""}

        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"Error in recognition attempt {attempt+1} after {elapsed:.2f}s: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            logger.warning("Recognition failed after all attempts due to exception")
            return {"status": "ERROR", "track": ""}


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
    remove_files("tmp")

    logger.info("2/5 [CUT] Segmenting audio file...")
    segment_audio(audio_file, "tmp")

    logger.info("3/5 [SCAN] Recognizing segments...")
    tmp_files = sorted(os.listdir("tmp"), key=lambda x: int(os.path.splitext(x)[0]))
    total_segments = len(tmp_files)
    logger.debug(f"Found {total_segments} segments to process")

    for idx, file_name in enumerate(tmp_files, start=1):
        segment_path = os.path.join("tmp", file_name)

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
                result = asyncio.run(get_name(segment_path))
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
    remove_files("tmp")
    logger.info(f"[OK] Successfully processed file: {audio_file}")
    logger.debug(f"Found {len(unique_tracks)} unique tracks in {audio_file}")


def process_downloads(rescan_mode: bool = False) -> None:
    """
    Process all MP3 files in DOWNLOADS_DIR: recognize each and save results to separate files named after each MP3.
    Supports selective rescanning of failed segments.
    """
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
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
        output_filename = os.path.join(output_dir, f"{mp3_base_name}.txt")

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


def analyze_false_positive_candidates(result_file_path: str, threshold: int = 3) -> dict:
    """
    Analyzes existing result file to identify potential false positive candidates.
    Returns dict with tracks that appear <= threshold times, ranked by suspicion level.
    """
    if not os.path.exists(result_file_path):
        logger.error(f"Result file not found: {result_file_path}")
        return {"candidates": [], "summary": {}}

    track_counts = {}
    track_positions = {}
    in_scan_log = False

    try:
        with open(result_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if line == "===== Scan Log =====":
                    in_scan_log = True
                    continue
                elif line.startswith("=====") and in_scan_log:
                    break

                # Check for any FOUND variant (FOUND, FOUND_VALIDATED, FOUND_FALSE_POSITIVE, FOUND_UNCERTAIN)
                if in_scan_log and (" - FOUND" in line):
                    parts_split = line.split(" - ")

                    if len(parts_split) >= 3:
                        timestamp = parts_split[0]
                        status = parts_split[1]
                        track_name = " - ".join(parts_split[2:])

                        # Only count legitimate tracks (exclude false positives from count)
                        if status in ["FOUND", "FOUND_VALIDATED"]:
                            if track_name not in track_counts:
                                track_counts[track_name] = 0
                                track_positions[track_name] = []

                            track_counts[track_name] += 1

                            # Convert timestamp to seconds for analysis
                            time_parts = timestamp.split(':')
                            seconds = int(time_parts[0])*3600 + int(time_parts[1])*60 + int(time_parts[2])
                            track_positions[track_name].append((timestamp, seconds))

        # Identify validation candidates
        candidates = []
        for track_name, count in track_counts.items():
            if count <= threshold:
                positions = sorted(track_positions[track_name], key=lambda x: x[1])

                candidate = {
                    'track': track_name,
                    'count': count,
                    'positions': positions,
                    'start_timestamp': positions[0][0],
                    'end_timestamp': positions[-1][0] if count > 1 else positions[0][0],
                    'duration_seconds': positions[-1][1] - positions[0][1] if count > 1 else 0,
                    'suspicion_level': 'HIGH' if count == 1 else 'MEDIUM' if count == 2 else 'LOW'
                }
                candidates.append(candidate)

        # Sort by suspicion level (count) and then by timestamp
        candidates.sort(key=lambda x: (x['count'], x['start_timestamp']))

        summary = {
            'total_unique_tracks': len(track_counts),
            'validation_candidates': len(candidates),
            'high_suspicion': len([c for c in candidates if c['count'] == 1]),
            'medium_suspicion': len([c for c in candidates if c['count'] == 2]),
            'low_suspicion': len([c for c in candidates if c['count'] == 3])
        }

        logger.info(f"Analysis complete: {len(candidates)} candidates found (threshold: <={threshold} occurrences)")

        return {"candidates": candidates, "summary": summary}

    except Exception as e:
        logger.error(f"Error analyzing result file {result_file_path}: {e}")
        return {"candidates": [], "summary": {}}


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
        ensure_directory_exists("tmp")
        output_filename = f"tmp/extended_{target_timestamp.replace(':', '')}__{mode}.mp3"

        # Export extended segment
        extended_segment.export(output_filename, format="mp3")

        duration = (end_ms - start_ms) / 1000
        logger.debug(f"Created extended segment: {output_filename} ({duration:.1f}s, mode: {mode})")

        return output_filename

    except Exception as e:
        logger.error(f"Failed to create extended segment for {target_timestamp}: {e}")
        return ""


def validate_segment_with_extended_audio(audio_file: str, candidate: dict) -> dict:
    """
    Validates a false positive candidate by re-recognizing with extended audio segments.

    Args:
        audio_file: Path to the original audio file
        candidate: Candidate dict from analyze_false_positive_candidates

    Returns:
        Dict with validation results
    """
    original_track = candidate['track']
    target_timestamp = candidate['start_timestamp']

    logger.info(f"Validating: {target_timestamp} - {original_track}")

    validation_results = {
        'original_track': original_track,
        'timestamp': target_timestamp,
        'extended_segments': {},
        'validation_status': 'UNKNOWN',
        'confidence': 'LOW'
    }

    # Test different extension modes
    modes = ["before", "after", "both"]

    for mode in modes:
        try:
            # Create extended segment
            extended_file = create_extended_segment(audio_file, target_timestamp, mode, 20)
            if not extended_file:
                continue

            # Recognize with extended segment
            logger.debug(f"Recognizing extended segment ({mode}): {extended_file}")
            result = asyncio.run(get_name(extended_file))

            validation_results['extended_segments'][mode] = {
                'status': result['status'],
                'track': result['track'],
                'matches_original': result['track'] == original_track if result['status'] == 'FOUND' else False
            }

            # Clean up extended segment file
            try:
                os.remove(extended_file)
            except:
                pass

        except Exception as e:
            logger.warning(f"Error validating with {mode} extension: {e}")
            validation_results['extended_segments'][mode] = {
                'status': 'ERROR',
                'track': '',
                'matches_original': False
            }

    # Analyze validation results
    found_results = [r for r in validation_results['extended_segments'].values()
                    if r['status'] == 'FOUND']

    if not found_results:
        validation_results['validation_status'] = 'NO_EXTENDED_RECOGNITION'
        validation_results['confidence'] = 'HIGH'  # Likely false positive
    else:
        matches = [r for r in found_results if r['matches_original']]
        different_tracks = [r for r in found_results if not r['matches_original']]

        if len(matches) >= 2:  # Multiple extensions confirm original
            validation_results['validation_status'] = 'CONFIRMED_VALID'
            validation_results['confidence'] = 'HIGH'
        elif len(different_tracks) >= 2:  # Multiple extensions disagree
            validation_results['validation_status'] = 'LIKELY_FALSE_POSITIVE'
            validation_results['confidence'] = 'HIGH'
            # Use most common alternative track
            alt_tracks = [r['track'] for r in different_tracks]
            validation_results['suggested_track'] = max(set(alt_tracks), key=alt_tracks.count)
        else:
            validation_results['validation_status'] = 'UNCERTAIN'
            validation_results['confidence'] = 'MEDIUM'

    logger.info(f"Validation result: {validation_results['validation_status']} - {original_track}")

    return validation_results


def validate_single_file(audio_file_path: str, result_file_path: str, threshold: int) -> None:
    """
    Validates a single audio file for false positives and updates the scan log with validation results.

    Args:
        audio_file_path: Path to the audio file
        result_file_path: Path to the corresponding result file
        threshold: Maximum occurrences for validation candidates
    """
    logger.info(f"[VALIDATE] Starting validation of {os.path.basename(audio_file_path)}")
    logger.info(f"[RESULTS] Using result file: {result_file_path}")

    # Read existing result file
    file_data = read_result_file(result_file_path)

    # Analyze candidates
    analysis = analyze_false_positive_candidates(result_file_path, threshold)
    candidates = analysis['candidates']
    summary = analysis['summary']

    if not candidates:
        logger.info("[RESULT] No validation candidates found - all tracks appear legitimate!")
        return

    logger.info(f"[CANDIDATES] Found {len(candidates)} validation candidates:")
    logger.info(f"  HIGH suspicion (1x): {summary['high_suspicion']} tracks")
    logger.info(f"  MEDIUM suspicion (2x): {summary['medium_suspicion']} tracks")
    logger.info(f"  LOW suspicion (3x): {summary['low_suspicion']} tracks")

    # Validate each candidate and track changes
    validation_results = []
    updated_segments = file_data['segments'].copy()

    for i, candidate in enumerate(candidates, 1):
        logger.info(f"\n[{i}/{len(candidates)}] Validating: {candidate['track']}")

        result = validate_segment_with_extended_audio(audio_file_path, candidate)
        validation_results.append(result)

        # Update scan log entry based on validation result
        timestamp = result['timestamp']
        original_track = result['original_track']
        validation_status = result['validation_status']

        if timestamp in updated_segments:
            if validation_status == 'LIKELY_FALSE_POSITIVE':
                # Update status to indicate false positive
                updated_segments[timestamp]['status'] = 'FOUND_FALSE_POSITIVE'
                # Keep original track name but mark as false positive
                updated_segments[timestamp]['track'] = original_track

                # If we have a suggested alternative, show it
                if 'suggested_track' in result:
                    logger.info(f"      > Suggested alternative: {result['suggested_track']}")

            elif validation_status == 'NO_EXTENDED_RECOGNITION':
                # Mark as false positive - extended segments couldn't recognize anything
                updated_segments[timestamp]['status'] = 'FOUND_FALSE_POSITIVE'
                updated_segments[timestamp]['track'] = original_track

            elif validation_status == 'CONFIRMED_VALID':
                # Mark as validated and confirmed
                updated_segments[timestamp]['status'] = 'FOUND_VALIDATED'
                updated_segments[timestamp]['track'] = original_track

            elif validation_status == 'UNCERTAIN':
                # Mark as suspicious but uncertain
                updated_segments[timestamp]['status'] = 'FOUND_UNCERTAIN'
                updated_segments[timestamp]['track'] = original_track

    # Generate summary report
    logger.info("\n[REPORT] Validation Results Summary:")

    confirmed_false = [r for r in validation_results if r['validation_status'] == 'LIKELY_FALSE_POSITIVE']
    no_recognition = [r for r in validation_results if r['validation_status'] == 'NO_EXTENDED_RECOGNITION']
    confirmed_valid = [r for r in validation_results if r['validation_status'] == 'CONFIRMED_VALID']
    uncertain = [r for r in validation_results if r['validation_status'] == 'UNCERTAIN']

    total_false_positives = len(confirmed_false) + len(no_recognition)

    logger.info(f"  FALSE POSITIVES: {total_false_positives} tracks")
    for result in confirmed_false + no_recognition:
        logger.info(f"    {result['timestamp']}: {result['original_track']}")
        if 'suggested_track' in result:
            logger.info(f"      > Suggested: {result['suggested_track']}")

    logger.info(f"  CONFIRMED VALID: {len(confirmed_valid)} tracks")
    for result in confirmed_valid:
        logger.info(f"    {result['timestamp']}: {result['original_track']}")

    logger.info(f"  UNCERTAIN: {len(uncertain)} tracks")
    for result in uncertain:
        logger.info(f"    {result['timestamp']}: {result['original_track']}")

    # Write updated result file with validation statuses
    logger.info(f"\n[UPDATE] Updating scan log with validation results...")
    write_result_file(result_file_path, file_data['header'], updated_segments)

    logger.info(f"[DONE] Validation complete for {os.path.basename(audio_file_path)}!")
    logger.info(f"  > Updated {len(validation_results)} entries in scan log")
    logger.info(f"  > {total_false_positives} false positives marked, {len(confirmed_valid)} confirmed valid")


def print_usage() -> None:
    """
    Displays script usage instructions.
    """
    print("""
[MUSIC] Shazam Tool [MUSIC]

Usage: python shazam.py [command1] [command2] ... [file/url] [options]

Commands:
    [SCAN] scan                       Scan downloads directory and recognize all MP3
    [RESCAN] rescan                   Rescan only failed segments (timeout/error)
    [VALIDATE] validate [audio_file]  Validate potential false positives with extended segments
    [DOWN] download <url>            Download and process audio from YouTube or SoundCloud
    [TARGET] recognize <file_or_url>    Recognize specific audio file or download and recognize from URL

Chainable Commands (NEW!):
    python shazam.py scan rescan validate            # Scan -> Rescan -> Validate all
    python shazam.py recognize file.mp3 rescan validate  # Recognize -> Rescan -> Validate
    python shazam.py scan validate                   # Scan -> Validate all
    python shazam.py rescan validate                 # Rescan -> Validate all

Options:
    --debug                       Enable debug mode with detailed logging
    --threshold <n>               Max occurrences for validation candidates (default: 3)

Single Command Examples:
    python shazam.py scan
    python shazam.py scan --debug
    python shazam.py validate
    python shazam.py validate --threshold 1
    python shazam.py validate "downloads/mix.mp3"
    python shazam.py validate "path/to/audio.mp3" --threshold 2 --debug
    python shazam.py download https://www.youtube.com/watch?v=...
    python shazam.py download https://soundcloud.com/... --debug
    python shazam.py recognize path/to/audio.mp3
    python shazam.py recognize https://soundcloud.com/...
    """)


def main() -> None:
    parser = argparse.ArgumentParser(description='Shazam Tool', add_help=False)
    parser.add_argument('commands', nargs='*', help='Commands: scan, download, recognize, rescan, validate')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with detailed logging')
    parser.add_argument('--threshold', type=int, default=3, help='Max occurrences for validation candidates')

    # Parse known args to avoid error with unrecognized args
    args, unknown = parser.parse_known_args()

    if not args.commands:
        print_usage()
        sys.exit(1)

    # Set up logging based on debug flag
    setup_logging(args.debug)

    # Parse commands and detect file/URL
    commands = []
    url_or_file = None

    # Process all arguments to separate commands from file/URL
    all_args = args.commands + unknown
    valid_commands = ['scan', 'download', 'recognize', 'rescan', 'validate']

    for arg in all_args:
        if arg in valid_commands:
            commands.append(arg)
        elif not url_or_file:
            # First non-command argument is likely the file/URL
            url_or_file = arg

    if not commands:
        print_usage()
        sys.exit(1)

    # For legacy compatibility, if only one argument and it's not a command, treat as old format
    if len(args.commands) == 1 and args.commands[0] not in valid_commands:
        print_usage()
        sys.exit(1)
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)

    # Generate default output filename
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    logger.info(f"[CHAIN] Executing command chain: {' -> '.join(commands)}")

    # Execute commands in sequence
    for idx, command in enumerate(commands, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"[{idx}/{len(commands)}] Executing: {command}")
        logger.info(f"{'='*60}")

        # Execute individual command
        execute_single_command(command, url_or_file, args, output_filename)

        logger.info(f"[{idx}/{len(commands)}] Completed: {command}")

    logger.info(f"\n[CHAIN] All commands completed successfully: {' -> '.join(commands)}")


def execute_single_command(command: str, url_or_file: str, args, output_filename: str) -> None:
    """Execute a single command with the given parameters."""

    if command == 'download':
        if not url_or_file:
            logger.error("Missing URL. Usage: python shazam.py download <url> [--debug]")
            sys.exit(1)

        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write("===== Download Results ======\n\n")
        except OSError as e:
            logger.error(f"Error creating output file {output_filename}: {e}")
            sys.exit(1)

        download_from_url(url_or_file)
        process_downloads()

    elif command in ['scan', 'scan-downloads']:
        logger.info(f"Scanning '{DOWNLOADS_DIR}' directory for MP3 files...")
        process_downloads()
        return

    elif command == 'rescan':
        logger.info(f"Rescanning failed segments in '{DOWNLOADS_DIR}' directory...")
        process_downloads(rescan_mode=True)
        return

    elif command == 'validate':
        if url_or_file:
            # Single file validation
            audio_file_path = url_or_file

            # Handle local file path
            if not os.path.exists(audio_file_path):
                logger.error(f"Audio file not found: {audio_file_path}")
                sys.exit(1)

            # Find corresponding result file
            audio_basename = os.path.splitext(os.path.basename(audio_file_path))[0]
            result_file_path = os.path.join("recognised-lists", f"{audio_basename}.txt")

            if not os.path.exists(result_file_path):
                logger.error(f"Result file not found: {result_file_path}")
                logger.error("Please run a scan first to generate results before validation")
                sys.exit(1)

            # Validate single file
            validate_single_file(audio_file_path, result_file_path, args.threshold)

        else:
            # Validate all files in downloads directory
            ensure_directory_exists(DOWNLOADS_DIR)
            ensure_directory_exists("recognised-lists")

            mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
            if not mp3_files:
                logger.error(f"No MP3 files found in '{DOWNLOADS_DIR}' directory.")
                sys.exit(1)

            # Find MP3 files that have corresponding result files
            valid_files = []
            for mp3_file in mp3_files:
                audio_basename = os.path.splitext(mp3_file)[0]
                result_file_path = os.path.join("recognised-lists", f"{audio_basename}.txt")
                if os.path.exists(result_file_path):
                    audio_file_path = os.path.join(DOWNLOADS_DIR, mp3_file)
                    valid_files.append((audio_file_path, result_file_path))

            if not valid_files:
                logger.error("No result files found for MP3 files in downloads directory.")
                logger.error("Please run a scan first to generate results before validation")
                sys.exit(1)

            logger.info(f"[VALIDATE] Starting bulk validation of {len(valid_files)} file(s)")
            logger.info(f"[THRESHOLD] Validation threshold: <={args.threshold} occurrences")

            # Validate each file
            for idx, (audio_file_path, result_file_path) in enumerate(valid_files, 1):
                logger.info(f"\n{'='*60}")
                logger.info(f"[{idx}/{len(valid_files)}] Validating: {os.path.basename(audio_file_path)}")
                logger.info(f"{'='*60}")

                validate_single_file(audio_file_path, result_file_path, args.threshold)

            logger.info(f"\n[DONE] Bulk validation complete! Processed {len(valid_files)} file(s)")

        return

    elif command == 'recognize':
        if not url_or_file:
            logger.error("Missing file path. Usage: python shazam.py recognize <file_path> [--debug]")
            sys.exit(1)

        audio_file = url_or_file

        # Check if the input is a URL
        if audio_file.startswith('http://') or audio_file.startswith('https://'):
            logger.info(f"URL detected: {audio_file}")
            # Download from URL first
            download_from_url(audio_file)
            # Find the downloaded file in the downloads directory
            mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
            if not mp3_files:
                logger.error(f"No MP3 files found in '{DOWNLOADS_DIR}' directory after download.")
                sys.exit(1)
            # Process only the most recently downloaded file
            # (assuming it's the one we just downloaded)
            latest_file = max([os.path.join(DOWNLOADS_DIR, f) for f in mp3_files],
                              key=os.path.getmtime)

            # Create output filename based on downloaded MP3 name
            mp3_base_name = os.path.splitext(os.path.basename(latest_file))[0]
            output_filename = os.path.join(output_dir, f"{mp3_base_name}.txt")

            process_audio_file(latest_file, output_filename, 1, 1)
            logger.info(f"\nResults saved to {output_filename}")
            return

        # Handle local file
        if not os.path.exists(audio_file):
            logger.error(f"Error: File '{audio_file}' not found.")
            sys.exit(1)

        # Create output filename based on MP3 name (without timestamp for rescan analysis)
        mp3_base_name = os.path.splitext(os.path.basename(audio_file))[0]
        output_filename = os.path.join(output_dir, f"{mp3_base_name}.txt")

        # Since we're processing a single file, pass file_index=1 and total_files=1
        process_audio_file(audio_file, output_filename, 1, 1)
        logger.info(f"\nResults saved to {output_filename}")
        return

    else:
        logger.error(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
