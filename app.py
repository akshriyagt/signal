"""
Call Recording Analyzer - local Flask backend.
Transcribes call recordings (any language) with faster-whisper,
classifies each call as spam / important / normal using multilingual
keyword heuristics, and exposes a small REST API consumed by the
single-page frontend in templates/index.html.

Run:
    python app.py
Then open:
    http://127.0.0.1:5000
"""

import os
import re
import csv
import io
import json
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
RESULTS_DIR = os.path.join(DATA_DIR, "results")

for d in (UPLOAD_DIR, ARCHIVE_DIR, RESULTS_DIR):
    os.makedirs(d, exist_ok=True)

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac", ".wma", ".opus", ".mp4"}

# ---------------------------------------------------------------------------
# Speech-to-text model (faster-whisper). Auto-detects the spoken language,
# works with mixed multilingual audio, and runs fully offline on CPU after
# the first model download.
#
# Model size can be overridden with an environment variable, e.g.
#   WHISPER_MODEL=tiny python app.py     -> fastest, least accurate
#   WHISPER_MODEL=small python app.py    -> slower, more accurate
# ---------------------------------------------------------------------------
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.audio import decode_audio  # noqa: E402
from faster_whisper.vad import VadOptions, get_speech_timestamps, collect_chunks  # noqa: E402

# "base" is fast but its language-ID head confuses closely-related languages
# often enough (Tamil/Telugu/Kannada/Malayalam, Hindi/Urdu, etc.) to be
# unreliable for real call recordings. "small" is still comfortably fast on
# CPU and is a large step up in multilingual accuracy, so it's now the
# default. Override with WHISPER_MODEL=base/tiny if you need more speed.
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")
print(f"[call-analyzer] loading faster-whisper model '{MODEL_SIZE}' ...")
# cpu_threads: use all available cores instead of the library default (4),
# which noticeably speeds up long recordings on modern multi-core laptops.
model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8", cpu_threads=os.cpu_count())
print("[call-analyzer] model ready.")

# Minimum probability below which we consider the detected language
# untrustworthy rather than silently presenting it as fact.
LANGUAGE_CONFIDENCE_FLOOR = 0.5

# ---------------------------------------------------------------------------
# Multilingual keyword banks used for classification.
# These are intentionally simple + transparent (no black-box scoring) so the
# reasoning behind every verdict is inspectable in the JSON output.
# Extend these lists freely for more languages / more precision.
# ---------------------------------------------------------------------------
SPAM_KEYWORDS = [
    # English
    "loan", "credit card", "lottery", "you have won", "you've won",
    "congratulations you have been selected", "otp", "kyc", "extended warranty",
    "warranty expired", "insurance policy", "investment opportunity",
    "guaranteed returns", "claim your prize", "account blocked", "click the link",
    "free gift", "act now", "limited time offer", "processing fee",
    "cashback offer", "pre-approved", "personal loan", "credit limit",
    "casino", "crypto investment", "double your money",
    # Hindi
    "लोन", "लॉटरी", "बीमा", "उपहार", "जीत गए", "ओटीपी", "केवाईसी",
    "मुफ्त उपहार", "इनाम", "क्रेडिट कार्ड",
    # Tamil
    "கடன்", "பரிசு", "காப்பீடு", "லாட்டரி", "இலவச பரிசு", "வெற்றி பெற்றீர்கள்",
    "கிரெடிட் கார்டு",
    # Telugu
    "రుణం", "లాటరీ", "బీమా", "బహుమతి", "క్రెడిట్ కార్డు",
    # Kannada
    "ಸಾಲ", "ಲಾಟರಿ", "ವಿಮೆ", "ಬಹುಮಾನ", "ಕ್ರೆಡಿಟ್ ಕಾರ್ಡ್",
    # Malayalam
    "വായ്പ", "ലോട്ടറി", "ഇൻഷുറൻസ്", "സമ്മാനം", "ക്രെഡിറ്റ് കാർഡ്",
]

