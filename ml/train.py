#!/usr/bin/env python3
"""EDM のメロディとコードを学習する。

  python ml/train.py --segments /home/user/data/segments.json --minutes 20
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import MusicGPT  # noqa: E402
from tokens import VOCAB  # noqa: E402


def batches(data, bs, ctx):
    random.shuffle(data)
    for i in range(0, len(data) - bs + 1, bs):
        chunk = [s[:ctx + 1] for s in data[i:i + bs]]
        L = max(len(s) for s in chunk)
        x = torch.zeros((bs, L), dtype=torch.long)  # PAD=0
        for j, s in enumerate(chunk):
            x[j, :len(s)] = torch.tensor(s)
        yield x[:, :-1], x[:, 1:]


def evaluate(model, data, ctx):
    model.eval()
    tot, n = 0.0, 0
    with torch.no_grad():
        for x, y in batches(list(data), 64, ctx):
            logits = model(x)
            loss = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1), ignore_index=0, reduction="sum")
            tot += loss.item()
            n += (y != 0).sum().item()
    model.train()
    return tot / max(n, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", type=Path, default=Path("/home/user/data/segments.json"))
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "edm_gpt.pt")
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--bs", type=int, default=32)
    a = ap.parse_args()

    torch.manual_seed(0)
    random.seed(0)
    data = json.load(open(a.segments))
    data = [s for s in data if len(s) >= 40]
    random.shuffle(data)
    nval = max(200, len(data) // 50)
    val, train = data[:nval], data[nval:]
    print(f"学習 {len(train)} 区間 / 検証 {len(val)} 区間")

    model = MusicGPT(len(VOCAB))
    print(f"パラメータ数 {sum(p.numel() for p in model.parameters()) / 1e6:.2f}M")
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.05)
    t0 = time.time()
    step, best = 0, 1e9
    deadline = t0 + a.minutes * 60
    epoch = 0
    while time.time() < deadline:
        epoch += 1
        for x, y in batches(train, a.bs, model.ctx):
            frac = min(1.0, (time.time() - t0) / (a.minutes * 60))
            for g in opt.param_groups:
                g["lr"] = 1e-3 * (0.1 + 0.9 * (1 - frac))  # だんだん学習率を下げる
            logits = model(x)
            loss = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1), ignore_index=0)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            if step % 200 == 0:
                print(f"  epoch {epoch} step {step}  loss {loss.item():.3f}  {(time.time() - t0) / 60:.1f}分", flush=True)
            if step % 1000 == 0 or time.time() >= deadline:
                vl = evaluate(model, val, model.ctx)
                print(f"  [検証] loss {vl:.3f}", flush=True)
                if vl < best:
                    best = vl
                    torch.save({"config": model.config, "state": model.state_dict(), "val_loss": vl}, a.out)
                if time.time() >= deadline:
                    break
    print(f"[done] 最良の検証 loss {best:.3f} → {a.out}")


if __name__ == "__main__":
    main()
