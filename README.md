# 🎵 Shazam Tool

> 🔍 A Python script that downloads audio from SoundCloud or YouTube, splits it into segments, and uses Shazam to identify songs within the mix.

## ✨ Features

- 🎧 Download audio from SoundCloud or YouTube URLs
- 🎼 Identify songs using Shazam API with advanced timeout/retry logic
- 📊 Smart status tracking (FOUND, NOT_FOUND, TIMEOUT, ERROR)
- 🔄 Intelligent rescanning of failed segments only
- 📋 Structured output with condensed tracklist and detailed scan log
- 💾 Save results to organized text files named after source MP3s
- 🚀 Easy setup and usage with provided shell script

## 🛠️ Requirements

This project uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading audio from SoundCloud and YouTube.

### Linux

```sh
sudo apt install ffmpeg
pip install ShazamApi pydub yt-dlp shazamio
```

### macOS

```sh
# Install Homebrew if not already installed
# See https://brew.sh for installation instructions

brew install ffmpeg

# Optional: Create and activate virtual environment
# python3.11 -m venv venv && source venv/bin/activate

# If you don't have Python 3.11:
# brew install python@3.11

# Install required packages
pip install shazamio pydub yt-dlp ShazamApi
```

## 📚 Usage

### Quick Start (Recommended)

Use the provided shell script for easy setup and running:

```sh
# Make the script executable (if needed)
chmod +x run_shazam.sh

# Setup environment (installs dependencies, creates venv)
./run_shazam.sh setup

# Download and process audio from URL
./run_shazam.sh download <url>

# Process all downloaded files
./run_shazam.sh scan

# Rescan only failed segments from previous runs
./run_shazam.sh rescan

# Process a specific audio file
./run_shazam.sh recognize <file>

# Show help information
./run_shazam.sh help
```

### Manual Usage

The script also supports direct Python invocation with three main commands:

#### 1. Download and Process from URL

```sh
python shazam.py download <url>
```

Downloads audio from YouTube or SoundCloud and processes it for song recognition.

#### 2. Scan Downloaded Files

```sh
python shazam.py scan
```

Processes all MP3 files in the Downloads directory.

#### 3. Rescan Failed Segments

```sh
python shazam.py rescan
```

Intelligently rescans only TIMEOUT and ERROR segments from previous runs, preserving successful recognitions.

#### 4. Recognize Single File

```sh
python shazam.py recognize <file>
```

Processes a single audio file for song recognition.

## 📋 Output

Results are saved in the `recognised-lists` directory with files named after the source MP3:

```
{filename}.txt
```

### File Structure

Each result file contains two sections:

**📃 Tracklist** - Condensed list of identified tracks (first occurrence only):
```
00:01:10 - Artist - Track Title
00:04:20 - Another Artist - Another Track
```

**📊 Scan Log** - Detailed status for every 10-second segment:
```
00:00:00 - NOT_FOUND
00:01:10 - FOUND
00:01:20 - TIMEOUT
00:01:30 - ERROR
```

> ℹ️ The tracklist can be imported into [TuneMyMusic](https://www.tunemymusic.com/)

## 📝 Notes

- The script splits audio into 10-second segments for precise recognition
- Uses 40-second timeout with 3 retries for robust API communication
- Duplicate songs within the same mix are automatically filtered out in the tracklist
- Failed segments can be reprocessed individually using the rescan feature
- Large files are processed in chunks to manage memory efficiently
- Status tracking allows for intelligent recovery from network issues or API timeouts

## 🤝 Contributing

Feel free to open issues or submit pull requests with improvements. We welcome contributions from the community!

---

<div align="center">
  <sub>Built with ❤️ </sub>
</div>
