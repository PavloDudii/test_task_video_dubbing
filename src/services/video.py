import subprocess
import tempfile
import logging
import json
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def get_video_info(video_path: Path) -> Dict[str, Any]:
    """Get detailed video properties using ffprobe"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        video_stream = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
        audio_stream = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)

        info = {
            'duration': float(data['format'].get('duration', 0)),
            'size': int(data['format'].get('size', 0)),
            'video_codec': video_stream.get('codec_name') if video_stream else None,
            'width': video_stream.get('width') if video_stream else None,
            'height': video_stream.get('height') if video_stream else None,
            'fps': eval(video_stream.get('r_frame_rate', '0/1')) if video_stream else 0,
            'audio_codec': audio_stream.get('codec_name') if audio_stream else None,
            'sample_rate': audio_stream.get('sample_rate') if audio_stream else None,
        }

        logger.info(f"Video info for {video_path.name}: {info}")
        return info

    except Exception as e:
        logger.error(f"Failed to get video info for {video_path}: {e}")
        return {}


def check_videos_compatible(video_paths: List[Path]) -> bool:
    """Check if videos have compatible properties for concat demuxer"""
    if len(video_paths) < 2:
        return True

    infos = [get_video_info(vp) for vp in video_paths]

    first = infos[0]
    for i, info in enumerate(infos[1:], 1):
        if info.get('video_codec') != first.get('video_codec'):
            logger.warning(f"Video {i} has different codec: {info.get('video_codec')} vs {first.get('video_codec')}")
            return False
        if info.get('width') != first.get('width') or info.get('height') != first.get('height'):
            logger.warning(
                f"Video {i} has different resolution: {info.get('width')}x{info.get('height')} vs {first.get('width')}x{first.get('height')}")
            return False
        if abs(info.get('fps', 0) - first.get('fps', 0)) > 0.01:
            logger.warning(f"Video {i} has different fps: {info.get('fps')} vs {first.get('fps')}")
            return False

    logger.info("All videos are compatible for concat demuxer")
    return True


def concatenate_videos(video_paths: List[Path], output_path: Path) -> bool:
    """
    Concatenate videos - tries multiple methods for reliability
    """
    if not video_paths:
        logger.error("No video paths provided")
        return False

    logger.info(f"Starting concatenation of {len(video_paths)} videos")
    for i, vp in enumerate(video_paths):
        logger.info(f"Video {i + 1}: {vp.name}")
        if not vp.exists():
            logger.error(f"Video not found: {vp}")
            return False

    if len(video_paths) == 1:
        import shutil
        shutil.copy2(video_paths[0], output_path)
        logger.info("Single video - copied directly")
        return True

    compatible = check_videos_compatible(video_paths)

    if compatible:
        logger.info("Attempting concat demuxer (fast, no re-encoding)")
        if concatenate_with_demuxer(video_paths, output_path):
            return True
        logger.warning("Demuxer failed, trying re-encoding...")
    else:
        logger.info("Videos not compatible, using re-encoding method")

    return concatenate_with_filter(video_paths, output_path)


def concatenate_with_demuxer(video_paths: List[Path], output_path: Path) -> bool:
    """Method 1: Concat demuxer (fastest, no quality loss)"""
    concat_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as f:
            for vpath in video_paths:
                abs_path = str(vpath.absolute()).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
            concat_file = f.name

        logger.info(f"Created concat file: {concat_file}")

        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',
            '-y', str(output_path)
        ]

        logger.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, capture_output=True, text=True, check=True)

        if concat_file:
            Path(concat_file).unlink(missing_ok=True)

        if output_path.exists():
            output_info = get_video_info(output_path)
            logger.info(f"Demuxer concatenation successful - Output duration: {output_info.get('duration')}s")
            return True
        else:
            logger.error("Output file not created")
            return False

    except subprocess.CalledProcessError as e:
        logger.error(f"Demuxer failed: {e.stderr}")
        if concat_file:
            Path(concat_file).unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error in demuxer: {e}")
        if concat_file:
            Path(concat_file).unlink(missing_ok=True)
        return False


def concatenate_with_filter(video_paths: List[Path], output_path: Path) -> bool:
    """Method 2: Filter complex (re-encodes, most reliable)"""
    try:
        n = len(video_paths)
        logger.info(f"Using filter_complex for {n} videos")

        first_info = get_video_info(video_paths[0])
        target_width = first_info.get('width', 1080)
        target_height = first_info.get('height', 1920)
        logger.info(f"Target resolution: {target_width}x{target_height}")

        inputs = []
        for vpath in video_paths:
            inputs.extend(['-i', str(vpath)])

        scaled_parts = []
        for i in range(n):
            scaled_parts.append(
                f'[{i}:v:0]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,'
                f'pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];'
            )
            scaled_parts.append(f'[{i}:a:0]aformat=sample_rates=48000:channel_layouts=stereo[a{i}];')

        concat_inputs = ''.join([f'[v{i}][a{i}]' for i in range(n)])
        filter_complex = ''.join(scaled_parts) + f'{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]'

        cmd = [
            'ffmpeg',
            *inputs,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-movflags', '+faststart',
            '-y', str(output_path)
        ]

        logger.info(f"Running filter_complex concatenation with scaling")
        subprocess.run(cmd, capture_output=True, text=True, check=True)

        if output_path.exists():
            output_info = get_video_info(output_path)
            expected_duration = sum(get_video_info(vp).get('duration', 0) for vp in video_paths)
            logger.info(f"Filter concatenation successful")
            logger.info(f"Expected duration: {expected_duration:.2f}s, Got: {output_info.get('duration', 0):.2f}s")
            return True
        else:
            logger.error("Output file not created")
            return False

    except subprocess.CalledProcessError as e:
        logger.error(f"Filter concatenation failed: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in filter concatenation: {e}")
        return False


def concatenate_with_ts_conversion(video_paths: List[Path], output_path: Path) -> bool:
    """Method 3: Convert to TS then concat (most compatible, slower)"""
    temp_ts_files = []
    try:
        logger.info("Converting videos to MPEG-TS format for concatenation")

        for i, vpath in enumerate(video_paths):
            ts_file = output_path.parent / f"temp_{i}_{vpath.stem}.ts"
            cmd = [
                'ffmpeg',
                '-i', str(vpath),
                '-c', 'copy',
                '-bsf:v', 'h264_mp4toannexb',
                '-f', 'mpegts',
                '-y', str(ts_file)
            ]

            logger.info(f"Converting {vpath.name} to TS format")
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            temp_ts_files.append(ts_file)

        concat_input = '|'.join(str(ts) for ts in temp_ts_files)
        cmd = [
            'ffmpeg',
            '-i', f'concat:{concat_input}',
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y', str(output_path)
        ]

        logger.info("Concatenating TS files")
        subprocess.run(cmd, capture_output=True, text=True, check=True)

        for ts_file in temp_ts_files:
            ts_file.unlink(missing_ok=True)

        if output_path.exists():
            output_info = get_video_info(output_path)
            logger.info(f"TS concatenation successful - Output duration: {output_info.get('duration')}s")
            return True
        else:
            logger.error("Output file not created")
            return False

    except Exception as e:
        logger.error(f"TS concatenation failed: {e}")
        for ts_file in temp_ts_files:
            ts_file.unlink(missing_ok=True)
        return False


def add_audio_tracks(
        video_path: Path,
        background_audio_path: Path,
        voice_audio_path: Path,
        output_path: Path,
        background_volume: float,
        voice_volume: float
) -> bool:
    """Add background music and voice audio to video"""
    try:
        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return False
        if not background_audio_path.exists():
            logger.error(f"Background audio not found: {background_audio_path}")
            return False
        if not voice_audio_path.exists():
            logger.error(f"Voice audio not found: {voice_audio_path}")
            return False

        logger.info(f"Adding audio tracks to {video_path.name}")
        logger.info(f"Background volume: {background_volume}, Voice volume: {voice_volume}")

        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-stream_loop', '-1', '-i', str(background_audio_path),
            '-i', str(voice_audio_path),
            '-filter_complex',
            f'[1:a]volume={background_volume}[bg];'
            f'[2:a]volume={voice_volume}[vc];'
            f'[bg][vc]amix=inputs=2:duration=first:dropout_transition=2[aout]',
            '-map', '0:v',
            '-map', '[aout]',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-shortest',
            '-y', str(output_path)
        ]

        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Successfully added audio tracks")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to add audio: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error adding audio: {e}")
        return False