IMPORTANT_KEYWORDS = [
    # English
    "urgent", "emergency", "doctor", "hospital", "accident", "meeting",
    "boss", "interview", "appointment", "deadline", "police", "court",
    "family emergency", "surgery", "asap", "client", "project", "manager",
    "reschedule", "flight", "exam", "results",
    # Hindi
    "जरूरी", "आपातकाल", "डॉक्टर", "अस्पताल", "दुर्घटना", "बैठक", "साक्षात्कार",
    "पुलिस", "अदालत",
    # Tamil
    "அவசரம்", "மருத்துவர்", "மருத்துவமனை", "விபத்து", "கூட்டம்", "நேர்காணல்",
    "காவல்துறை",
    # Telugu
    "అత్యవసరం", "వైద్యుడు", "ఆసుపత్రి", "ప్రమాదం", "సమావేశం",
    # Kannada
    "ತುರ್ತು", "ವೈದ್ಯರು", "ಆಸ್ಪತ್ರೆ", "ಅಪಘಾತ", "ಸಭೆ",
    # Malayalam
    "അടിയന്തിരം", "ഡോക്ടർ", "ആശുപത്രി", "അപകടം", "മീറ്റിംഗ്",
    # Bengali
    "ঋণ", "লটারি", "বীমা", "উপহার", "জরুরি", "ডাক্তার", "হাসপাতাল",
    # Marathi
    "कर्ज", "लॉटरी", "विमा", "भेट", "तातडीचे", "डॉक्टर", "रुग्णालय",
    # Gujarati
    "લોન", "લોટરી", "વીમો", "ભેટ", "તાત્કાલિક", "ડોક્ટર", "હોસ્પિટલ",
    # Punjabi
    "ਕਰਜ਼ਾ", "ਲਾਟਰੀ", "ਬੀਮਾ", "ਤੋਹਫ਼ਾ", "ਜ਼ਰੂਰੀ", "ਡਾਕਟਰ", "ਹਸਪਤਾਲ",
    # Urdu
    "قرض", "لاٹری", "بیمہ", "تحفہ", "ضروری", "ڈاکٹر", "ہسپتال",
]

# ---------------------------------------------------------------------------
# Language-agnostic pattern signals. Keyword lists only cover the languages
# they were written for, so a call in a language none of the banks include
# would otherwise fall back to "normal" no matter what it actually contains.
# These regexes catch spam "shape" (links, long digit strings read out as
# account/OTP numbers, currency mentions) regardless of spoken language, so
# classification stays reasonably accurate even on unlisted languages.
# ---------------------------------------------------------------------------
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:com|in|org|net)\b)", re.IGNORECASE)
LONG_DIGIT_PATTERN = re.compile(r"\b\d{6,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?\d{10}\b")
CURRENCY_PATTERN = re.compile(r"(₹|rs\.?\s?\d|\$\s?\d|inr\s?\d|\d+\s?(?:rupees|lakh|crore|percent|%))", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Robocall / scam-script signals.
#
# Keyword lists only catch a scam if it happens to use one of the exact
# listed words (loan, lottery, OTP, ...). In practice most real robocalls
# never say any of those — they follow well-known IVR/scam *scripts*
# instead ("press 1 to authorize", "no one has signed for it", "I'm a
# robot, please state the legal name of the entity responsible for this
# call" — that last one is literally the FCC-mandated robocall disclosure
# line). These regexes catch that *shape* of call regardless of the
# specific product/company named, which is what was missing before.
# ---------------------------------------------------------------------------
ROBOCALL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"press\s*(one|1|two|2|three|3|zero|0)\b",
        r"do not authorize",
        r"to authorize (this|your) (order|payment|transaction|purchase)",
        r"if you did not (make|authorize|place)",
        r"this is an? automated (call|message|voice)",
        r"i'?m a robot",
        r"legal name of the entity responsible",
        r"this is not a solicitation",
        r"final (notice|warning)",
        r"last (time|notice) we will (inform|contact|notify)",
        r"(parcel|package|shipment).{0,25}(delivered|held|customs|undeliver)",
        r"no one (has )?signed for it",
        r"(account|card|number)\s*(has been|is|was)\s*(suspended|blocked|locked|compromised|deactivated)",
        r"verify your (identity|account|information|details)",
        r"social security (number|administration)",
        r"internal revenue service|\birs\b",
        r"student loan forgiveness",
        r"extended (car |auto )?warranty",
        r"medicare (benefits|coverage|eligib)",
        r"stay on the line",
        r"do not hang up",
        r"calling (on behalf of|regarding) your (car|vehicle)",
        r"arrest warrant",
        r"suspend(ed)? your (number|sim|service)",
        r"one time password|otp",
    ]
]


