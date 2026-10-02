# Copywaste Audionotes

A little app i use to quickly record audionotes to myself, make a transcription of it and if there's date/times present, schedule it in my Google Calendar. 


- Android app
- HTML-frontend (hosted at notes.copywaste.org)
- Web API backend in Python doing the transliteration and calendar-scheduling


## Install

### Backend

Needs Python 3.12 and `ffmpeg` (its `ffprobe` measures note durations).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
scripts/dev.sh                    # serves on http://127.0.0.1:8000
```

Copy `deploy/.env.example` to `deploy/.env` and fill in the Google OAuth
values — Google sign-in is the only way to log in.

Title summarization (Ollama) and date recognition (Duckling) are optional —
without them notes still transcribe, they just get a fallback title and no
`scheduledAt`:

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml up -d ollama duckling
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml exec ollama ollama pull llama3.2:3b
```

Run the tests with `pytest`. For deployment see `deploy/systemd/` (bare
metal) or `deploy/docker-compose.yml` (Docker).

### Android app

Needs JDK 17 and the Android SDK (>26 - Android 8). Point Gradle at the SDK in `src/local.properties`:
```properties
sdk.dir=/Users/you/Library/Android/sdk
```

Build and install onto a connected device (check it's visible with `adb devices`):

```bash
cd src
./gradlew :app:installDebug
```

Or build the APK and install it separately:

```bash
cd src
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

 On first launch, set the backend URL and sign in from
the app's Settings screen.
