from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and initialize Whisper Base for Indonesian transcription through FunASR."
    )
    parser.add_argument("--model", default="Whisper-base")
    args = parser.parse_args()

    print(f"Preparing Indonesian ASR model: {args.model}", flush=True)
    print("This uses the OpenAI Whisper multilingual Base checkpoint through FunASR.", flush=True)
    try:
        import whisper  # noqa: F401
        from funasr import AutoModel
    except ImportError:
        print(
            "FunASR or openai-whisper is not installed. Run setup_windows.bat first.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    try:
        AutoModel(model=args.model, hub="openai", device="cpu")
    except KeyboardInterrupt:
        print("Download cancelled. Run this script again to resume.", flush=True)
        return 130
    except Exception as exc:
        print(f"Whisper Base preparation failed: {exc}", file=sys.stderr, flush=True)
        return 1

    print("Whisper Base is ready for Indonesian agents.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
