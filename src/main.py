import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.settings import settings
from .routes import router, set_generator
from .services.tts import TTSService
from .services.generator import VideoGenerator
from .services.storage_service import GCSUploadService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="Video Generation Service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tts_service = TTSService(
    api_key=settings.elevenlabs_api_key,
    model=settings.elevenlabs_model,
    stability=settings.tts_stability,
    similarity_boost=settings.tts_similarity_boost
)

storage_service = GCSUploadService()
generator = VideoGenerator(tts_service, storage_service, settings)
set_generator(generator)

app.include_router(router)
