import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wavepilot.dsp import NfmStreamDemodulator
from wavepilot.live_audio import _condition_audio
from wavepilot.radio import RtlSdrDevice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frequency", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sample_rate = 240_000
    chunk_samples = 32_768
    remaining = int(sample_rate * args.seconds)
    decoder = NfmStreamDemodulator(sample_rate, 48_000)
    gain_scale = 2.0
    blocks = []
    radio = RtlSdrDevice()
    try:
        radio.configure(
            center_hz=int(args.frequency * 1_000_000),
            sample_rate=sample_rate,
            auto_gain=False,
            gain_tenths_db=77,
        )
        while remaining > 0:
            iq = radio.read_iq(min(chunk_samples, remaining))
            audio = decoder.process(iq)
            audio, gain_scale = _condition_audio(audio, gain_scale)
            blocks.append(audio)
            remaining -= len(iq)
    finally:
        radio.close()

    audio = np.concatenate(blocks) if blocks else np.empty(0, dtype=np.float32)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(pcm.tobytes())
    print(f"wrote {args.output} samples={len(audio)} peak={float(np.max(np.abs(audio))):.4f}")


if __name__ == "__main__":
    main()
