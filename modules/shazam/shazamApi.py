import asyncio

from shazamio import Shazam

from modules.core.constants import MAX_RETRIES, TIMEOUT, SegmentStatus
from modules.core.logger import logger


async def recognize_track(file_path: str) -> dict:
    """
    Uses Shazam to recognize the song with retry logic, timeout, and error handling.
    Returns dict with 'status' and 'track' keys, or dict with error status.
    """
    import time
    shazam = Shazam()
    logger.debug(f"Attempting to recognize: {file_path} (max retries: {MAX_RETRIES}, timeout: {TIMEOUT}s)")

    for attempt in range(MAX_RETRIES):
        try:
            start_time = time.time()
            logger.debug(f"Recognition attempt {attempt + 1}/{MAX_RETRIES} starting...")

            # Add timeout to prevent hanging
            data = await asyncio.wait_for(shazam.recognize(file_path), timeout=TIMEOUT)

            elapsed = time.time() - start_time
            logger.debug(f"API call completed in {elapsed:.2f}s")

            if 'track' not in data:
                logger.debug(f"No track data found in attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2)  # Increased delay between retries
                    continue
                logger.debug("Recognition failed after all attempts - no track data")
                return {"status": SegmentStatus.NOT_FOUND.value, "track": ""}

            title = data['track']['title']
            subtitle = data['track']['subtitle']

            track_string = f"{subtitle} - {title}"
            result = {"status": SegmentStatus.FOUND.value, "track": track_string}
            logger.debug(f"Recognition successful in {elapsed:.2f}s: {track_string}")
            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(f"Recognition attempt {attempt + 1} timed out after {elapsed:.2f}s")
            if attempt < MAX_RETRIES - 1:
                logger.debug(f"Retrying with increased timeout...")
                await asyncio.sleep(3)  # Longer delay after timeout
                continue
            logger.warning("Recognition failed after all attempts due to timeout")
            return {"status": SegmentStatus.TIMEOUT.value, "track": ""}

        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"Error in recognition attempt {attempt + 1} after {elapsed:.2f}s: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2)
                continue
            logger.warning("Recognition failed after all attempts due to exception")
            return {"status": SegmentStatus.ERROR.value, "track": ""}
