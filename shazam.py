import os
import sys
import asyncio
from datetime import datetime
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment
from shazamio import Shazam
from pytube import YouTube

# Duration of each segment in milliseconds (1 minute)
SEGMENT_LENGTH = 60 * 1000

# Directory for downloaded files
DOWNLOADS_DIR = 'downloads'

# Logger setup (set to WARNING to avoid extra info in terminal)
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and above
    format='%(message)s',
    handlers=[
        logging.StreamHandler()  # Console output
    ]
)
logger = logging.getLogger('scdl')


def ensure_directory_exists(dir_path: str) -> None:
    """
    Checks if directory exists, creates it if it doesn't.
    """
    os.makedirs(dir_path, exist_ok=True)


def remove_files(directory: str) -> None:
    """
    Removes all files in specified directory. If directory doesn't exist,
    it will be created.
    """
    ensure_directory_exists(directory)
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"Error deleting file {file_path}: {e}")


def write_to_file(data: str, filename: str) -> None:
    """
    Appends text string to specified file if data != 'Not found'.
    """
    if data != "Not found":
        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"{data}\n")
        except OSError as e:
            print(f"Error writing to file {filename}: {e}")


def download_soundcloud(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download audio from a SoundCloud URL using scdl.
    """
    ensure_directory_exists(output_path)
    try:
        # Redirect stdout and stderr to DEVNULL to suppress scdl logs
        subprocess.run(
            ['scdl', '-l', url, '--path', output_path, '--onlymp3'],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ Successfully downloaded from SoundCloud!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to download from SoundCloud. Exit code: {e.returncode}")
    except Exception as e:
        print(f"❌ Failed to download from SoundCloud {url}: {e}")


def download_youtube(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download the audio track from a YouTube video and convert to mp3.
    """
    ensure_directory_exists(output_path)
    try:
        yt = YouTube(url)
        video_stream = yt.streams.filter(only_audio=True).first()
        out_file = video_stream.download(output_path=output_path)
        base, _ = os.path.splitext(out_file)
        new_file = base + '.mp3'
        os.rename(out_file, new_file)
        print(f"✅ Successfully downloaded: {yt.title}!")
    except Exception as e:
        print(f"❌ Error downloading from YouTube {url}: {e}")


def download_from_url(url: str) -> None:
    """
    Determines if URL is YouTube or SoundCloud and calls appropriate download function.
    """
    print("🚀 Starting download...")
    lower_url = url.lower()
    if 'soundcloud.com' in lower_url:
        print("🎵 SoundCloud URL detected")
        download_soundcloud(url)
    elif 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        print("🎥 YouTube URL detected")
        download_youtube(url)
    else:
        print("❌ Unsupported URL format. Please provide a YouTube or SoundCloud link.")


def segment_audio(audio_file: str, output_directory: str = "tmp", num_threads: int = 4) -> None:
    """
    Segments MP3 file into chunks of SEGMENT_LENGTH duration (in milliseconds)
    using parallel processing.
    """
    ensure_directory_exists(output_directory)
    try:
        audio = AudioSegment.from_file(audio_file, format="mp3")
        segments = [audio[i:i + SEGMENT_LENGTH] for i in range(0, len(audio), SEGMENT_LENGTH)]
        total_segments = len(segments)

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


async def get_name(file_path: str, max_retries: int = 3) -> str:
    """
    Uses Shazam to recognize the song with retry logic and error handling.
    Returns either 'Track Title - Artist' or 'Not found' if it fails.
    """
    shazam = Shazam()
    for attempt in range(max_retries):
        try:
            data = await shazam.recognize(file_path)
            if 'track' not in data:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return "Not found"

            title = data['track']['title']
            subtitle = data['track']['subtitle']
            return f"{title} - {subtitle}"

        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            return "Not found"


def process_audio_file(audio_file: str, output_filename: str, file_index: int, total_files: int) -> None:
    """
    Processes a single audio file: segments it, recognizes each segment,
    excludes duplicate tracks, and saves results.
    """
    # If there are multiple files, display the file index
    if total_files > 2:
        print(f"\n[{file_index}/{total_files}] Processing file: {audio_file}")
    else:
        print(f"\nProcessing file: {audio_file}")

    unique_tracks = set()
    try:
        with open(output_filename, "a", encoding="utf-8") as f:
            f.write(f"===== {os.path.basename(audio_file)} ======\n")
    except OSError as e:
        print(f"Error writing header for {audio_file}: {e}")
        return

    print("1/5 🧹 Cleaning temporary files...")
    remove_files("tmp")

    print("2/5 ✂️ Segmenting audio file...")
    segment_audio(audio_file, "tmp")

    print("3/5 🔍 Recognizing segments...")
    tmp_files = sorted(os.listdir("tmp"), key=lambda x: int(os.path.splitext(x)[0]))
    total_segments = len(tmp_files)

    for idx, file_name in enumerate(tmp_files, start=1):
        segment_path = os.path.join("tmp", file_name)
        try:
            loop = asyncio.get_event_loop()
            track_name = loop.run_until_complete(get_name(segment_path))

            # Build the progress output in the desired format
            progress_str = f"[{idx}/{total_segments}]: {track_name}"
            print(progress_str)

            if track_name != "Not found" and track_name not in unique_tracks:
                unique_tracks.add(track_name)
                write_to_file(track_name, output_filename)
        except Exception as e:
            print(f"Error processing segment {file_name}: {e}")
            continue

    # Add an empty line after processing each file
    try:
        with open(output_filename, "a", encoding="utf-8") as f:
            f.write("\n")
    except OSError as e:
        print(f"Error writing empty line for {audio_file}: {e}")

    print("🧹 Cleaning temporary files...")
    remove_files("tmp")
    print(f"✅ Successfully processed file: {audio_file}")


def process_downloads() -> None:
    """
    Process all MP3 files in DOWNLOADS_DIR: recognize each and save results to a new file.
    """
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
    ensure_directory_exists(DOWNLOADS_DIR)

    mp3_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
    if not mp3_files:
        print(f"❌ No MP3 files found in '{DOWNLOADS_DIR}' directory.")
        return

    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(f"===== Scan results for {DOWNLOADS_DIR} directory ======\n\n")
    except OSError as e:
        print(f"Error creating output file {output_filename}: {e}")
        return

    total_files = len(mp3_files)
    print(f"📝 Found {total_files} MP3 file(s) to process...")
    print("🚀 Starting processing...")

    for idx, file_name in enumerate(mp3_files, start=1):
        full_path = os.path.join(DOWNLOADS_DIR, file_name)
        process_audio_file(full_path, output_filename, idx, total_files)

    print(f"\n5/5 ✨ All files successfully processed!")
    print(f"📋 Results saved to {output_filename}")


def print_usage() -> None:
    """
    Displays script usage instructions.
    """
    print("""
🎵 Shazam Tool 🎵

Usage: python shazam.py [command] [options]

Commands:
    🔍 scan                       Scan downloads directory and recognize all MP3
    ⬇️  download <url>            Download and process audio from YouTube or SoundCloud
    🎯 recognize <file_path>      Recognize specific audio file

Examples:
    python shazam.py scan
    python shazam.py download https://www.youtube.com/watch?v=...
    python shazam.py download https://soundcloud.com/...
    python shazam.py recognize path/to/audio.mp3
    """)


def main() -> None:
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)

    # Generate default output filename
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    if command == 'download':
        if len(sys.argv) != 3:
            print("Usage: python shazam.py download <url>")
            sys.exit(1)

        url = sys.argv[2]
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write("===== Download Results ======\n\n")
        except OSError as e:
            print(f"Error creating output file {output_filename}: {e}")
            sys.exit(1)

        download_from_url(url)
        process_downloads()

    elif command in ['scan', 'scan-downloads']:
        print(f"Scanning '{DOWNLOADS_DIR}' directory for MP3 files...")
        process_downloads()
        return

    elif command == 'recognize':
        if len(sys.argv) != 3:
            print("Usage: python shazam.py recognize <file_path>")
            sys.exit(1)

        audio_file = sys.argv[2]
        if not os.path.exists(audio_file):
            print(f"Error: File '{audio_file}' not found.")
            sys.exit(1)

        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write("===== Recognition Results ======\n\n")
        except OSError as e:
            print(f"Error creating output file {output_filename}: {e}")
            sys.exit(1)

        # Since we're processing a single file, pass file_index=1 and total_files=1
        process_audio_file(audio_file, output_filename, 1, 1)
        print(f"\nResults saved to {output_filename}")

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()