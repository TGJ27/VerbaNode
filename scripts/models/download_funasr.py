from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and initialize the FunASR model before first use.")
    parser.add_argument("--model", default="iic/SenseVoiceSmall", help="FunASR/ModelScope model identifier")
    parser.add_argument("--threads", type=int, default=2, help="CPU threads used when loading the model")
    args = parser.parse_args()

    print(f"Preparing FunASR model: {args.model}", flush=True)
    print("The first download is about 936 MB. Progress comes from ModelScope.", flush=True)
    try:
        from funasr import AutoModel
    except ImportError:
        print("FunASR is not installed. Run scripts/setup/setup_windows.bat first.", file=sys.stderr, flush=True)
        return 1

    try:
        AutoModel(
            model=args.model,
            trust_remote_code=True,
            disable_update=True,
            device="cpu",
            ncpu=max(1, args.threads),
        )
    except KeyboardInterrupt:
        print("Download cancelled. Run this script again to resume.", flush=True)
        return 130
    except Exception as exc:
        print(f"FunASR model preparation failed: {exc}", file=sys.stderr, flush=True)
        return 1

    print("FunASR model is ready. Future transcription should start without downloading it again.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
