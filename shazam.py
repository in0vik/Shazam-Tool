import os
import sys
import asyncio
from datetime import datetime
import subprocess
import logging

from pydub import AudioSegment
from shazamio import Shazam
from pytube import YouTube

# Length of each segment in milliseconds
SEGMENT_LENGTH = 60 * 1000
DOWNLOADS_DIR = 'downloads'

# Logger configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Add handler for console output
    ]
)

# Get logger for scdl
logger = logging.getLogger('scdl')

def ensure_directory_exists(dir_path: str) -> None:
    """
    Ensure that the specified directory exists; if not, create it.
    """
    os.makedirs(dir_path, exist_ok=True)

def remove_files(directory: str) -> None:
    """
    Remove all files in the specified directory. If the directory does not exist,
    it will be created.
    """
    ensure_directory_exists(directory)
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"Error removing file {file_path}: {e}")

def write_to_file(data: str, filename: str) -> None:
    """
    Append a line of text to the specified file, only if data is not "Not found".
    """
    if data != "Not found":
        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"{data}\n")
        except OSError as e:
            print(f"Error writing to file {filename}: {e}")

def segment_audio(audio_file: str, output_directory: str = "tmp") -> None:
    """
    Segment an mp3 file into 1-minute chunks and store them in the output directory.
    Handles large files by processing them in chunks.
    """
    ensure_directory_exists(output_directory)
    
    try:
        # Open the file in binary mode for manual chunking
        with open(audio_file, 'rb') as f:
            # Read the file in 1GB chunks
            chunk_size = 1024 * 1024 * 1024  # 1GB
            segment_counter = 1
            
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                # Create a temporary file for this chunk
                temp_chunk_path = os.path.join(output_directory, f"temp_chunk_{segment_counter}.mp3")
                with open(temp_chunk_path, 'wb') as temp_file:
                    temp_file.write(chunk)
                
                try:
                    # Process this chunk with pydub
                    audio_chunk = AudioSegment.from_file(temp_chunk_path, format="mp3")
                    
                    # Create segments from this chunk
                    segments = [audio_chunk[i:i+SEGMENT_LENGTH] for i in range(0, len(audio_chunk), SEGMENT_LENGTH)]
                    
                    # Export segments
                    for segment in segments:
                        segment_file_path = os.path.join(output_directory, f"{segment_counter}.mp3")
                        segment.export(segment_file_path, format="mp3")
                        segment_counter += 1
                    
                    # Remove temporary chunk file
                    os.remove(temp_chunk_path)
                    
                except Exception as e:
                    print(f"Error processing chunk: {e}")
                    if os.path.exists(temp_chunk_path):
                        os.remove(temp_chunk_path)
                    
    except Exception as e:
        print(f"Failed to process audio file {audio_file}: {e}")

