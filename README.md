# 🎵 Shazam Tool

> 🔍 A modular Python tool that downloads audio from SoundCloud or YouTube, splits it into segments, and uses Shazam to identify songs within the mix.

## ✨ Features

- 🎧 Download audio from SoundCloud or YouTube URLs
- 🎼 Identify songs using Shazam API with advanced timeout/retry logic
- 📊 **Enhanced status tracking** with comprehensive segment status types
- 🔄 **Enhanced automatic rescanning** with timeout retry and intelligent segment merging
- 🔍 **False positive validation** with extended audio segment analysis
- 📋 **Formatted tracklist** with numbered rows and clean layout
- 💾 Save results to organized text files named after source MP3s
- 🚀 Easy setup and usage with provided shell script
- 🏗️ **Modular architecture** with clean separation of concerns
- 🎯 **Type-safe status tracking** with centralized SegmentStatus enum

## 🛠️ Requirements

This project uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading audio from SoundCloud and YouTube.

**Core Dependencies:**
- `yt-dlp` - Audio downloading from YouTube/SoundCloud
- `shazamio` - Shazam API integration for song recognition
- `pydub` - Audio processing and segmentation
- `ffmpeg` - Required system dependency for audio processing

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

## 🏗️ Project Structure

```
shazam-tool/
├── shazam.py                     # Main entry point with command parsing
├── run_shazam.sh                 # Shell script wrapper for easy execution
├── modules/                      # Modular architecture
│   ├── core/                     # Core utilities
│   │   ├── constants.py          # Application constants and configuration
│   │   ├── helper.py             # Utility functions (timestamps, file ops)
│   │   └── logger.py             # Centralized logging system
│   ├── audio/                    # Audio processing modules
│   │   └── audioSegmentation.py  # Audio segmentation and extended segments
│   ├── download.py               # YouTube/SoundCloud downloading
│   ├── resultFileOperations.py   # Result file I/O and parsing
│   ├── trackRecognition.py       # Main track recognition processing
│   ├── trackValidation.py        # False positive validation
│   └── shazam/
│       └── shazamApi.py          # Shazam API integration
├── downloads/                    # Downloaded audio files (auto-created)
├── recognised-lists/             # Output directory for results (auto-created)
├── audio-segments/               # Temporary segments during processing
└── logs/                         # Session-based timestamped logs (auto-created)
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

# Validate tracks for false positives
./run_shazam.sh validate <file>

# Chainable commands (NEW!)
./run_shazam.sh scan rescan validate
./run_shazam.sh recognize file.mp3 rescan validate

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

#### 2. Enhanced Scan with Automatic Optimization

```sh
python shazam.py scan
```

Processes all MP3 files in the Downloads directory with intelligent enhancement:
- **Phase 1**: Automatic TIMEOUT retry with delays (up to 2 rounds)
- **Phase 2**: Sliding window merging of consecutive NOT_FOUND segments (≥3)
- **Smart Recognition**: Finds optimal segment sizes for difficult tracks

#### 3. Manual Rescan Failed Segments

```sh
python shazam.py rescan
```

Manually rescans only TIMEOUT and ERROR segments from previous runs, preserving successful recognitions. (Note: The enhanced `scan` command now includes automatic rescanning).

#### 4. Recognize Single File

```sh
python shazam.py recognize <file>
```

Processes a single audio file for song recognition.

#### 5. Validate False Positives

```sh
python shazam.py validate <file> [--threshold 3]
```

Validates tracks that appear infrequently (≤ threshold occurrences) by re-recognizing them with extended audio segments. Helps identify and mark false positive detections.

**Options:**
- `--threshold`: Maximum occurrences for validation candidates (default: 3)
- Omit `<file>` to validate all files in downloads directory

**How it works:**
- Identifies tracks appearing ≤ threshold times (likely false positives)
- Creates extended 20-50 second segments around suspicious detections
- Re-recognizes with Shazam using longer audio context
- Updates scan log with validation statuses:
  - `VALIDATION_FALSE_POSITIVE` - Detected as false positive
  - `VALIDATION_VALIDATED` - Confirmed as legitimate
  - `VALIDATION_UNCERTAIN` - Unclear validation result

#### 6. Chainable Commands (NEW!)

Execute multiple commands in sequence for streamlined workflows:

```sh
# Complete workflow: scan all files, rescan failures, validate results
python shazam.py scan rescan validate

