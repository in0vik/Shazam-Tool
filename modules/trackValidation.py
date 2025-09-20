import asyncio
import os
import re
from difflib import SequenceMatcher
from typing import List, Tuple

from modules.core.constants import SegmentStatus
from modules.core.helper import parse_timestamp
from modules.core.logger import logger
from modules.resultFileOperations import read_result_file, write_result_file, generate_tracklist_and_log
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

                # Check for any FOUND variant (FOUND, VALIDATION_VALIDATED, VALIDATION_FALSE_POSITIVE, VALIDATION_UNCERTAIN)
                if in_scan_log and (" - FOUND" in line):
                    parts_split = line.split(" - ")

                    if len(parts_split) >= 3:
                        timestamp = parts_split[0]
                        status = parts_split[1]
                        track_name = " - ".join(parts_split[2:])

                        # Only count legitimate tracks (exclude false positives from count)
                        if status in [SegmentStatus.FOUND.value, SegmentStatus.VALIDATION_VALIDATED.value]:
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
        # Still proceed to Phase 2 for wrong version detection
        logger.info(f"[DONE] Phase 1 validation complete for {os.path.basename(audio_file_path)}!")
        logger.info(f"  > No false positive candidates found")

        # Phase 2: Wrong version detection
        validate_wrong_versions(audio_file_path, result_file_path)
        return

    logger.info(f"[CANDIDATES] Found {len(candidates)} validation candidates:")
    logger.info(f"  HIGH suspicion (1x): {summary['high_suspicion']} tracks")
    logger.info(f"  MEDIUM suspicion (2x): {summary['medium_suspicion']} tracks")
    logger.info(f"  LOW suspicion (3x): {summary['low_suspicion']} tracks")

    # Validate each candidate and track changes
    validation_results = []
    updated_segments = file_data['segments'].copy()

    for i, candidate in enumerate(candidates, 1):
        logger.info(f"[{i}/{len(candidates)}] Validating: {candidate['track']}")

        result = validate_segment_with_extended_audio(audio_file_path, candidate)
        validation_results.append(result)

        # Update scan log entry based on validation result
        timestamp = result['timestamp']
        original_track = result['original_track']
        validation_status = result['validation_status']

        if timestamp in updated_segments:
            if validation_status == 'LIKELY_FALSE_POSITIVE':
                # Update status to indicate false positive
                updated_segments[timestamp]['status'] = SegmentStatus.VALIDATION_FALSE_POSITIVE.value
                # Keep original track name but mark as false positive
                updated_segments[timestamp]['track'] = original_track

                # If we have a suggested alternative, show it
                if 'suggested_track' in result:
                    logger.info(f"      > Suggested alternative: {result['suggested_track']}")

            elif validation_status == 'NO_EXTENDED_RECOGNITION':
                # Mark as false positive - extended segments couldn't recognize anything
                updated_segments[timestamp]['status'] = SegmentStatus.VALIDATION_FALSE_POSITIVE.value
                updated_segments[timestamp]['track'] = original_track

            elif validation_status == 'CONFIRMED_VALID':
                # Mark as validated and confirmed
                updated_segments[timestamp]['status'] = SegmentStatus.VALIDATION_VALIDATED.value
                updated_segments[timestamp]['track'] = original_track

            elif validation_status == 'UNCERTAIN':
                # Mark as suspicious but uncertain
                updated_segments[timestamp]['status'] = SegmentStatus.VALIDATION_UNCERTAIN.value
                updated_segments[timestamp]['track'] = original_track

    # Generate summary report
    logger.info("[REPORT] Validation Results Summary:")

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
    logger.info(f"[UPDATE] Updating scan log with validation results...")
    write_result_file(result_file_path, file_data['header'], updated_segments)

    logger.info(f"[DONE] Phase 1 validation complete for {os.path.basename(audio_file_path)}!")
    logger.info(f"  > Updated {len(validation_results)} entries in scan log")
    logger.info(f"  > {total_false_positives} false positives marked, {len(confirmed_valid)} confirmed valid")

    # Phase 2: Wrong version detection
    validate_wrong_versions(audio_file_path, result_file_path)