def download_soundcloud(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download audio from a SoundCloud URL using scdl.
    """
    ensure_directory_exists(output_path)
    try:
        # Run scdl command without capturing output
        result = subprocess.run(
            ['scdl', '-l', url, '--path', output_path, '--onlymp3'],
            check=True 
        )
    except subprocess.CalledProcessError as e:
        print(f"Failed to download from SoundCloud. Exit code: {e.returncode}")
    except Exception as e:
        print(f"Failed to download from SoundCloud {url}: {e}")

def download_youtube(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download the audio track of a YouTube video and convert it to mp3.
    """
    ensure_directory_exists(output_path)
    try:
        yt = YouTube(url)
        video = yt.streams.filter(only_audio=True).first()
        out_file = video.download(output_path=output_path)
        base, _ = os.path.splitext(out_file)
        new_file = base + '.mp3'
        os.rename(out_file, new_file)
        print(f"{yt.title} has been successfully downloaded.")
    except Exception as e:
        print(f"Failed to download from YouTube {url}: {e}")

def download_from_url(url: str) -> None:
    """
    Download audio from either YouTube or SoundCloud URL.
    """
    if 'soundcloud.com' in url.lower():
        download_soundcloud(url)
    elif 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
        download_youtube(url)
    else:
        print("Unsupported URL format. Please provide a YouTube or SoundCloud URL.")

async def get_name(file: str, max_retries: int = 3) -> str:
    """
    Use Shazamio to recognize the song with retry logic.
    """
    shazam = Shazam()
    for attempt in range(max_retries):
        try:
            data = await shazam.recognize(file)
            if 'track' not in data:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # Wait before retry
                    continue
                return "Not found"
            title = data['track']['title']
            subtitle = data['track']['subtitle']
            print(f"{title} - {subtitle}")
            return f"{title} - {subtitle}"
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Retry {attempt + 1}/{max_retries} for {file}: {e}")
                await asyncio.sleep(1)  # Wait before retry
                continue
            print(f"Shazam recognition failed after {max_retries} attempts for {file}: {e}")
            return "Not found"

def process_audio_file(audio_file: str, output_filename: str) -> None:
    """
    Process a single audio file with duplicate detection.
    """
    print(f"\nProcessing: {audio_file}")
    
    # Track unique songs
    unique_songs = set()
    
    # Write file name as header
    try:
        with open(output_filename, "a", encoding="utf-8") as f:
            f.write(f"===== {os.path.basename(audio_file)} ======\n")
    except OSError as e:
        print(f"Error writing header for {audio_file}: {e}")
        return

    print("Removing temporary files...")
    remove_files("tmp")

    print("Segmenting audio file...")
    segment_audio(audio_file, "tmp")

    print("Getting song names...")
    tmp_files = sorted(os.listdir("tmp"), key=lambda x: int(x.split('.')[0]))
    for file_name in tmp_files:
        segment_path = os.path.join("tmp", file_name)
        try:
            loop = asyncio.get_event_loop()
            name = loop.run_until_complete(get_name(segment_path))
            if name != "Not found" and name not in unique_songs:
                unique_songs.add(name)
                write_to_file(name, output_filename)
        except Exception as e:
            print(f"Error processing segment {file_name}: {e}")
            continue

    # Add two newlines after processing each file
    try:
        with open(output_filename, "a", encoding="utf-8") as f:
            f.write("\n\n")
    except OSError as e:
        print(f"Error writing spacing after {audio_file}: {e}")

    print("Cleaning up...")
    remove_files("tmp")
    print(f"Finished processing: {audio_file}")

def print_usage():
    """
    Print usage instructions for the script.
    """
    print("""
Usage: python shazam.py [command] [options]

Commands:
    scan                       Scan and recognize all MP3 files in downloads directory
    download <url>             Download and process from YouTube or SoundCloud URL
    recognize <file>           Recognize a single audio file
    
Examples:
    python shazam.py scan
    python shazam.py download https://www.youtube.com/watch?v=...
    python shazam.py download https://soundcloud.com/...
    python shazam.py recognize path/to/audio.mp3
    """)

def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]

    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    if command == 'download':
        if len(sys.argv) != 3:
            print("Usage: python shazam.py download <url>")
            sys.exit(1)
        url = sys.argv[2]
        
        # Create output file with appropriate header
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(f"===== Download Results ======\n\n")
        except OSError as e:
            print(f"Error creating output file {output_filename}: {e}")
            sys.exit(1)
            
        download_from_url(url)
        process_downloads()

    elif command in ['scan', 'scan-downloads']:  # Support both commands for compatibility
        print(f"Scanning {DOWNLOADS_DIR} directory for MP3 files...")
        process_downloads()
        return

    elif command == 'recognize':
        if len(sys.argv) != 3:
            print("Usage: python shazam.py recognize <file>")
            sys.exit(1)
        
        audio_file = sys.argv[2]
        if not os.path.exists(audio_file):
            print(f"Error: File '{audio_file}' not found")
            sys.exit(1)

        output_dir = "recognised-lists"
        ensure_directory_exists(output_dir)
        timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
        output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(f"===== Recognition Results ======\n\n")
        except OSError as e:
            print(f"Error creating output file {output_filename}: {e}")
            sys.exit(1)

        process_audio_file(audio_file, output_filename)
        print(f"\nResults saved to {output_filename}")

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)

def process_downloads():
    """
    Process all MP3 files in the downloads directory.
    """
    output_dir = "recognised-lists"
    ensure_directory_exists(output_dir)
    ensure_directory_exists(DOWNLOADS_DIR)  # Ensure downloads directory exists
    
    input_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.endswith('.mp3')]
    
    if not input_files:
        print(f"No MP3 files found in '{DOWNLOADS_DIR}' directory.")
        return

    timestamp = datetime.now().strftime("%d%m%y-%H%M%S")
    output_filename = os.path.join(output_dir, f"songs-{timestamp}.txt")

    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(f"===== Scan Results from {DOWNLOADS_DIR} directory ======\n\n")
    except OSError as e:
        print(f"Error creating output file {output_filename}: {e}")
        return

    print(f"Found {len(input_files)} MP3 files to process...")
    print("Starting processing...")
    
    for audio_file in input_files:
        full_path = os.path.join(DOWNLOADS_DIR, audio_file)
        process_audio_file(full_path, output_filename)
    
    print(f"\nAll files processed! Results saved to {output_filename}")

if __name__ == "__main__":
    main()