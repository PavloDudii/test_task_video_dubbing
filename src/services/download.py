import aiohttp
import aiofiles
import logging
from pathlib import Path
import ssl

logger = logging.getLogger(__name__)


async def download_file(url: str, dest_path: Path, timeout: int = 300) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    async with aiofiles.open(dest_path, 'wb') as f:
                        await f.write(await resp.read())
                    logger.info(f"Downloaded: {dest_path.name}")
                    return True
                else:
                    logger.error(f"Download failed (HTTP {resp.status}): {url}")
                    return False
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
        return False
