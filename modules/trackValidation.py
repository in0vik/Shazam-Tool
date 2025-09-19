import asyncio
import os

from modules.core.logger import logger
from modules.resultFileOperations import read_result_file, write_result_file
from modules.shazam.shazamApi import recognize_track
from modules.audio.audioSegmentation import create_extended_segment


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
            result = asyncio.run(recognize_track(extended_file))

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
