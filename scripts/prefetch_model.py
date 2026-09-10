import os

from faster_whisper import WhisperModel

model = os.getenv("ASR_MODEL", "small")
device = os.getenv("ASR_DEVICE", "cpu")
compute_type = os.getenv("ASR_COMPUTE_TYPE", "int8")
print(f"Prefetching faster-whisper model={model} device={device} compute_type={compute_type}")
WhisperModel(model, device=device, compute_type=compute_type)
print("Model is ready.")
