import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Callable
from itertools import product

from .download import download_file
from .video import concatenate_videos
from .tts import TTSService
from .storage_service import GCSUploadService

logger = logging.getLogger(__name__)


class VideoGenerator:
    def __init__(self, tts_service: TTSService, gcs_service: GCSUploadService, config):
        self.tts_service = tts_service
        self.gcs_service = gcs_service
        self.config = config

    def parse_blocks(self, data: dict) -> Tuple[List[List[str]], List[str], List[dict]]:
        video_blocks = []
        audio_urls = []
        voice_configs = []

        i = 1
        while f"block{i}" in data:
            block = data[f"block{i}"]
            if isinstance(block, list) and block:
                video_blocks.append(block)
            i += 1

        i = 1
        while f"audio{i}" in data:
            audio_list = data[f"audio{i}"]
            if isinstance(audio_list, list):
                audio_urls.extend(audio_list)
            i += 1

        i = 1
        while f"voice{i}" in data:
            voice_list = data[f"voice{i}"]
            if isinstance(voice_list, list):
                voice_configs.extend(voice_list)
            i += 1

        return video_blocks, audio_urls, voice_configs

    async def process_video_block(
            self,
            video_urls: List[str],
            block_name: str,
            temp_dir: Path
    ) -> Path:
        logger.info(f"Processing {block_name}: {len(video_urls)} videos")

        downloaded_videos = []
        for idx, url in enumerate(video_urls):
            video_path = temp_dir / f"{block_name}_video_{idx}.mp4"
            if await download_file(url, video_path, self.config.download_timeout):
                downloaded_videos.append(video_path)
            else:
                raise Exception(f"Failed to download {block_name} video {idx}")

        concatenated_path = temp_dir / f"{block_name}_concatenated.mp4"

        if concatenate_videos(downloaded_videos, concatenated_path):
            for video_path in downloaded_videos:
                video_path.unlink()
            logger.info(f"{block_name}: Concatenated {len(video_urls)} videos")
            return concatenated_path
        else:
            raise Exception(f"{block_name}: Concatenation failed")

    async def generate_all_tts(
            self,
            voice_configs: List[dict],
            temp_dir: Path
    ) -> List[Path]:
        """Generate all TTS files once"""
        logger.info(f"Generating {len(voice_configs)} TTS files")

        tts_files = []
        loop = asyncio.get_event_loop()

        for idx, voice_config in enumerate(voice_configs):
            voice_path = temp_dir / f"tts_{idx}.mp3"

            success = await loop.run_in_executor(
                None,
                self.tts_service.generate_speech,
                voice_config['text'],
                voice_config['voice'],
                voice_path
            )

            if not success:
                logger.warning(f"TTS {idx} failed, creating silent audio")
                subprocess.run([
                    'ffmpeg', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
                    '-t', '1', '-y', str(voice_path)
                ], capture_output=True)

            tts_files.append(voice_path)

        logger.info(f"Generated {len(tts_files)} TTS files")
        return tts_files

    async def download_all_audio(
            self,
            audio_urls: List[str],
            temp_dir: Path
    ) -> List[Path]:
        logger.info(f"Downloading {len(audio_urls)} audio files")

        audio_files = []

        for idx, url in enumerate(audio_urls):
            audio_path = temp_dir / f"audio_{idx}.mp3"
            if await download_file(url, audio_path, self.config.download_timeout):
                audio_files.append(audio_path)
            else:
                raise Exception(f"Failed to download audio {idx}")

        logger.info(f"Downloaded {len(audio_files)} audio files")
        return audio_files

    def mix_audio_tracks(
            self,
            background_audio: Path,
            voice_audio: Path,
            output_path: Path
    ) -> bool:
        try:
            cmd = [
                'ffmpeg',
                '-i', str(background_audio),
                '-i', str(voice_audio),
                '-filter_complex',
                f'[0:a]volume={self.config.background_audio_volume}[bg];'
                f'[1:a]volume={self.config.voice_audio_volume}[vc];'
                f'[bg][vc]amix=inputs=2:duration=longest:dropout_transition=2',
                '-y', str(output_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            logger.error(f"Audio mix failed: {e}")
            return False

    async def create_audio_mixes(
            self,
            audio_files: List[Path],
            tts_files: List[Path],
            temp_dir: Path
    ) -> List[Path]:
        """Create all audio mixes (audio × tts combinations)"""
        combinations = list(product(audio_files, tts_files))
        logger.info(f"Creating {len(combinations)} audio mixes")

        mixed_audio_files = []
        loop = asyncio.get_event_loop()

        for idx, (audio, tts) in enumerate(combinations):
            mixed_path = temp_dir / f"mixed_{idx}.mp3"

            success = await loop.run_in_executor(
                None,
                self.mix_audio_tracks,
                audio,
                tts,
                mixed_path
            )

            if success:
                mixed_audio_files.append(mixed_path)
            else:
                logger.error(f"Failed to create audio mix {idx}")

        logger.info(f"Created {len(mixed_audio_files)} audio mixes")
        return mixed_audio_files

    def add_audio_to_video(
            self,
            video_path: Path,
            audio_path: Path,
            output_path: Path
    ) -> bool:
        """Add audio track to video (loop audio if shorter than video)"""
        try:
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-stream_loop', '-1',
                '-i', str(audio_path),
                '-map', '0:v',
                '-map', '1:a',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',
                '-y', str(output_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            logger.error(f"Failed to add audio to video: {e}")
            return False

    async def generate_all(
            self,
            task_id: str,
            data: dict,
            progress_callback: Callable = None
    ) -> Dict:
        results = {"successful": [], "failed": [], "total": 0, "urls": []}  # ADD urls

        try:
            video_blocks, audio_urls, voice_configs = self.parse_blocks(data)

            if not video_blocks:
                raise ValueError("No video blocks found")
            if not audio_urls:
                raise ValueError("No audio URLs found")
            if not voice_configs:
                raise ValueError("No voice configs found")

            logger.info(
                f"[{task_id}] Blocks: {len(video_blocks)}, Audio: {len(audio_urls)}, Voices: {len(voice_configs)}")

            temp_dir = Path(tempfile.mkdtemp(prefix=f"task_{task_id}_"))

            logger.info(f"[{task_id}] Step 1: Concatenating video blocks")
            base_videos = []
            for idx, video_urls in enumerate(video_blocks):
                block_name = f"block{idx + 1}"
                concatenated = await self.process_video_block(video_urls, block_name, temp_dir)
                base_videos.append((block_name, concatenated))

            logger.info(f"[{task_id}] Prepared {len(base_videos)} base videos")

            logger.info(f"[{task_id}] Step 2: Downloading background audio")
            audio_files = await self.download_all_audio(audio_urls, temp_dir)

            logger.info(f"[{task_id}] Step 3: Generating TTS")
            tts_files = await self.generate_all_tts(voice_configs, temp_dir)

            logger.info(f"[{task_id}] Step 4: Creating audio mixes")
            mixed_audio_files = await self.create_audio_mixes(audio_files, tts_files, temp_dir)

            total_variants = len(base_videos) * len(mixed_audio_files)
            results["total"] = total_variants

            logger.info(f"[{task_id}] Step 5: Generating {total_variants} final videos")

            if progress_callback:
                await progress_callback(0, total_variants)

            completed = 0
            semaphore = asyncio.Semaphore(self.config.max_concurrent_jobs)
            loop = asyncio.get_event_loop()

            async def generate_final_video(block_name, base_video, mixed_audio, variant_num):
                nonlocal completed
                async with semaphore:
                    variant_id = f"{task_id}_{block_name}_v{variant_num}"
                    local_output_path = temp_dir / f"{variant_id}.mp4"

                    # Generate video locally
                    success = await loop.run_in_executor(
                        None,
                        self.add_audio_to_video,
                        base_video,
                        mixed_audio,
                        local_output_path
                    )

                    if success:
                        gcs_path = f"{task_id}/{variant_id}.mp4"
                        url = await loop.run_in_executor(
                            None,
                            self.gcs_service.upload_file,
                            local_output_path,
                            gcs_path
                        )

                        if url:
                            results["successful"].append({f"{variant_id}_url": url})
                            logger.info(f"Uploaded {variant_id}.mp4 to GCS: {url}")
                        else:
                            results["failed"].append(variant_id)
                            logger.error(f"Failed to upload {variant_id}.mp4 to GCS")

                        local_output_path.unlink(missing_ok=True)
                    else:
                        results["failed"].append(variant_id)
                        logger.error(f"Failed to generate {variant_id}.mp4")

                    completed += 1
                    if progress_callback:
                        await progress_callback(completed, total_variants)

                    return success

            tasks = []
            variant_counter = 0

            for block_name, base_video in base_videos:
                for mixed_audio in mixed_audio_files:
                    variant_counter += 1
                    task = generate_final_video(block_name, base_video, mixed_audio, variant_counter)
                    tasks.append(task)

            await asyncio.gather(*tasks, return_exceptions=True)

            logger.info(f"[{task_id}] Cleaning up...")
            shutil.rmtree(temp_dir, ignore_errors=True)

            logger.info(f"[{task_id}] Completed: {len(results['successful'])}/{total_variants}")
            logger.info(f"[{task_id}] Uploaded {len(results['successful'])} videos to GCS")

        except Exception as e:
            logger.error(f"[{task_id}] Generation failed: {e}", exc_info=True)
            results["error"] = str(e)

        return results

