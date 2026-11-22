"""小さな Transformer（GPT と同じしくみ）。次のトークンを予測するように学習する。"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class Block(nn.Module):
    def __init__(self, d, heads, drop):
        super().__init__()
        self.ln1 = nn.LayerNorm(d)
        self.attn = nn.MultiheadAttention(d, heads, dropout=drop, batch_first=True)
        self.ln2 = nn.LayerNorm(d)
        self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d), nn.Dropout(drop))

    def forward(self, x, mask):
        h = self.ln1(x)
        a, _ = self.attn(h, h, h, attn_mask=mask, need_weights=False)
        x = x + a
        return x + self.mlp(self.ln2(x))


class MusicGPT(nn.Module):
    def __init__(self, vocab: int, ctx: int = 320, d: int = 192, layers: int = 4, heads: int = 4, drop: float = 0.1):
        super().__init__()
        self.ctx = ctx
        self.tok = nn.Embedding(vocab, d)
        self.pos = nn.Embedding(ctx, d)
        self.blocks = nn.ModuleList([Block(d, heads, drop) for _ in range(layers)])
        self.ln = nn.LayerNorm(d)
        self.head = nn.Linear(d, vocab, bias=False)
        self.config = dict(vocab=vocab, ctx=ctx, d=d, layers=layers, heads=heads, drop=drop)

    def forward(self, idx):
        T = idx.shape[1]
        x = self.tok(idx) + self.pos(torch.arange(T, device=idx.device))
        mask = torch.triu(torch.full((T, T), float("-inf"), device=idx.device), 1)
        for b in self.blocks:
            x = b(x, mask)
        return self.head(self.ln(x))

    @torch.no_grad()
    def sample(self, prefix: list[int], max_len: int, temperature=1.0, top_k=12, allowed=None):
        """allowed(seq) -> 次に出してよいトークンの集合（文法を守らせる）"""
        self.eval()
        seq = list(prefix)
        while len(seq) < max_len:
            x = torch.tensor([seq[-self.ctx:]])
            logits = self(x)[0, -1] / temperature
            if allowed is not None:
                ok = allowed(seq)
                m = torch.full_like(logits, float("-inf"))
                m[list(ok)] = 0
                logits = logits + m
            v, _ = torch.topk(logits, min(top_k, logits.numel()))
            logits[logits < v[-1]] = float("-inf")
            nxt = int(torch.multinomial(F.softmax(logits, -1), 1))
            seq.append(nxt)
            if nxt == 2:  # EOS
                break
        return seq
