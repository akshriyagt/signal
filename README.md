# Signal — Call Recording Analyzer

A local web app that takes call recordings (single or multiple, any spoken
language), transcribes them, and classifies each one as **Spam**,
**Important**, or **Normal** — with a one-click **Delete / Archive / Keep**
action for every result. Runs entirely on `localhost`; no audio ever leaves
your machine.

---

## 1. What it does

1. Drag & drop (or pick) one or many call recordings — MP3, WAV, M4A, OGG,
   AAC, FLAC, WMA, OPUS.
2. Each file is transcribed locally with **faster-whisper**, which also
   **auto-detects the spoken language** (English, Tamil, Hindi, Telugu,
   Kannada, Malayalam, and 90+ others — no need to tell it which language a
   call is in). Detection scans multiple windows of the call (after
   stripping silence/ringing/hold-music with VAD) rather than trusting a
   single 30-second guess, and flags calls that are actually code-mixed
   (e.g. Hindi+English) instead of forcing them into one label — see
   `language_breakdown` / `is_mixed_language` / `language_low_confidence`
   in the result JSON below.
3. A transparent, multilingual **keyword-based classifier** reads the
   transcript and labels the call:
   - 🔴 **Spam** — loan/lottery/OTP/KYC/prize-style scam language
   - 🟡 **Important** — urgent/doctor/hospital/meeting/deadline-style language
   - 🟢 **Normal** — everything else
   Every verdict shows exactly which keywords triggered it, so it's never a
   black box.
4. Every result is a card with the detected language, duration, confidence,
   a transcript snippet, and three actions:
   - **Delete** → removes the recording and its result permanently
   - **Archive** → moves the recording into `data/archive/` and marks it archived
   - **Keep** → marks it kept, recording stays in `data/uploads/`
   A **Clear** button wipes all pending (non-archived) results in one go.
5. **Download JSON** exports every analyzed call as a single structured
   JSON file (`call_analysis_results.json`).

> **Note on speed:** true speech-to-text on a real audio file cannot happen
> in a literal fraction of a second — the model has to actually listen to
> the recording. On a normal laptop CPU the default `base` model processes
> audio at roughly 5-10x real-time (a 1-minute call finishes in about
> 6-12 seconds). If you want it faster (at some accuracy cost), run with
> `WHISPER_MODEL=tiny` — see below. Once transcribed, the classification
> step itself is instant.

---

## 2. Setup

Requires **Python 3.9+**.

```bash
cd call-analyzer
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

The first run downloads the whisper model (a few hundred MB) from
Hugging Face automatically — you need internet access for that *one time*
only. After that, everything runs fully offline.

---

## 3. Run

```bash
python app.py
```

Open your browser at:

```
http://127.0.0.1:5000
```

To use a smaller/faster or larger/more-accurate model:

```bash
# fastest, least accurate
WHISPER_MODEL=tiny python app.py

# default
WHISPER_MODEL=base python app.py

# slower, more accurate — good for noisy calls
WHISPER_MODEL=small python app.py
```

(On Windows PowerShell: `$env:WHISPER_MODEL="tiny"; python app.py`)

---

## 4. Project structure

```
call-analyzer/
├── app.py                  Flask backend + transcription + classification
├── requirements.txt
├── templates/
│   └── index.html          Single-page UI
├── static/
│   ├── css/style.css
│   └── js/script.js
├── data/
│   ├── uploads/             recordings currently pending / kept
│   ├── archive/             recordings you archived
│   └── results/             one JSON file per analyzed call
└── README.md
```

## 5. Result JSON shape

```json
{
  "id": "b1e2...",
  "filename": "call_2026_07_09.mp3",
  "language": "ta",
  "language_probability": 0.94,
  "language_low_confidence": false,
  "language_breakdown": [
    { "language": "ta", "share": 0.75, "avg_probability": 0.91 },
    { "language": "en", "share": 0.25, "avg_probability": 0.68 }
  ],
  "is_mixed_language": true,
  "duration_seconds": 42.7,
  "transcript": "...",
  "category": "spam",
  "confidence": 0.9,
  "matched_keywords": ["லாட்டரி", "பரிசு"],
  "analyzed_at": "2026-07-09T10:12:44.120Z",
  "status": "pending"
}
```

## 6. Extending it

- **More languages / better accuracy**: add more keyword phrases to
  `SPAM_KEYWORDS` / `IMPORTANT_KEYWORDS` in `app.py`.
- **Smarter classification**: swap the keyword classifier in `classify()`
  for a call to any LLM API of your choice — the transcript is already
  extracted and ready to hand off.
- **Bulk folder import**: point a script at a folder of recordings and
  `POST` them to `/api/analyze` in batches if you don't want to use the UI.
