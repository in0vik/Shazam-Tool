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

    try:
        with open(result_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if " - " in line and not line.startswith("====="):
                    parts = line.split(" - ", 1)
                    if len(parts) >= 2:
                        timestamp_str = parts[0]
                        status = parts[1]

                        # Calculate segment number from timestamp
                        timestamp_seconds = parse_timestamp(timestamp_str)
                        segment_num = int(timestamp_seconds / (SEGMENT_LENGTH / 1000)) + 1
                        max_segment = max(max_segment, segment_num)

                        # Mark segments that need rescanning (TIMEOUT and ERROR for rescan mode)
                        if status in ["TIMEOUT", "ERROR"]:
                            rescan_segments.append(segment_num)

    except Exception as e:
        logger.debug(f"Error analyzing result file {result_file_path}: {e}")
        return {"rescan_segments": [], "max_segment": 0}

    return {"rescan_segments": rescan_segments, "max_segment": max_segment}


def read_result_file(result_file_path: str) -> dict:
    """
    Reads existing result file and returns structured data.
    Parses the new format with separate Tracklist and Scan Log sections.
    """
    if not os.path.exists(result_file_path):
        return {"header": "", "segments": {}}

    segments = {}
    header = ""
    current_section = "none"
    track_data = {}  # timestamp -> track_name

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
            elif " - " in line and not line.startswith("====="):
                parts = line.split(" - ", 1)
                if len(parts) >= 2:
                    timestamp_str = parts[0]

                    if current_section == "tracklist":
                        # Track info: "timestamp - artist - title"
                        track_name = parts[1]
                        track_data[timestamp_str] = track_name
                    elif current_section == "scan_log":
                        # Status info: "timestamp - status"
                        status = parts[1]
                        # Initialize segment with status
                        if timestamp_str not in segments:
                            segments[timestamp_str] = {"status": status, "track": ""}
                        else:
                            segments[timestamp_str]["status"] = status

        # Merge track data with segments
        for timestamp, track_name in track_data.items():
            if timestamp in segments:
                segments[timestamp]["track"] = track_name
            else:
                # Track found but no scan log entry - assume FOUND status
                segments[timestamp] = {"status": "FOUND", "track": track_name}

        # Fill in missing track data for segments that don't have tracks
        for timestamp, segment in segments.items():
            if not segment["track"]:
                if segment["status"] == "FOUND":
                    segment["track"] = "Unknown Track"
                else:
                    segment["track"] = segment["status"]

    except Exception as e:
        logger.debug(f"Error reading result file {result_file_path}: {e}")

    return {"header": header, "segments": segments}


def generate_tracklist_and_log(segments: dict) -> tuple:
    """
    Generates condensed tracklist and scan log from segment data.
    """
    tracklist = []
    scan_log = []
    seen_tracks = set()

    # Sort segments by timestamp
    sorted_timestamps = sorted(segments.keys(), key=lambda x: parse_timestamp(x))

    for timestamp in sorted_timestamps:
        data = segments[timestamp]
        status = data["status"]
        track = data["track"]

        # Add to scan log with proper status
        scan_log.append(f"{timestamp} - {status}")

        # Add to tracklist only if found and not already seen
        if status == "FOUND" and track not in seen_tracks:
            tracklist.append(f"{timestamp} - {track}")
            seen_tracks.add(track)

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


async def get_name(file_path: str, max_retries: int = 3, timeout: int = 40) -> str:
    """
    Uses Shazam to recognize the song with retry logic, timeout, and error handling.
    Returns either 'Artist - Track Title', 'TIMEOUT', 'ERROR', or 'NOT_FOUND' based on failure type.
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
                return "NOT_FOUND"

            title = data['track']['title']
            subtitle = data['track']['subtitle']
            result = f"{subtitle} - {title}"
            logger.debug(f"Recognition successful in {elapsed:.2f}s: {result}")
            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(f"Recognition attempt {attempt+1} timed out after {elapsed:.2f}s")
            if attempt < max_retries - 1:
                logger.debug(f"Retrying with increased timeout...")
                await asyncio.sleep(3)  # Longer delay after timeout
                continue
            logger.warning("Recognition failed after all attempts due to timeout")
            return "TIMEOUT"

        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"Error in recognition attempt {attempt+1} after {elapsed:.2f}s: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            logger.warning("Recognition failed after all attempts due to exception")
            return "ERROR"


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
                track_name = asyncio.run(get_name(segment_path))
                # get_name() now returns specific status strings
                if track_name in ["TIMEOUT", "ERROR", "NOT_FOUND"]:
                    segment_status = track_name
                else:
                    # If it's not a status string, it's a successful recognition
                    segment_status = "FOUND"
            except asyncio.TimeoutError:
                track_name = "TIMEOUT"
                segment_status = "TIMEOUT"
            except Exception as seg_error:
                logger.debug(f"Segment {idx} error: {seg_error}")
                track_name = "ERROR"
                segment_status = "ERROR"

            # Build the progress output with timestamp and status
            progress_str = f"[{idx}/{total_segments}] {timestamp}: {track_name}"
            logger.info(progress_str)

            # Update file_data structure
            file_data["segments"][timestamp] = {"status": segment_status, "track": track_name}

            if track_name not in ["NOT_FOUND", "TIMEOUT", "ERROR"] and track_name not in unique_tracks:
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


def print_usage() -> None:
    """
    Displays script usage instructions.
    """
    print("""
[MUSIC] Shazam Tool [MUSIC]

Usage: python shazam.py [command] [options]

Commands:
    [SCAN] scan                       Scan downloads directory and recognize all MP3
    [RESCAN] rescan                   Rescan only failed segments (timeout/error)
    [DOWN] download <url>            Download and process audio from YouTube or SoundCloud
    [TARGET] recognize <file_or_url>    Recognize specific audio file or download and recognize from URL

Options:
    --debug                       Enable debug mode with detailed logging

Examples:
    python shazam.py scan
    python shazam.py scan --debug
    python shazam.py download https://www.youtube.com/watch?v=...
    python shazam.py download https://soundcloud.com/... --debug
    python shazam.py recognize path/to/audio.mp3
    python shazam.py recognize https://soundcloud.com/... 
    """)


def main() -> None:
    parser = argparse.ArgumentParser(description='Shazam Tool', add_help=False)
    parser.add_argument('command', nargs='?', help='scan, download, or recognize')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with detailed logging')
    parser.add_argument('url_or_file', nargs='?', help='URL or file path, depending on command')

    # Parse known args to avoid error with unrecognized args
    args, unknown = parser.parse_known_args()

    if not args.command:
        print_usage()
        sys.exit(1)

    # Set up logging based on debug flag
    setup_logging(args.debug)

    command = args.command
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)

    # Generate default output filename
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    # Special handling for download and recognize commands to support unquoted URLs
    if command == 'download' or command == 'recognize':
        # Determine the URL/file by reconstructing from sys.argv
        # Skip 'python', 'shazam.py', 'command', and potentially '--debug'
        start_idx = 2  # Skip program name and command
        if '--debug' in sys.argv:
            # If --debug is immediately after command, adjust accordingly
            if sys.argv.index('--debug') == start_idx:
                start_idx += 1

        # If we still have arguments left, reconstruct them
        if len(sys.argv) > start_idx:
            # Join all remaining arguments to handle spaces in URLs or file paths
            url_or_file = ' '.join(sys.argv[start_idx:])
        else:
            url_or_file = None
    else:
        # For other commands, use argparse result
        url_or_file = args.url_or_file

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
