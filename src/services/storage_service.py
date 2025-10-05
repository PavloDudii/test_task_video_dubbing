import logging
from pathlib import Path
from google.cloud import storage
from typing import Optional
from src.settings import settings

logger = logging.getLogger(__name__)


class GCSUploadService:
    def __init__(self):
        credentials_path = settings.google_credentials_path

        if credentials_path and Path(credentials_path).exists():
            self.client = storage.Client.from_service_account_json(credentials_path)
            logger.info(f"GCS Client initialized")
        else:
            self.client = storage.Client()

        self.bucket = self.client.bucket(settings.gcs_bucket_name)
        logger.info(f"GCS Service initialized for bucket: {settings.gcs_bucket_name}")

    def upload_file(
            self,
            local_path: Path,
            destination_blob_name: str,
            content_type: str = "video/mp4"
    ) -> Optional[str]:

        try:
            blob = self.bucket.blob(destination_blob_name)
            blob.chunk_size = 5 * 1024 * 1024
            blob.upload_from_filename(str(local_path),
                                      content_type=content_type,
                                      timeout=300,
                                      retry=None)
            public_url = f"https://storage.googleapis.com/{self.bucket.name}/{destination_blob_name}"

            logger.info(f"Uploaded {local_path.name} to {destination_blob_name}")
            return public_url

        except Exception as e:
            logger.error(f"Failed to upload {local_path}: {e}")
            return None

    def delete_file(self, blob_name: str) -> bool:
        """Delete a file from GCS bucket"""
        try:
            blob = self.bucket.blob(blob_name)
            blob.delete()
            logger.info(f"Deleted {blob_name} from GCS")
            return True
        except Exception as e:
            logger.error(f"Failed to delete {blob_name}: {e}")
            return False