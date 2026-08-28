# Third-party notices

## xiaozhi-esp32-server

- License: MIT
- Repository: `xinnan-tech/xiaozhi-esp32-server`
- Use in VerbaNode: architectural reference for modular VAD, STT, LLM, tools, memory, and TTS pipeline design. Its console screenshots also informed the general navigation and light-dashboard direction of the v0.3.0 interface; VerbaNode retains its own implementation and assets.

## OpenAI Whisper

- License: MIT for the `openai-whisper` software package.
- Use in VerbaNode: multilingual Whisper Base inference for Indonesian agents through the FunASR OpenAI hub adapter.
- Model weights are downloaded separately and retain their own applicable terms.

No upstream model files or proprietary visual assets are included in this repository. External models and runtimes retain their own licenses and terms.

## CustomTkinter

- License: MIT.
- Use in VerbaNode: native Windows launcher presentation layer for the packaged application.
- The source-mode web dashboard and VerbaNode runtime do not depend on CustomTkinter; it is bundled with the Windows application build.

## FastEmbed

- License: Apache-2.0.
- Use in VerbaNode: CPU/ONNX embedding runtime for the local Hybrid RAG dense-retrieval path.

## USearch

- License: Apache-2.0.
- Use in VerbaNode: persistent local HNSW approximate-nearest-neighbor vector indexes for Knowledge libraries.

## multilingual-e5-small

- Model: `intfloat/multilingual-e5-small`.
- License: MIT (per the upstream model card).
- Use in VerbaNode: default multilingual 384-dimensional Knowledge embedding model. Model files are downloaded separately into the local Knowledge cache and are not included in this repository.