# Process specific file and validate
python shazam.py recognize file.mp3 rescan validate

# Quick scan and validation
python shazam.py scan validate

# Rescan failures and validate
python shazam.py rescan validate
```

Commands are executed in the order specified, with progress tracking for each step.

## 📋 Output

Results are saved in the `recognised-lists` directory with files named after the source MP3:

```
{filename}.txt
```

### File Structure

Each result file contains two sections:

**📃 Tracklist** - Clean formatted list with numbered rows:
```
===== Tracklist =====
  1 - 00:01:10 - Deadmau5 - Strobe
  2 - 00:04:20 - Skrillex - Bangarang
  3 - 00:07:30 - Martin Garrix - Animals
```

**📊 Scan Log** - Detailed status for every 10-second segment:
```
===== Scan Log =====
00:00:00 - NOT_FOUND
00:01:10 - FOUND - Deadmau5 - Strobe
00:01:20 - TIMEOUT
00:01:30 - ERROR
00:02:00 - VALIDATION_FALSE_POSITIVE - Track Name
00:02:10 - VALIDATION_VALIDATED - Another Track
```

**Enhanced Status Types (SegmentStatus Enum):**
- `FOUND` - Successfully identified track via standard recognition
- `FOUND_MERGED` - Track identified through intelligent segment merging
- `VALIDATION_VALIDATED` - Track confirmed legitimate by validation process
- `VALIDATION_FALSE_POSITIVE` - Track marked as false positive detection
- `VALIDATION_UNCERTAIN` - Validation result unclear or inconclusive
- `NOT_FOUND` - No recognition after all retry and merge attempts
- `TIMEOUT` - Recognition timed out despite retry attempts
- `ERROR` - Exception during recognition process

> ℹ️ The tracklist can be imported into [TuneMyMusic](https://www.tunemymusic.com/)

## 📝 Notes

### Architecture & Design
- **Modular Architecture**: Clean separation of concerns with organized modules for better maintainability
- **Type Safety**: Centralized SegmentStatus enum prevents string literal errors and improves code reliability
- **Centralized Configuration**: All constants and settings managed in `modules/core/constants.py`
- **Session-based Logging**: Timestamped log files (YYYY-MM-DD_HH-MM-SS.log) for each execution session
- **Enhanced Logging**: Structured logging system with debug mode support

### Processing Features
- **Enhanced Scan Process**: Automatic two-phase optimization (TIMEOUT retry + segment merging)
- **Intelligent Segment Merging**: Sliding window approach finds optimal segment sizes for difficult tracks
- **Smart Recognition**: 10-second base segments with automatic merging for tracks spanning multiple segments
- **Robust API Communication**: 40-second timeout with 3 retries plus additional retry rounds with delays
- **Clean Formatted Output**: Numbered tracks in compact layout with comprehensive status tracking

### Performance & Reliability
- **Automatic Recovery**: Intelligent handling of network issues, API timeouts, and recognition failures
- **Duplicate Filtering**: Songs within the same mix are automatically deduplicated in tracklist
- **Memory Efficiency**: Large files processed in chunks with automatic cleanup
- **Progress Tracking**: Detailed logging shows processing phases and improvement results

## 🤝 Contributing

Feel free to open issues or submit pull requests with improvements. We welcome contributions from the community!

---

<div align="center">
  <sub>Built with ❤️ </sub>
</div>
