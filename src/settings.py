from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    elevenlabs_api_key: str
    output_dir: Path = Path("./generated_videos")
    max_concurrent_jobs: int = 3
    download_timeout: int = 300
    background_audio_volume: float = 0.2
    voice_audio_volume: float = 0.8
    elevenlabs_model: str = "eleven_flash_v2_5"
    tts_stability: float = 0.5
    tts_similarity_boost: float = 0.75

    google_credentials_path: str
    gcs_bucket_name: str
    gcs_output_folder: str = "videos"

    class Config:
        env_file = ".env"


settings = Settings()
settings.output_dir.mkdir(exist_ok=True)
