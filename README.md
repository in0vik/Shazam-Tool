# 🎵 Shazam Tool

> 🔍 A Python script that downloads audio from SoundCloud or YouTube, splits it into segments, and uses Shazam to identify songs within the mix.

## ✨ Features

- 🎧 Download audio from SoundCloud or YouTube URLs
- 🎼 Identify songs using Shazam API
- 💾 Save results to timestamped text files

## 🛠️ Requirements

This project uses [scdl](https://github.com/flyingrub/scdl) for downloading SoundCloud tracks.

### Linux

```sh
sudo apt install ffmpeg scdl
pip install ShazamApi pydub pytube shazamio
```

### macOS

```sh
# Install Homebrew if not already installed
# See https://brew.sh for installation instructions

brew install ffmpeg scdl

# Optional: Create and activate virtual environment
# python3.11 -m venv venv && source venv/bin/activate

# If you don't have Python 3.11:
# brew install python@3.11

# Install required packages
pip install shazamio pydub pytube ShazamApi
```

## 📚 Usage

The script supports three main commands:

### 1. Download and Process from URL

```sh
python shazam.py download <url>
```

Downloads audio from YouTube or SoundCloud and processes it for song recognition.

### 2. Scan Downloaded Files

```sh
python shazam.py scan
```

Processes all MP3 files in the Downloads directory.

### 3. Recognize Single File

```sh
python shazam.py recognize <file>
```

Processes a single audio file for song recognition.

## 📋 Output

Results are saved in the `recognised-lists` directory with timestamped filenames in the format:

```
songs-DDMMYY-HHMMSS.txt
```

> ℹ️ The generated song list can be imported into [TuneMyMusic](https://www.tunemymusic.com/)

## 📝 Notes

- The script splits audio into 1-minute segments for optimal recognition
- Duplicate songs within the same mix are automatically filtered out
- Large files are processed in chunks to manage memory efficiently

## 🤝 Contributing

Feel free to open issues or submit pull requests with improvements. We welcome contributions from the community!

---

<div align="center">
  <sub>Built with ❤️ </sub>
</div>
