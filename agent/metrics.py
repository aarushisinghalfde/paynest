"""Metrics for the model-fit test (no external libraries)."""

from collections import Counter, defaultdict


def accuracy(gold, pred):
    return sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold) if gold else 0.0


def macro_f1(gold, pred, labels):
    f1s = []
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred, strict=True))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred, strict=True))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred, strict=True))
        if tp + fp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def by_group(gold, pred, groups):
    acc = defaultdict(lambda: [0, 0])
    for g, p, k in zip(gold, pred, groups, strict=True):
        acc[k][0] += g == p
        acc[k][1] += 1
    return {k: round(a / n, 4) for k, (a, n) in sorted(acc.items())}


def confusion_between(gold, pred, a, b):
    c = Counter((g, p) for g, p in zip(gold, pred, strict=True))
    return {f"{a}->{b}": c[(a, b)], f"{b}->{a}": c[(b, a)]}


def p95(values):
    if not values:
        return None
    s = sorted(values)
    return s[max(0, int(round(0.95 * len(s))) - 1)]
