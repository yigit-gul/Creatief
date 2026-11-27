"""Meet hoe 'voorgelezen' een voice-over klinkt: tempo, pauzes, toonhoogte en volume.

  python -m pipeline.stemanalyse review/<map>/<id>.mp4 [andere.mp4 ...]

Richtwaarden (voorbeeldvideo met veel views, 27/11): ±3,2 woorden/s, ±11 pauzes per minuut,
≥8 woorden in de eerste 3 s, volume-spreiding ±2-3 dB.
"""
import sys

import numpy as np


def meet(path):
    import librosa
    from . import luister
    y = luister.load_audio(path).astype(np.float32)
    sr = 16000
    segs, _ = luister.model().transcribe(y, language="nl", word_timestamps=True, beam_size=5)
    W = [w for s in segs for w in s.words]
    dur = W[-1].end - W[0].start
    gaps = np.array([b.start - a.end for a, b in zip(W, W[1:])])
    f0, _, _ = librosa.pyin(y, fmin=60, fmax=300, sr=sr, frame_length=1024, hop_length=160)
    f = f0[~np.isnan(f0)]
    st = 12 * np.log2(f / np.median(f))
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=160)[0]
    r = 20 * np.log10(rms[rms > np.percentile(rms, 30)] + 1e-6)
    return {
        "woorden_per_s": round(len(W) / dur, 2),
        "pauzes_per_min": round(float(np.sum(gaps > 0.15)) / dur * 60, 1),
        "woorden_eerste_3s": len([w for w in W if w.start < 3]),
        "toon_spreiding_ht": round(float(st.std()), 2),
        "volume_spreiding_db": round(float(r.std()), 1),
    }


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, meet(p))
