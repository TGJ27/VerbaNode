# Pipeline comparison: Xiaozhi reference vs VerbaNode

This comparison is based on the uploaded `xiaozhi-esp32-server-main` source tree and VerbaNode v0.1.8.

## Xiaozhi reference pipeline

Key source paths:

- `main/xiaozhi-server/core/connection.py`
- `main/xiaozhi-server/core/handle/receiveAudioHandle.py`
- `main/xiaozhi-server/core/providers/asr/base.py`
- `main/xiaozhi-server/core/providers/vad/silero.py`
- `main/xiaozhi-server/core/providers/tts/base.py`
- `main/xiaozhi-server/core/handle/sendAudioHandle.py`

Flow:

```text
Device microphone
  -> Opus packets over WebSocket
  -> server decodes each packet to PCM once
  -> ordered ASR audio queue
  -> Silero VAD with dual thresholds and a sliding window
  -> completed-utterance ASR
  -> intent/tool handling
  -> streaming LLM tokens
  -> TTS text queue
  -> punctuation-based text segmentation
  -> TTS synthesis / optional provider-level audio streaming
  -> Opus audio queue
  -> rate-controlled WebSocket audio packets
  -> device speaker
```

Notable design choices:

- The server and audio device are separate.
- Audio transport is packetized Opus rather than host file playback.
- The first TTS segment may end at a comma to reduce time-to-first-audio.
- Text synthesis and audio sending use separate queues/threads.
- `sentence_id` and abort flags discard stale TTS after interruption.
- Client/server AEC paths exist for full-duplex interruption.
- The provider architecture supports many ASR, LLM, TTS, memory, and tool backends.
- FunASR local recognition is still utterance-final, although other configured ASR providers can be streaming.

## VerbaNode pipeline

Key source paths:

- `app/services/audio.py`
- `app/services/stt.py`
- `app/services/conversation.py`
- `app/services/llm.py`
- `app/services/sentence_tts.py`
- `app/services/tts.py`

Flow:

```text
Windows host microphone
  -> float32 PCM through sounddevice
  -> Silero VAD / energy fallback
  -> capture ends after configured silence
  -> SenseVoiceSmall transcription
  -> confidence display/filter
  -> agent prompt + selected information + memory summary + recent history
  -> Ollama token stream
  -> sentence chunker
  -> TTS generation queue
  -> sequential host playback through a persistent sounddevice output stream
  -> Windows host speaker
```

Notable design choices:

- The browser is only a control/status UI; audio always remains on the Windows host.
- There is no Opus encode/decode or audio WebSocket path.
- LLM text is shown as one chat message while complete sentences enter TTS immediately.
- TTS synthesis and playback are separate producer/consumer tasks, so the next sentence can be generated while the current sentence plays.
- A generation token cancels stale or stopped audio.
- Safe half-duplex is the default because acoustic echo cancellation is not implemented.
- Script and greeting audio can be cached and replayed without regenerating TTS.
- Agent configuration, information selection, conversations, summaries, PIN takeover, and browser responsiveness are integrated into one application.

## Main differences

| Area | Xiaozhi reference | VerbaNode |
|---|---|---|
| Intended deployment | Remote/multiple embedded clients and central server | One Windows host with browser controls |
| Audio location | Client device microphone/speaker | Windows host microphone/speaker |
| Audio transport | Opus over WebSocket | No network audio transport |
| VAD | Frame-by-frame dual-threshold state machine | Capture session using Silero iterator plus energy fallback |
| Local FunASR | Utterance-final | Utterance-final |
| LLM-to-TTS | Token queue, first clause may split on comma | Sentence queue, forced split at 180 characters |
| Audio delivery | Opus packets with prebuffer/rate control | Generated MP3/WAV file playback per chunk |
| Interruption | Designed for AEC/full duplex | Safe half duplex; experimental barge-in only |
| Cancellation | `sentence_id` + abort flags | Speech generation ID + cancellation events |
| Provider breadth | Very broad | Focused: Ollama, FunASR, Edge, Kokoro |
| Operational complexity | High | Much lower |
| Reusable TTS cache | Not central to the base pipeline | Scripts and greetings cached persistently |

## Which is better?

For the requested single-host Windows product, **VerbaNode is the better base**. It directly matches the required topology, avoids unnecessary device binding and network-audio codecs, is easier to install on different PCs, and already includes the required agent, script, information, memory, and browser-management workflows.

The Xiaozhi pipeline is technically stronger for a different problem: remote embedded devices, many simultaneous connections, true packet-level audio streaming, and robust full-duplex interruption with AEC. Its first-clause TTS segmentation can also produce lower time-to-first-audio than waiting for a complete sentence.

## Recommended hybrid improvements

The best future direction is to keep the single-host architecture and selectively borrow these ideas from Xiaozhi:

1. Optional first-clause TTS split at a comma for faster first speech.
2. True streaming TTS audio frames when a local/online provider supports them.
3. Acoustic echo cancellation before enabling full-duplex interruption by default.
4. Optional streaming ASR provider while retaining SenseVoiceSmall as the low-CPU default.
5. More robust multi-step tool execution with an explicit depth limit.

Do not copy the remote device binding, Opus transport, or per-connection server machinery into the Windows-hosted edition unless network audio clients become a requirement.
