import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wavepilot.dsp import channel_rf_score
from wavepilot.radio import RtlSdrDevice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frequency", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=15.0)
    args = parser.parse_args()
    radio = RtlSdrDevice()
    rows = []
    try:
        radio.configure(
            center_hz=int(args.frequency * 1_000_000),
            sample_rate=240_000,
            auto_gain=False,
            gain_tenths_db=77,
        )
        started = time.monotonic()
        while time.monotonic() - started < args.seconds:
            score = channel_rf_score(radio.read_iq(32_768), 240_000)
            rows.append(
                {
                    "seconds": round(time.monotonic() - started, 2),
                    "snr_db": round(score["snr_db"], 1),
                    "peak_db": round(score["peak_db"], 1),
                }
            )
    finally:
        radio.close()
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