def get_primary_artist(artist: str) -> str:
    """
    Extract the primary/first artist from collaborations by converting all delimiters to commas
    and taking the first artist.

    Args:
        artist: Full artist string potentially containing collaborations

    Returns:
        Primary artist name (first artist in the collaboration)
    """
    # Replace all collaboration delimiters with commas
    delimiters = ['feat.', 'feat', 'featuring', ' & ', ' and ', ' with ']
    normalized = artist.lower()

    for delimiter in delimiters:
        normalized = normalized.replace(delimiter, ',')

    # Split by comma and take the first artist
    artists = [a.strip() for a in normalized.split(',')]
    return artists[0] if artists else normalized.strip()


def normalize_artist(artist: str) -> str:
    """
    Full artist normalization for fuzzy comparison.
    Standardizes collaboration delimiters for better matching.

    Args:
        artist: Full artist string

    Returns:
        Normalized artist string with standardized delimiters
    """
    # Replace various collaboration delimiters with standardized separator
    delimiters = ['feat.', 'feat', 'featuring', ' and ', ' with ']
    normalized = artist.lower()
    for delimiter in delimiters:
        normalized = normalized.replace(delimiter, ' & ')
    return normalized.strip()


def normalize_track_title(title: str) -> str:
    """
    Normalize track title by removing version indicators and standardizing format.

    Args:
        title: Original track title

    Returns:
        Normalized title with version indicators removed
    """
    # Remove parentheses and brackets with content
    normalized = re.sub(r'\([^)]*\)', '', title)
    normalized = re.sub(r'\[[^\]]*\]', '', normalized)

    # Remove common version suffixes (case insensitive)
    suffixes = ['VIP', 'Live', 'Bootleg', 'Promo', 'Edit', 'Mix', 'Version', 'Remix']
    for suffix in suffixes:
        normalized = re.sub(f'\\b{suffix}\\b', '', normalized, flags=re.IGNORECASE)

    # Clean up extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def calculate_fuzzy_similarity(str1: str, str2: str) -> float:
    """
    Calculate similarity ratio between two strings using difflib.

    Args:
        str1: First string to compare
        str2: Second string to compare

    Returns:
        Similarity ratio between 0.0 and 1.0 (1.0 = identical)
    """
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def detect_wrong_version_pairs(tracklist_data: List[dict],
                             primary_artist_threshold: float = 0.85,
                             full_artist_threshold: float = 0.85,
                             track_title_threshold: float = 0.85,
                             combined_threshold: float = 0.85) -> List[Tuple[int, int, str, float]]:
    """
    Detect pairs of tracks that are likely different versions of the same song.

    Uses multiple detection methods:
    1. Primary artist exact match + track title fuzzy match
    2. Full artist fuzzy match + track title fuzzy match
    3. Combined "artist - track" string fuzzy match

    Args:
        tracklist_data: List of track dictionaries with 'artist', 'title', 'timestamp'
        primary_artist_threshold: Threshold for track title similarity when primary artist matches
        full_artist_threshold: Threshold for artist similarity in full fuzzy matching
        track_title_threshold: Threshold for track title similarity
        combined_threshold: Threshold for combined string similarity

    Returns:
        List of tuples (index1, index2, detection_method, similarity_score)
    """
    pairs = []

    logger.debug(f"Starting wrong version pair detection for {len(tracklist_data)} tracks")
    logger.debug(f"Thresholds - Primary artist: {primary_artist_threshold}, Full artist: {full_artist_threshold}, Track: {track_title_threshold}, Combined: {combined_threshold}")

    # Only compare adjacent pairs (1+2, 2+3, 3+4...)
    for i in range(len(tracklist_data) - 1):
        j = i + 1
        track1, track2 = tracklist_data[i], tracklist_data[j]

        # Skip if tracks are identical
        if track1['artist'] == track2['artist'] and track1['title'] == track2['title']:
            continue

        logger.debug(f"Comparing adjacent tracks {i+1} and {j+1}:")
        logger.debug(f"  Track {i+1}: {track1['artist']} - {track1['title']}")
        logger.debug(f"  Track {j+1}: {track2['artist']} - {track2['title']}")

        # Method 1: Primary artist exact + track fuzzy
        primary1 = get_primary_artist(track1['artist'])
        primary2 = get_primary_artist(track2['artist'])
        title1_norm = normalize_track_title(track1['title'])
        title2_norm = normalize_track_title(track2['title'])

        logger.debug(f"  Primary artists: '{primary1}' vs '{primary2}'")
        logger.debug(f"  Normalized titles: '{title1_norm}' vs '{title2_norm}'")

        if primary1 == primary2:
            title_similarity = calculate_fuzzy_similarity(title1_norm, title2_norm)
            logger.debug(f"  Primary artist match! Title similarity: {title_similarity:.3f}")
            if title_similarity >= track_title_threshold:
                logger.info(f"PAIR DETECTED [Method 1]: Tracks {i+1} and {j+1} (similarity: {title_similarity:.3f})")
                pairs.append((i, j, "primary_artist_exact+track_fuzzy", title_similarity))
                continue

        # Method 2: Artist fuzzy + track fuzzy
        artist1_norm = normalize_artist(track1['artist'])
        artist2_norm = normalize_artist(track2['artist'])
        artist_similarity = calculate_fuzzy_similarity(artist1_norm, artist2_norm)
        title_similarity = calculate_fuzzy_similarity(title1_norm, title2_norm)

        logger.debug(f"  Normalized artists: '{artist1_norm}' vs '{artist2_norm}'")
        logger.debug(f"  Artist similarity: {artist_similarity:.3f}, Title similarity: {title_similarity:.3f}")

        if (artist_similarity >= full_artist_threshold and
            title_similarity >= track_title_threshold):
            avg_similarity = (artist_similarity + title_similarity) / 2
            logger.info(f"PAIR DETECTED [Method 2]: Tracks {i+1} and {j+1} (avg similarity: {avg_similarity:.3f})")
            pairs.append((i, j, "artist_fuzzy+track_fuzzy", avg_similarity))
            continue

        # Method 3: Combined string fuzzy
        combined1 = f"{artist1_norm} - {title1_norm}"
        combined2 = f"{artist2_norm} - {title2_norm}"
        combined_similarity = calculate_fuzzy_similarity(combined1, combined2)

        logger.debug(f"  Combined strings: '{combined1}' vs '{combined2}'")
        logger.debug(f"  Combined similarity: {combined_similarity:.3f}")

        if combined_similarity >= combined_threshold:
            logger.info(f"PAIR DETECTED [Method 3]: Tracks {i+1} and {j+1} (combined similarity: {combined_similarity:.3f})")
            pairs.append((i, j, "combined_fuzzy", combined_similarity))

    logger.info(f"Wrong version pair detection complete. Found {len(pairs)} pairs.")
    return pairs


