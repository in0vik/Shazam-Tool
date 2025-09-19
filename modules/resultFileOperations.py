import os

from modules.core.constants import SEGMENT_LENGTH, SegmentStatus
from modules.core.helper import parse_timestamp
from modules.core.logger import logger


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
                        if len(parts) >= 3 and parts[1] in [SegmentStatus.FOUND.value, SegmentStatus.FOUND_VALIDATED.value, SegmentStatus.FOUND_FALSE_POSITIVE.value, SegmentStatus.FOUND_UNCERTAIN.value]:
                            status = parts[1]  # FOUND, FOUND_VALIDATED, etc.
                        else:
                            status = parts[1]  # NOT_FOUND, TIMEOUT, ERROR

                        # Calculate segment number from timestamp
                        try:
                            timestamp_seconds = parse_timestamp(timestamp_str)
                            segment_num = int(timestamp_seconds / (SEGMENT_LENGTH / 1000)) + 1
                            max_segment = max(max_segment, segment_num)

                            # Mark segments that need rescanning (TIMEOUT and ERROR for rescan mode)
                            if status in [SegmentStatus.TIMEOUT.value, SegmentStatus.ERROR.value]:
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
                        if len(parts) >= 3 and parts[1] in [SegmentStatus.FOUND.value, SegmentStatus.FOUND_VALIDATED.value, SegmentStatus.FOUND_FALSE_POSITIVE.value, SegmentStatus.FOUND_UNCERTAIN.value, SegmentStatus.FOUND_MERGED.value]:
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
                segments[timestamp] = {"status": SegmentStatus.FOUND.value, "track": track_info["track"]}

        # Fill in missing track data for segments that don't have tracks
        for timestamp, segment in segments.items():
            if not segment["track"]:
                if segment["status"] == SegmentStatus.FOUND.value:
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
        if status in [SegmentStatus.FOUND.value, SegmentStatus.FOUND_VALIDATED.value, SegmentStatus.FOUND_FALSE_POSITIVE.value, SegmentStatus.FOUND_UNCERTAIN.value, SegmentStatus.FOUND_MERGED.value] and track:
            scan_log.append(f"{timestamp} - {status} - {track}")
        else:
            scan_log.append(f"{timestamp} - {status}")

        # Add to tracklist only if found (but not false positive) and not already seen
        if status in [SegmentStatus.FOUND.value, SegmentStatus.FOUND_VALIDATED.value, SegmentStatus.FOUND_MERGED.value] and track not in seen_tracks:
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