def detect_robocall_patterns(text: str):
    hits = []
    for pattern in ROBOCALL_PATTERNS:
        m = pattern.search(text)
        if m:
            hits.append(m.group(0).lower())
    return hits


def extract_signals(text: str) -> dict:
    """Pull language-agnostic, structural signals out of a transcript."""
    urls = URL_PATTERN.findall(text)
    phones = PHONE_PATTERN.findall(text)
    long_digits = LONG_DIGIT_PATTERN.findall(text)
    currency_hits = CURRENCY_PATTERN.findall(text)
    robocall_hits = detect_robocall_patterns(text)
    return {
        "has_link": bool(urls),
        "phone_numbers": sorted(set(phones))[:5],
        "has_long_number": bool(long_digits),
        "mentions_money": bool(currency_hits),
        "robocall_patterns": robocall_hits,
    }


def detect_language_breakdown(filepath: str, window_seconds: int = 30, max_windows: int = 8):
    """
    Whisper's built-in auto-detect only looks at the language(s) present in
    however much audio `language_detection_segments` covers, then commits to
    ONE label for the entire file. That's the main source of wrong/unstable
    results here:
      - a call that opens with ringing, hold music, or an IVR greeting in a
        different language than the actual conversation skews detection,
      - code-switched calls (e.g. Hindi/English, Tamil/English) genuinely
        contain more than one language, so a single label is always partly
        wrong for those,
      - closely-related languages (Tamil/Telugu/Kannada/Malayalam, Hindi/
        Urdu) are the cases the model is least confident about, and a single
        30s window doesn't give it much to go on.

    This scans the call in successive windows (after stripping silence with
    VAD) and returns a share-weighted breakdown of every language detected,
    so a code-mixed call is reported as such instead of forced into one
    bucket, and a mis-detected single language is easier to spot/inspect.
    """
    sampling_rate = model.feature_extractor.sampling_rate
    audio = decode_audio(filepath, sampling_rate=sampling_rate)

    speech_chunks = get_speech_timestamps(audio, VadOptions())
    if speech_chunks:
        audio = collect_chunks(audio, speech_chunks)

    if audio.shape[0] < sampling_rate:  # less than 1s of actual speech
        return []

    window_samples = window_seconds * sampling_rate
    max_frames = model.feature_extractor.nb_max_frames
    num_windows = min(max_windows, max(1, -(-audio.shape[0] // window_samples)))

    votes = []
    for i in range(num_windows):
        start = i * window_samples
        chunk = audio[start:start + window_samples]
        if chunk.shape[0] < sampling_rate:
            continue
        features = model.feature_extractor(chunk)[:, :max_frames]
        encoder_output = model.encode(features)
        results = model.model.detect_language(encoder_output)[0]
        lang, prob = results[0][0][2:-2], results[0][1]
        votes.append((lang, prob))

    if not votes:
        return []

    confident_votes = [v for v in votes if v[1] >= LANGUAGE_CONFIDENCE_FLOOR] or votes
    counts = Counter(lang for lang, _ in confident_votes)
    total = sum(counts.values())

    breakdown = [
        {
            "language": lang,
            "share": round(count / total, 2),
            "avg_probability": round(
                sum(p for l, p in confident_votes if l == lang) / count, 3
            ),
        }
        for lang, count in counts.most_common()
    ]
    return breakdown


def classify(text: str, signals: dict):
    """
    Rule-based, multilingual, fully transparent classifier.

    Keyword hits carry the classification whenever the call's language is
    covered by SPAM_KEYWORDS / IMPORTANT_KEYWORDS. Structural signals (link,
    long digit string read out loud, money mentions) and robocall/scam
    *script* patterns (IVR "press 1", fake authorization prompts, package-
    scam phrasing, the FCC robocall disclosure line, etc.) are language-
    agnostic and act as a fallback/booster so a call isn't forced into
    "normal" just because it happens not to contain a listed keyword.
    """
    t = text.lower()
    spam_hits = [k for k in SPAM_KEYWORDS if k.lower() in t]
    important_hits = [k for k in IMPORTANT_KEYWORDS if k.lower() in t]
    robocall_hits = signals.get("robocall_patterns", [])

    pattern_score = sum([
        signals.get("has_link", False),
        signals.get("has_long_number", False),
        signals.get("mentions_money", False),
    ])

    # Robocall script patterns are strong, specific signals (an IVR asking
    # you to "press 1 to authorize" or reciting the robocall disclosure
    # line is essentially never a normal human conversation), so each hit
    # counts as much as an explicit spam keyword.
    spam_score = len(spam_hits) + pattern_score + len(robocall_hits)

    if spam_score and spam_score >= len(important_hits):
        category = "spam"
        confidence = round(min(0.62 + 0.12 * spam_score, 1.0), 2)
        matched = spam_hits + robocall_hits
    elif important_hits:
        category = "important"
        confidence = round(min(0.65 + 0.12 * len(important_hits), 1.0), 2)
        matched = important_hits
    else:
        category = "normal"
        confidence = 0.70
        matched = []

    return category, confidence, matched


# ---------------------------------------------------------------------------
# AI summary.
#
# This stays 100% local/offline (no external LLM API call, nothing leaves
# the machine — same guarantee as transcription/classification). It's an
# "extractive" summarizer: it doesn't invent sentences, it picks out the
# most information-dense sentences that actually exist in the transcript
# (the ones containing the matched keywords, phone/OTP numbers, links, or
# money amounts that drove the verdict) and pairs them with a one-line
# explanation of the classification. That keeps every summary traceable
# back to real words the caller said, matching the "transparent,
# inspectable" design used everywhere else in this app.
# ---------------------------------------------------------------------------
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?।॥؟\u06D4])\s+|\n+")


def _split_sentences(text: str):
    if not text or not text.strip():
        return []
    parts = [p.strip() for p in SENTENCE_SPLIT_PATTERN.split(text.strip()) if p.strip()]
    return parts if parts else [text.strip()]


def _score_sentence(sentence: str, matched_keywords):
    s = sentence.lower()
    score = 0.0
    for kw in matched_keywords:
        if kw.lower() in s:
            score += 2.0
    if URL_PATTERN.search(sentence):
        score += 1.5
    if LONG_DIGIT_PATTERN.search(sentence) or PHONE_PATTERN.search(sentence):
        score += 1.0
    if CURRENCY_PATTERN.search(sentence):
        score += 1.0
    for pattern in ROBOCALL_PATTERNS:
        if pattern.search(sentence):
            score += 1.5
            break
    return score


def generate_ai_summary(text: str, category: str, confidence: float, matched_keywords, signals: dict) -> dict:
    sentences = _split_sentences(text)
    if not sentences:
        return {"summary": "No speech detected in this recording.", "highlights": []}

    scored = sorted(
        ((s, _score_sentence(s, matched_keywords)) for s in sentences),
        key=lambda pair: pair[1],
        reverse=True,
    )
    top_n = 2 if len(sentences) <= 6 else 3
    picked_set = {s for s, sc in scored[:top_n] if sc > 0}
    if not picked_set:
        # Nothing scored (e.g. a normal call with no flagged signals) —
        # fall back to a plain gist: the opening sentence(s).
        picked_set = set(sentences[: min(2, len(sentences))])
    # Preserve original speaking order rather than score order.
    highlights = [s for s in sentences if s in picked_set][:top_n]

    pct = int(round(confidence * 100))
    if category == "spam":
        reason = f"⚠️ Flagged as SPAM ({pct}% confidence)"
        if matched_keywords:
            reason += f" — mentions {', '.join(matched_keywords[:4])}"
        extras = []
        if signals.get("has_link"):
            extras.append("contains a link")
        if signals.get("mentions_money"):
            extras.append("mentions money/amount")
        if signals.get("has_long_number"):
            extras.append("reads out a long number (OTP/account-style)")
        if extras:
            reason += "; " + ", ".join(extras)
    elif category == "important":
        reason = f"🟡 Flagged as IMPORTANT ({pct}% confidence)"
        if matched_keywords:
            reason += f" — mentions {', '.join(matched_keywords[:4])}"
    else:
        reason = f"🟢 Looks like a routine NORMAL call ({pct}% confidence)"

    summary = (reason + ". " + " ".join(highlights)).strip()
    return {"summary": summary, "highlights": highlights}


def analyze_file(filepath: str, original_name: str, forced_language: str = None) -> dict:
    if forced_language:
        # Known language: skip detection entirely. This is the reliable path
        # for short clips (WhatsApp voice notes, etc.) where auto-detect
        # doesn't have enough audio to work with, and for languages (like
        # Kannada) that the model's language-ID head confuses with related
        # ones even on longer audio.
        #
        # task="transcribe" keeps output in the original spoken language/script.
        # (task="translate" would force everything into English, which both
        # garbles low-resource languages like Kannada and breaks the
        # native-script keyword lists below, since they can only ever match
        # text in the language they were written for.)
        segments, info = model.transcribe(
            filepath,
            beam_size=1,
            language=forced_language,
            task="transcribe",
            vad_filter=True,                   # skip silence/hold-music — faster on long calls
            condition_on_previous_text=False,  # stop errors from compounding over long audio
            repetition_penalty=1.2,            # discourage the model from repeating a phrase
            no_repeat_ngram_size=3,             # hard-block exact 3-word-or-longer repeats
        )
        language_breakdown = [{"language": forced_language, "share": 1.0, "avg_probability": 1.0}]
        is_mixed_language = False
        language_low_confidence = False
    else:
        segments, info = model.transcribe(
            filepath,
            beam_size=1,
            vad_filter=True,                    # ignore ringing/hold music/silence
            language_detection_segments=4,      # look at up to ~2 min, not just 30s
            language_detection_threshold=0.6,   # fall back to majority vote below this
            task="transcribe",                  # keep output in the spoken language/script
            condition_on_previous_text=False,   # stop errors from compounding over long audio
            repetition_penalty=1.2,             # discourage the model from repeating a phrase
            no_repeat_ngram_size=3,              # hard-block exact 3-word-or-longer repeats
        )
        language_breakdown = detect_language_breakdown(filepath)
        is_mixed_language = (
            len(language_breakdown) > 1 and language_breakdown[1]["share"] >= 0.15
        )
        language_low_confidence = info.language_probability < LANGUAGE_CONFIDENCE_FLOOR

    # Safety net: even with repetition_penalty/no_repeat_ngram_size, Whisper can
    # occasionally still emit the same segment twice in a row (a known looping
    # artifact, not genuine repeated speech) — drop exact consecutive duplicates.
    seg_texts = []
    for seg in segments:
        t = seg.text.strip()
        if t and (not seg_texts or seg_texts[-1] != t):
            seg_texts.append(t)
    text = " ".join(seg_texts).strip()
    signals = extract_signals(text)
    category, confidence, matched = classify(text, signals)
    ai_summary = generate_ai_summary(text, category, confidence, matched, signals)

    result = {
        "id": str(uuid.uuid4()),
        "filename": original_name,
        "stored_name": os.path.basename(filepath),
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "language_forced": bool(forced_language),
        "language_low_confidence": language_low_confidence,
        "language_breakdown": language_breakdown,  # e.g. [{"language":"hi","share":0.6,...}, ...]
        "is_mixed_language": is_mixed_language,
        "duration_seconds": round(info.duration, 2),
        "transcript": text,
        "category": category,          # spam | important | normal
        "confidence": confidence,
        "matched_keywords": matched,
        "ai_summary": ai_summary["summary"],
        "summary_highlights": ai_summary["highlights"],
        "signals": signals,            # language-agnostic structural flags
        "extracted_numbers": signals.get("phone_numbers", []),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",           # pending | kept | archived | deleted
    }

    with open(os.path.join(RESULTS_DIR, result["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
# 300MB was rejecting long/uncompressed call recordings before they ever
# reached transcription. Raised well above what any realistic call recording
# (even hours-long, uncompressed WAV) would need. Actual analysis time still
# scales with audio length — a long file just takes longer to transcribe,
# it's no longer blocked outright.
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 * 1024  # 5 GB total upload cap


@app.errorhandler(413)
def too_large(_e):
    """Without this, an over-the-cap upload returns Flask's default HTML
    error page, which breaks the frontend's `await res.json()` call and
    surfaces as a confusing 'Unexpected token <' error instead of a clear
    message."""
    return jsonify({"error": "Upload too large — files exceed the server's size limit."}), 413


@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files uploaded"}), 400

    forced_language = (request.form.get("language") or "").strip() or None

    results = []
    for f in files:
        original_name = secure_filename(f.filename) or f.filename
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in ALLOWED_EXT:
            results.append({"filename": original_name, "error": f"unsupported file type {ext}"})
            continue

        stored_name = f"{uuid.uuid4()}{ext}"
        save_path = os.path.join(UPLOAD_DIR, stored_name)
        f.save(save_path)

        try:
            results.append(analyze_file(save_path, original_name, forced_language))
        except Exception as exc:  # keep going even if one file fails
            results.append({"filename": original_name, "error": str(exc)})

    return jsonify({"results": results})


@app.route("/api/action", methods=["POST"])
def action():
    data = request.get_json(force=True)
    result_id = data.get("id")
    act = data.get("action")  # delete | archive | keep

    result_path = os.path.join(RESULTS_DIR, f"{result_id}.json")
    if not os.path.exists(result_path):
        return jsonify({"error": "result not found"}), 404

    with open(result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    src = os.path.join(UPLOAD_DIR, result["stored_name"])

    if act == "delete":
        if os.path.exists(src):
            os.remove(src)
        os.remove(result_path)
        return jsonify({"status": "deleted"})

    if act == "archive":
        if os.path.exists(src):
            shutil.move(src, os.path.join(ARCHIVE_DIR, result["stored_name"]))
        result["status"] = "archived"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "archived"})

    if act == "keep":
        result["status"] = "kept"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "kept"})

    return jsonify({"error": "invalid action"}), 400


@app.route("/api/clear", methods=["POST"])
def clear():
    """Wipes uploads + result records (archive folder is left untouched)."""
    for d in (UPLOAD_DIR, RESULTS_DIR):
        for fn in os.listdir(d):
            fp = os.path.join(d, fn)
            if os.path.isfile(fp):
                os.remove(fp)
    return jsonify({"status": "cleared"})


@app.route("/api/results", methods=["GET"])
def get_results():
    results = []
    for fn in sorted(os.listdir(RESULTS_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(RESULTS_DIR, fn), "r", encoding="utf-8") as f:
                results.append(json.load(f))
    results.sort(key=lambda r: r.get("analyzed_at", ""), reverse=True)
    return jsonify({"results": results})


@app.route("/api/audio/<result_id>", methods=["GET"])
def get_audio(result_id):
    """Streams the original recording back for in-card playback."""
    result_path = os.path.join(RESULTS_DIR, f"{result_id}.json")
    if not os.path.exists(result_path):
        return jsonify({"error": "result not found"}), 404

    with open(result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    stored_name = result["stored_name"]
    for folder in (UPLOAD_DIR, ARCHIVE_DIR):
        candidate = os.path.join(folder, stored_name)
        if os.path.exists(candidate):
            return send_file(candidate, conditional=True)

    return jsonify({"error": "audio file not found (was it deleted?)"}), 404


@app.route("/api/download-csv", methods=["GET"])
def download_csv():
    """
    Spreadsheet-friendly export for spam/important/normal review — deliberately
    leaves out the raw transcript so it stays a quick scan list, not a wall
    of text.
    """
    rows = []
    for fn in sorted(os.listdir(RESULTS_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(RESULTS_DIR, fn), "r", encoding="utf-8") as f:
                rows.append(json.load(f))
    rows.sort(key=lambda r: r.get("analyzed_at", ""), reverse=True)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "filename", "category", "confidence", "duration_seconds",
        "matched_keyword_count", "robocall_pattern_count", "has_link", "has_long_number",
        "mentions_money", "extracted_numbers", "ai_summary", "status", "analyzed_at",
    ])
    for r in rows:
        signals = r.get("signals", {})
        writer.writerow([
            r.get("filename", ""),
            r.get("category", ""),
            r.get("confidence", ""),
            r.get("duration_seconds", ""),
            len(r.get("matched_keywords", []) or []),
            len(signals.get("robocall_patterns", []) or []),
            signals.get("has_link", False),
            signals.get("has_long_number", False),
            signals.get("mentions_money", False),
            "; ".join(r.get("extracted_numbers", []) or []),
            r.get("ai_summary", ""),
            r.get("status", ""),
            r.get("analyzed_at", ""),
        ])

    out_path = os.path.join(DATA_DIR, "call_analysis_results.csv")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())

    return send_file(out_path, as_attachment=True, download_name="call_analysis_results.csv")


@app.route("/api/download-json", methods=["GET"])
def download_json():
    results = []
    for fn in sorted(os.listdir(RESULTS_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(RESULTS_DIR, fn), "r", encoding="utf-8") as f:
                results.append(json.load(f))

    out_path = os.path.join(DATA_DIR, "all_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return send_file(out_path, as_attachment=True, download_name="call_analysis_results.json")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