async def resolve_wrong_version_with_shazam(audio_file_path: str, start_timestamp: str, end_timestamp: str, pair_tracks: list) -> dict:
    """
    Creates an extended audio segment covering the wrong version pair range and uses Shazam to identify the correct version.

    Args:
        audio_file_path: Path to the original audio file
        start_timestamp: Start timestamp of the segment range
        end_timestamp: End timestamp of the segment range
        pair_tracks: List of track names in the pair for comparison

    Returns:
        Dict with 'status', 'track', and 'confidence' keys
    """
    logger.debug(f"Creating extended segment from {start_timestamp} to {end_timestamp}")

    try:
        # Create extended segment for the entire range
        extended_segment_path = create_extended_segment(
            audio_file_path,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp
        )

        if not extended_segment_path or not os.path.exists(extended_segment_path):
            logger.error("Failed to create extended segment")
            return {"status": "ERROR", "track": "", "confidence": 0.0}

        logger.debug(f"Extended segment created: {extended_segment_path}")

        # Use Shazam to recognize the correct version
        result = await recognize_track(extended_segment_path)

        # Clean up temporary file
        try:
            os.remove(extended_segment_path)
        except:
            pass

        if result['status'] == 'FOUND':
            detected_track = result['track']
            logger.info(f"Shazam identified: {detected_track}")

            # Calculate confidence based on similarity to pair tracks
            confidence = 0.0
            for pair_track in pair_tracks:
                similarity = calculate_fuzzy_similarity(detected_track.lower(), pair_track.lower())
                confidence = max(confidence, similarity)

            return {
                "status": "FOUND",
                "track": detected_track,
                "confidence": confidence
            }
        else:
            logger.debug(f"Shazam recognition failed with status: {result['status']}")
            return {"status": result['status'], "track": "", "confidence": 0.0}

    except Exception as e:
        logger.error(f"Error in Shazam resolution: {e}")
        return {"status": "ERROR", "track": "", "confidence": 0.0}


