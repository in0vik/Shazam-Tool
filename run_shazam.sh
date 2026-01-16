#!/bin/bash

# Colors for better readability
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo -e "${BOLD}[MUSIC] Shazam Tool Setup & Runner${NC}\n"

# Ensure directories exist
mkdir -p downloads tmp recognised-lists logs

# Function to check if command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Setup environment
setup_environment() {
  echo -e "${BLUE}Setting up environment...${NC}"
  
  # Check for Python 3.11 or 3.12 first, then fall back to Python 3
  PYTHON_CMD="python3"
  if command_exists python3.11; then
    PYTHON_CMD="python3.11"
    echo "Using Python 3.11"
  elif command_exists python3.12; then
    PYTHON_CMD="python3.12"
    echo "Using Python 3.12"
  elif command_exists python3; then
    PYTHON_CMD="python3"
    echo "Using Python 3"
  else
    echo "Python 3 is required but not installed. Please install Python 3.11+"
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
    $PYTHON_CMD -m venv venv
  fi
  
  # Activate virtual environment
  echo "Activating virtual environment..."
  if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
  else
    source venv/bin/activate
  fi
  
  # Install dependencies
  echo "Installing dependencies..."
  
  echo -e "${GREEN}Environment setup complete!${NC}\n"
}

# Run the Shazam tool
run_shazam() {
  # Ensure virtual environment is activated
  if [ -z "$VIRTUAL_ENV" ]; then
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
      source venv/Scripts/activate
    else
      source venv/bin/activate
    fi
  fi
  
  # Run the Shazam tool with provided arguments
  echo -e "${BLUE}Running Shazam Tool...${NC}"
  python shazam.py "$@"
}

# Display help information
show_help() {
  echo -e "${BOLD}Shazam Tool - Help${NC}"
  echo "Usage: ./run_shazam.sh [command1] [command2] ... [file/url] [options]"
  echo ""
  echo "Commands:"
  echo "  setup       - Install dependencies and set up the environment"
  echo "  download    - Download and analyze audio from URL"
  echo "               Example: ./run_shazam.sh download https://soundcloud.com/user/track"
  echo "  scan        - Process all downloaded files"
  echo "  rescan      - Reprocess failed segments from previous scans"
  echo "  recognize   - Process a specific audio file"
  echo "               Example: ./run_shazam.sh recognize path/to/file.mp3"
  echo "  validate    - Validate tracks for false positives"
  echo "               Example: ./run_shazam.sh validate path/to/file.mp3"
  echo "               Example: ./run_shazam.sh validate path/to/file.mp3 --threshold 2"
  echo "  help        - Show this help information"
  echo ""
  echo -e "${BOLD}Chainable Commands (NEW!):${NC}"
  echo "  ./run_shazam.sh scan rescan validate           # Scan -> Rescan -> Validate all"
  echo "  ./run_shazam.sh recognize file.mp3 rescan validate  # Recognize -> Rescan -> Validate"
  echo "  ./run_shazam.sh scan validate                  # Scan -> Validate all"
  echo "  ./run_shazam.sh rescan validate                # Rescan -> Validate all"
  echo ""
}

# Make the script executable
chmod +x "$0"

# Check if no arguments provided or help requested
if [ $# -eq 0 ] || [ "$1" = "help" ]; then
  show_help
  exit 0
fi

# Handle setup command separately as it's not chainable
if [ "$1" = "setup" ]; then
  setup_environment
  exit 0
fi

# Handle chainable commands
valid_commands=("scan" "rescan" "validate" "download" "recognize")
commands=()
other_args=()

# Parse arguments to separate commands from files/options
for arg in "$@"; do
  if [[ " ${valid_commands[@]} " =~ " ${arg} " ]]; then
    commands+=("$arg")
  else
    other_args+=("$arg")
  fi
done

# Validate that we have at least one valid command
if [ ${#commands[@]} -eq 0 ]; then
  echo "Error: No valid commands found"
  echo "Valid commands: ${valid_commands[*]}"
  show_help
  exit 1
fi

# Special validation for commands that require arguments
for cmd in "${commands[@]}"; do
  if [ "$cmd" = "download" ] || [ "$cmd" = "recognize" ]; then
    if [ ${#other_args[@]} -eq 0 ]; then
      echo "Error: Command '$cmd' requires a file path or URL"
      echo "Usage: ./run_shazam.sh $cmd <file/url> [other commands...]"
      exit 1
    fi
  fi
done

# Execute the commands by passing everything to the Python script
echo -e "${BLUE}Running Shazam Tool with chainable commands...${NC}"
run_shazam "$@"
