from __future__ import annotations

import argparse
import sys


MODEL_MAP = {
    "base": "Whisper-base",
    "small": "Whisper-small",
    "Whisper-base": "Whisper-base",
    "Whisper-small": "Whisper-small",
}


def prepare(model_name: str) -> None:
    from funasr import AutoModel

    print(f"Preparing Indonesian ASR model: {model_name}", flush=True)
    AutoModel(model=model_name, hub="openai", device="cpu")
    print(f"{model_name} is ready.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Whisper Base and/or Small for Indonesian transcription through FunASR."
    )
    parser.add_argument(
        "--model",
        default="base",
        help="base, small, both, Whisper-base, or Whisper-small",
    )
    args = parser.parse_args()

    try:
        import whisper  # noqa: F401
        from funasr import AutoModel  # noqa: F401
    except ImportError:
        print(
            "FunASR or openai-whisper is not installed. Run scripts/setup/setup_windows.bat first.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    requested = str(args.model).strip()
    if requested.lower() == "both":
        models = ["Whisper-base", "Whisper-small"]
    else:
        resolved = MODEL_MAP.get(requested, MODEL_MAP.get(requested.lower()))
        if not resolved:
            print("Unknown model. Use base, small, or both.", file=sys.stderr, flush=True)
            return 2
        models = [resolved]

    try:
        for model_name in models:
            prepare(model_name)
    except KeyboardInterrupt:
        print("Download cancelled. Run this script again to resume.", flush=True)
        return 130
    except Exception as exc:
        print(f"Whisper preparation failed: {exc}", file=sys.stderr, flush=True)
        return 1

    print("Indonesian Whisper setup completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