def validate_wrong_versions(audio_file_path: str, result_file_path: str) -> None:
    """
    Phase 2 validation: Detect wrong version pairs in the tracklist and resolve them using Shazam.
    This runs after the normal false positive validation.

    Args:
        audio_file_path: Path to the audio file
        result_file_path: Path to the corresponding result file
    """
    logger.info(f"[PHASE 2] Starting wrong version detection for {os.path.basename(audio_file_path)}")

    # Read existing result file
    file_data = read_result_file(result_file_path)

    # Generate tracklist data for analysis
    tracklist, _ = generate_tracklist_and_log(file_data['segments'])

    # Extract tracklist data in the format needed for detection
    tracklist_data = []
    for track_line in tracklist:
        # Parse format: "  1 - 00:04:00 - Metrik - Want My Love (feat. Elisabeth Troy)"
        parts = track_line.split(' - ', 3)
        if len(parts) >= 4:
            timestamp = parts[1]
            artist = parts[2]
            title = parts[3]
            tracklist_data.append({
                "timestamp": timestamp,
                "artist": artist,
                "title": title
            })

    if len(tracklist_data) < 2:
        logger.info("[PHASE 2] Not enough tracks for wrong version detection")
        return

    # Detect wrong version pairs
    detected_pairs = detect_wrong_version_pairs(tracklist_data)

    if not detected_pairs:
        logger.info("[PHASE 2] No wrong version pairs detected")
        return

    logger.info(f"[PHASE 2] Found {len(detected_pairs)} wrong version pairs:")
    for idx1, idx2, method, similarity in detected_pairs:
        track1 = tracklist_data[idx1]
        track2 = tracklist_data[idx2]
        logger.info(f"  Pair {idx1+1}-{idx2+1}: {track1['artist']} - {track1['title']} <-> {track2['artist']} - {track2['title']} (method: {method}, similarity: {similarity:.3f})")

    # Process each pair with Shazam resolution
    updated_segments = file_data['segments'].copy()

    for idx1, idx2, method, similarity in detected_pairs:
        track1 = tracklist_data[idx1]
        track2 = tracklist_data[idx2]

        logger.info(f"[RESOLVE] Processing pair: {track1['artist']} - {track1['title']} <-> {track2['artist']} - {track2['title']}")

        # Find all segments related to both tracks in the scan log
        related_segments = []
        track1_full = f"{track1['artist']} - {track1['title']}"
        track2_full = f"{track2['artist']} - {track2['title']}"

        for timestamp, segment_data in file_data['segments'].items():
            if (segment_data.get('track') == track1_full or
                segment_data.get('track') == track2_full) and \
               segment_data.get('status') in ['FOUND', 'VALIDATION_VALIDATED']:
                related_segments.append(timestamp)

        if not related_segments:
            logger.warning(f"No related segments found for pair")
            continue

        # Sort timestamps to find the range
        related_segments.sort(key=parse_timestamp)
        start_timestamp = related_segments[0]
        end_timestamp = related_segments[-1]

        logger.info(f"[RESOLVE] Analyzing segment range {start_timestamp} to {end_timestamp}")

        # Use async wrapper to call Shazam resolution
        async def resolve_pair():
            return await resolve_wrong_version_with_shazam(
                audio_file_path,
                start_timestamp,
                end_timestamp,
                [track1_full, track2_full]
            )

        resolution = asyncio.run(resolve_pair())

        if resolution['status'] == 'FOUND':
            correct_track = resolution['track']
            confidence = resolution['confidence']

            logger.info(f"[RESOLVE] Correct version identified: {correct_track} (confidence: {confidence:.3f})")

            # Update segments: mark wrong versions and keep correct one
            for timestamp in related_segments:
                segment_data = updated_segments[timestamp]
                current_track = segment_data.get('track', '')

                if current_track == correct_track:
                    # This is the correct version - mark as validated
                    segment_data['status'] = SegmentStatus.VALIDATION_VALIDATED.value
                    logger.debug(f"  {timestamp}: Keeping correct version - {current_track}")
                else:
                    # This is a wrong version - mark as wrong version
                    segment_data['status'] = SegmentStatus.VALIDATION_WRONG_VERSION.value
                    logger.debug(f"  {timestamp}: Marking wrong version - {current_track}")
        else:
            logger.warning(f"[RESOLVE] Failed to resolve pair with Shazam: {resolution['status']}")

    # Write updated result file
    write_result_file(result_file_path, file_data['header'], updated_segments)

    logger.info("[PHASE 2] Wrong version detection and resolution complete")
