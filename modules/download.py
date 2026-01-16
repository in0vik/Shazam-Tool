from yt_dlp import YoutubeDL

from modules.core.helper import ensure_directory_exists
from modules.core.constants import DOWNLOADS_DIR
from modules.core.logger import logger


def download_from_url(url: str) -> None:
    """
    Determines if URL is YouTube or SoundCloud and calls appropriate download function.
    """
    logger.info("[START] Starting download...")
    lower_url = url.lower()
    logger.debug(f"Processing URL: {url}")
    if 'soundcloud.com' in lower_url:
        logger.info("[MUSIC] SoundCloud URL detected")
        download_soundcloud(url)
    elif 'youtube.com' in lower_url or 'youtu.be' in lower_url:
        logger.info("[VIDEO] YouTube URL detected")
        download_youtube(url)
    else:
        logger.error("[ERROR] Unsupported URL format. Please provide a YouTube or SoundCloud link.")


def download_soundcloud(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download audio from a SoundCloud URL using yt-dlp.
    """
    ensure_directory_exists(output_path)
    logger.debug(f"Attempting to download from SoundCloud: {url}")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        logger.info("[OK] Successfully downloaded from SoundCloud!")
    except Exception as e:
        logger.error(f"[ERROR] Failed to download from SoundCloud {url}: {e}")


def download_youtube(url: str, output_path: str = DOWNLOADS_DIR) -> None:
    """
    Download the audio track from a YouTube video and convert to mp3 using yt-dlp.
    """
    ensure_directory_exists(output_path)
    logger.debug(f"Attempting to download from YouTube: {url}")
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Title')
            logger.info(f"[OK] Successfully downloaded: {title}!")
    except Exception as e:
        logger.error(f"[ERROR] Error downloading from YouTube {url}: {e}")
