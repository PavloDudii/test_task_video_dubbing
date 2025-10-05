# Video Generator Service

Automated video generation service that concatenates video blocks, generates text-to-speech audio, mixes audio tracks, and uploads final videos to Google Cloud Storage.

## Prerequisites

- **Docker** and **Docker Compose**
- **Google Cloud Storage** bucket
- **ElevenLabs API key** (for text-to-speech)
- **GCS Service Account** credentials JSON file

## Environment Configuration

Create a `.env` file in the project root:

```env
# ElevenLabs TTS
ELEVEN_LABS_API_KEY=your_elevenlabs_api_key_here

# Google Cloud Storage
GCS_BUCKET_NAME=your-bucket-name
# GOOGLE_CREDENTIALS_PATH=/src/secrets/your-credentials.json

```

### Getting Credentials

**ElevenLabs API Key:**
1. Sign up at [elevenlabs.io](https://elevenlabs.io)
2. Go to Profile → API Keys
3. Copy your API key

**Google Cloud Storage:**
1. Create a GCS bucket in [Google Cloud Console](https://console.cloud.google.com)
2. Create a service account with "Storage Object Admin" role
3. Download the JSON key file
4. Either:
   - place file in `secrets/` folder and set `GOOGLE_CREDENTIALS_PATH`

## Running with Docker

### Build and Start Docker

```bash
# Build the image
docker compose build

# Start the service
docker compose up -d

# View logs
docker compose logs -f

# Stop the service
docker compose down
```

The API will be available at `http://localhost:8000`

## API Endpoints

### 1. Generate Videos

**POST** `/generate`

Start a video generation task. Creates all combinations of video blocks × audio × voice configurations.

**Request Body:**
```json
{
  "task_name": "my_video_campaign",
  "block1": [
    "https://storage.googleapis.com/bucket/video1.mp4",
    "https://storage.googleapis.com/bucket/video2.mp4",
    "https://storage.googleapis.com/bucket/video3.mp4"
  ],
  "block2": [
    "https://storage.googleapis.com/bucket/video4.mp4"
  ],
  "audio1": [
    "https://storage.googleapis.com/bucket/background1.mp3",
    "https://storage.googleapis.com/bucket/background2.mp3"
  ],
  "voice1": [
    {
      "text": "Welcome to our platform. This is the first voice segment.",
      "voice": "Sarah"
    },
    {
      "text": "Here's more information about our service.",
      "voice": "George"
    }
  ]
}
```

**Fields:**
- `task_name` (required): Identifier for this generation task
- `block1`, `block2`, `block3`, ... : Arrays of video URLs to concatenate
  - Videos in each block will be concatenated in order
  - Different resolutions are automatically normalized
- `audio1`, `audio2`, ... : Arrays of background audio URLs
- `voice1`, `voice2`, ... : Arrays of voice-over configurations
  - `text`: The text to convert to speech
  - `voice`: ElevenLabs voice name (e.g., "Sarah", "George", "Will", "Rachel")

**Response:**
```json
{
  "task_id": "93fed755-715c-4b3f-a6a8-5cd2b93622ea",
  "status": "queued",
  "message": "Generation started"
}
```

**Output:**
- Total videos = (number of blocks) × (number of audio) × (number of voices)
- Example: 2 blocks × 2 audio × 2 voices = 8 final videos
- All videos uploaded to GCS bucket at `generated_videos/{task_id}_{block}_v{variant}.mp4`

---

### 2. Check Task Status

**GET** `/status/{task_id}`

Monitor the progress of a generation task.

**Response:**
```json
{
  "task_id": "93fed755-715c-4b3f-a6a8-5cd2b93622ea",
  "task_name": "my_video_campaign",
  "status": "processing",
  "progress": 62.5,
  "completed": 5,
  "total": 8,
  "results": [
    "https://storage.googleapis.com/bucket/generated_videos/task_block1_v1.mp4",
    "https://storage.googleapis.com/bucket/generated_videos/task_block1_v2.mp4"
  ],
  "created_at": "2025-10-05T20:28:59.581000",
  "completed_at": null,
  "error": null
}
```

**Status values:**
- `queued`: Task accepted, waiting to start
- `processing`: Currently generating videos
- `completed`: All videos generated successfully
- `failed`: Task failed with error

---

### 3. Get Results

**GET** `/results/{task_id}`

Retrieve final results for a completed task.

**Response:**
```json
{
  "task_id": "93fed755-715c-4b3f-a6a8-5cd2b93622ea",
  "task_name": "my_video_campaign",
  "total_variants": 8,
  "successful": 8,
  "failed": 0,
  "files": [
    {
      "url": "https://storage.googleapis.com/bucket/generated_videos/task_block1_v1.mp4"
    },
    {
      "url": "https://storage.googleapis.com/bucket/generated_videos/task_block1_v2.mp4"
    }
  ]
}
```

---

### 4. Delete Task

**DELETE** `/task/{task_id}`

Remove task from memory (does not delete GCS files).

**Response:**
```json
{
  "message": "Task deleted",
  "task_id": "93fed755-715c-4b3f-a6a8-5cd2b93622ea"
}
```

## Example Workflow

```bash
# 1. Start generation
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "campaign_q1",
    "block1": ["https://example.com/video1.mp4", "https://example.com/video2.mp4"],
    "audio1": ["https://example.com/music.mp3"],
    "voice1": [{"text": "Hello world", "voice": "Sarah"}]
  }'

# Response: {"task_id": "abc-123", "status": "queued"}

# 2. Check progress
curl http://localhost:8000/status/abc-123

# 3. Get results when complete
curl http://localhost:8000/results/abc-123
```

## Video Processing Pipeline

1. **Download**: All video and audio files downloaded to temporary directory
2. **Concatenate**: Videos in each block concatenated (different resolutions normalized)
3. **Generate TTS**: Text converted to speech using ElevenLabs
4. **Mix Audio**: Background audio mixed with voice-over
5. **Add Audio to Video**: Mixed audio added to each video block
6. **Upload**: Final videos uploaded to GCS
7. **Cleanup**: Temporary files deleted

## License

MIT