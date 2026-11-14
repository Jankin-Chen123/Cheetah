"""Explicit local audio test, using a <=10s fictional PCM WAV; never dials a number."""

import argparse
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.integrations.voice.realtime import audio_roundtrip  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_wav", type=Path)
    parser.add_argument("--transcription-only", action="store_true")
    parser.add_argument("--output-directory", type=Path, default=Path("../work/realtime-check"))
    args = parser.parse_args()
    with wave.open(str(args.input_wav), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            parser.error("Input must be 16kHz mono 16-bit PCM WAV")
        if source.getnframes() > 160000:
            parser.error("Input must be at most 10 seconds")
        pcm = source.readframes(source.getnframes())
    result = audio_roundtrip(get_settings(), pcm, transcription_only=args.transcription_only)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    if args.transcription_only:
        (args.output_directory / "transcription.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8"
        )
        print(f"Model: {result['model']}; transcription complete; telephone line: false")
        return
    with wave.open(str(args.output_directory / "reply.wav"), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(result["sample_rate"])
        target.writeframes(result["pcm"])
    summary = {key: value for key, value in result.items() if key != "pcm"}
    (args.output_directory / "events.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(f"Model: {result['model']}; audio bytes: {len(result['pcm'])}; telephone line: false")


if __name__ == "__main__":
    main()
