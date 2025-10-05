import logging
from pathlib import Path
from typing import Optional, Dict
from elevenlabs.client import ElevenLabs

logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self, api_key: str, model: str, stability: float, similarity_boost: float):
        self.api_key = api_key
        self.model = model
        self.stability = stability
        self.similarity_boost = similarity_boost
        self._voices_cache: Optional[Dict[str, str]] = None
        self.client = ElevenLabs(api_key=api_key) if api_key else None

    def get_available_voices(self) -> Dict[str, str]:
        if self._voices_cache:
            return self._voices_cache

        if not self.client:
            logger.warning("ElevenLabs client not initialized")
            return {}

        try:
            voices_response = self.client.voices.get_all()
            voices = {v.name: v.voice_id for v in voices_response.voices}
            self._voices_cache = voices
            logger.info(f"Loaded {len(voices)} voices from ElevenLabs")
            return voices
        except Exception as e:
            logger.error(f"Error fetching voices: {e}")
            return {}

    def get_voice_id(self, voice_name: str) -> Optional[str]:
        voices = self.get_available_voices()

        if not voices:
            logger.error("No voices available from ElevenLabs")
            return None

        voice_id = voices.get(voice_name)

        if not voice_id:
            logger.warning(f"Voice '{voice_name}' not found. Available: {list(voices.keys())[:5]}")
            voice_id = list(voices.values())[0]
            logger.info(f"Using fallback voice: {list(voices.keys())[0]}")

        return voice_id

    def generate_speech(self, text: str, voice: str, output_path: Path) -> bool:
        if not self.client:
            logger.error("ElevenLabs API key not set")
            return False

        voice_id = self.get_voice_id(voice)
        if not voice_id:
            logger.error(f"Cannot resolve voice: {voice}")
            return False

        try:
            audio_generator = self.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=self.model,
                output_format="mp3_44100_128",
                voice_settings={
                    "stability": self.stability,
                    "similarity_boost": self.similarity_boost
                }
            )

            with open(output_path, 'wb') as f:
                for chunk in audio_generator:
                    f.write(chunk)

            logger.info(f"Generated TTS: {output_path.name}")
            return True

        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            return False