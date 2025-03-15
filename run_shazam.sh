#!/bin/bash

# Colors for better readability
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo -e "${BOLD}🎵 Shazam Tool Setup & Runner${NC}\n"

# Ensure directories exist
mkdir -p downloads tmp recognised-lists logs

# Function to check if command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Setup environment
setup_environment() {
  echo -e "${BLUE}Setting up environment...${NC}"
  
  # Check for Python
  if ! command_exists python3; then
    echo "Python 3 is required but not installed. Please install Python 3.7+"
    exit 1
  fi
  
  # Check for ffmpeg
  if ! command_exists ffmpeg; then
    echo "ffmpeg is required but not installed."
    if [[ "$OSTYPE" == "darwin"* ]]; then
      echo "Installing ffmpeg using Homebrew..."
      brew install ffmpeg
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
      echo "Please install ffmpeg using: sudo apt install ffmpeg"
      exit 1
    else
      echo "Please install ffmpeg manually for your operating system."
      exit 1
    fi
  fi
  
  # Create virtual environment if it doesn't exist
  if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
  fi
  
  # Activate virtual environment
  echo "Activating virtual environment..."
  source venv/bin/activate
  
  # Install dependencies
  echo "Installing dependencies..."
  pip install shazamio pydub yt-dlp ShazamApi
  
  echo -e "${GREEN}Environment setup complete!${NC}\n"
}

# Run the Shazam tool
run_shazam() {
  # Ensure virtual environment is activated
  if [ -z "$VIRTUAL_ENV" ]; then
    source venv/bin/activate
  fi
  
  # Run the Shazam tool with provided arguments
  echo -e "${BLUE}Running Shazam Tool...${NC}"
  python shazam.py "$@"
}

# Display help information
show_help() {
  echo -e "${BOLD}Shazam Tool - Help${NC}"
  echo "Usage: ./run_shazam.sh [command]"
  echo ""
  echo "Commands:"
  echo "  setup       - Install dependencies and set up the environment"
  echo "  download    - Download and analyze audio from URL"
  echo "               Example: ./run_shazam.sh download https://soundcloud.com/user/track"
  echo "  scan        - Process all downloaded files"
  echo "  recognize   - Process a specific audio file"
  echo "               Example: ./run_shazam.sh recognize path/to/file.mp3"
  echo "  help        - Show this help information"
  echo ""
}

# Make the script executable
chmod +x "$0"

# Main command handler
case "$1" in
  "setup")
    setup_environment
    ;;
  "download")
    if [ -z "$2" ]; then
      echo "Error: URL required"
      echo "Usage: ./run_shazam.sh download <url>"
      exit 1
    fi
    run_shazam download "$2"
    ;;
  "scan")
    run_shazam scan
    ;;
  "recognize")
    if [ -z "$2" ]; then
      echo "Error: File path required"
      echo "Usage: ./run_shazam.sh recognize <file>"
      exit 1
    fi
    run_shazam recognize "$2"
    ;;
  "help"|"")
    show_help
    ;;
  *)
    echo "Unknown command: $1"
    show_help
    exit 1
    ;;
esac
