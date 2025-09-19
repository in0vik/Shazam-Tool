import os
import sys
from datetime import datetime
import argparse

from modules.core.constants import DOWNLOADS_DIR, RESULTS_DIR
from modules.core.helper import ensure_directory_exists
from modules.core.logger import logger, setup_logging
from modules.download import download_from_url
from modules.trackRecognition import process_audio_file, process_downloads
from modules.trackValidation import validate_single_file


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
    ensure_directory_exists(RESULTS_DIR)

    # Generate default output filename
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(RESULTS_DIR, f"songs-{timestamp}.txt")

    logger.info(f"[CHAIN] Executing command chain: {' -> '.join(commands)}")

    # Execute commands in sequence
    for idx, command in enumerate(commands, 1):
        logger.info(f"\n{'=' * 60}")
        logger.info(f"[{idx}/{len(commands)}] Executing: {command}")
        logger.info(f"{'=' * 60}")

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

    elif command == 'rescan':
        logger.info(f"Rescanning failed segments in '{DOWNLOADS_DIR}' directory...")
        process_downloads(rescan_mode=True)

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
                logger.info(f"\n{'=' * 60}")
                logger.info(f"[{idx}/{len(valid_files)}] Validating: {os.path.basename(audio_file_path)}")
                logger.info(f"{'=' * 60}")

                validate_single_file(audio_file_path, result_file_path, args.threshold)

            logger.info(f"\n[DONE] Bulk validation complete! Processed {len(valid_files)} file(s)")


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
            output_filename = os.path.join(RESULTS_DIR, f"{mp3_base_name}.txt")

            process_audio_file(latest_file, output_filename, 1, 1)
            logger.info(f"\nResults saved to {output_filename}")
            return

        # Handle local file
        if not os.path.exists(audio_file):
            logger.error(f"Error: File '{audio_file}' not found.")
            sys.exit(1)

        # Create output filename based on MP3 name (without timestamp for rescan analysis)
        mp3_base_name = os.path.splitext(os.path.basename(audio_file))[0]
        output_filename = os.path.join(RESULTS_DIR, f"{mp3_base_name}.txt")

        # Since we're processing a single file, pass file_index=1 and total_files=1
        process_audio_file(audio_file, output_filename, 1, 1)
        logger.info(f"\nResults saved to {output_filename}")

    else:
        logger.error(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
