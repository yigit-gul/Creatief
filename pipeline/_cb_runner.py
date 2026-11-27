"""Draait in de aparte Chatterbox-omgeving (Python 3.11). Niet rechtstreeks importeren vanuit de pipeline.

Leest een JSON-taaklijst van stdin: {"ref": pad, "exaggeration": x, "cfg": y,
                                     "jobs": [{"text": ..., "out": pad.wav, "seed": n}, ...]}
en schrijft elke clip als wav. Het model wordt maar één keer geladen.
"""
import json
import sys

import torch
import torchaudio as ta

torch.set_num_threads(4)
from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: E402

task = json.load(sys.stdin)
model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
for job in task["jobs"]:
    torch.manual_seed(job.get("seed", 1))
    wav = model.generate(job["text"], language_id="nl", audio_prompt_path=task["ref"],
                         exaggeration=task["exaggeration"], cfg_weight=task["cfg"])
    ta.save(job["out"], wav, model.sr)
    print("KLAAR", job["out"], flush=True)
