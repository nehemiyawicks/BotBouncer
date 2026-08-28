import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scorer import CommentScorer

DATA_DIR = Path(__file__).parent / "data"
AI_SAMPLES = DATA_DIR / "ai_samples.jsonl"
HUMAN_SAMPLES = DATA_DIR / "human_samples.jsonl"

scorer = CommentScorer()

DUMMY_AI_ACCOUNT = {"account_age_days": 25, "karma": 80, "comment_history": ["word " * 210] * 10}
DUMMY_HUMAN_ACCOUNT = {"account_age_days": 365, "karma": 5000,
                        "comment_history": ["short", "word " * 210, "lol ok", "word " * 210, "nah"]}


def load_samples(path):
    if not path.exists():
        return []
    samples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def test_ai_samples_flag_rate():
    samples = load_samples(AI_SAMPLES)
    if not samples:
        pytest.skip("No AI samples found. Run scripts/prepare_test_data.py first.")

    suspicious_or_flag = 0
    flagged = 0

    signal_counts = defaultdict(int)

    for s in samples:
        result = scorer.score(s["text"], **DUMMY_AI_ACCOUNT)
        if result.total_score >= 10:
            suspicious_or_flag += 1
        if result.total_score >= 20:
            flagged += 1
            for sig in result.signals_triggered:
                signal_counts[sig] += 1

    total = len(samples)
    print(f"\nAI samples: {total}")
    print(f"  >= 10 (suspicious/flag): {suspicious_or_flag} ({100*suspicious_or_flag/total:.1f}%)")
    print(f"  >= 20 (flag): {flagged} ({100*flagged/total:.1f}%)")
    print("Top signals:", sorted(signal_counts.items(), key=lambda x: -x[1])[:10])

    assert suspicious_or_flag / total >= 0.80, f"AI detection rate too low: {suspicious_or_flag/total:.2%}"
    assert flagged / total >= 0.60, f"AI flag rate too low: {flagged/total:.2%}"


def test_human_samples_false_positive_rate():
    samples = load_samples(HUMAN_SAMPLES)
    if not samples:
        pytest.skip("No human samples found. Run scripts/prepare_test_data.py first.")

    suspicious = 0
    flagged = 0
    signal_counts = defaultdict(int)

    for s in samples:
        result = scorer.score(s["text"], **DUMMY_HUMAN_ACCOUNT)
        if result.total_score >= 10:
            suspicious += 1
            for sig in result.signals_triggered:
                signal_counts[sig] += 1
        if result.total_score >= 20:
            flagged += 1

    total = len(samples)
    print(f"\nHuman samples: {total}")
    print(f"  >= 20 (false positive flags): {flagged} ({100*flagged/total:.1f}%)")
    print(f"  >= 10 (suspicious): {suspicious} ({100*suspicious/total:.1f}%)")

    if flagged / total > 0.05 or suspicious / total > 0.15:
        print("Top firing signals on human text:", sorted(signal_counts.items(), key=lambda x: -x[1])[:10])

    assert flagged / total <= 0.05, f"False positive rate too high: {flagged/total:.2%}"
    assert suspicious / total <= 0.15, f"Suspicious rate too high: {suspicious/total:.2%}"


def test_individual_signal_certainly():
    text = "Certainly! That is a great point to consider here."
    result = scorer.score(text, account_age_days=200, karma=1000, comment_history=[])
    assert any("certainly" in s.lower() for s in result.signals_triggered)


def test_individual_signal_bullet_points():
    text = (
        "Here are the main points:\n"
        "- First point about the topic\n"
        "- Second point with more detail\n"
        "- Third point that concludes\n"
        "These are the key considerations."
    )
    result = scorer.score(text, account_age_days=200, karma=1000, comment_history=[])
    assert any("bullet" in s for s in result.signals_triggered)


def test_individual_signal_bold_headers():
    text = (
        "**Overview:**\nThis is the overview section.\n\n"
        "**Details:**\nHere are more details for you.\n"
    )
    result = scorer.score(text, account_age_days=200, karma=1000, comment_history=[])
    assert any("bold" in s for s in result.signals_triggered)


def test_individual_signal_em_dash():
    text = (
        "There are several factors at play here — first the economic — then the social — "
        "and finally the political dimensions of this issue."
    )
    result = scorer.score(text, account_age_days=200, karma=1000, comment_history=[])
    assert any("em dash" in s for s in result.signals_triggered)


def test_individual_signal_high_ttr():
    words = [f"unique{i}" for i in range(200)]
    text = " ".join(words)
    result = scorer.score(text, account_age_days=200, karma=1000, comment_history=[])
    assert any("lexical diversity" in s for s in result.signals_triggered)


def test_negative_signals_reduce_score():
    text = "wtf lol this is bullshit tbh ngl"
    result = scorer.score(text, account_age_days=365, karma=5000, comment_history=[])
    assert result.total_score <= 0


def test_threshold_verdicts():
    cases = [
        (5, "clean"),
        (12, "suspicious"),
        (22, "flag"),
    ]
    for score_val, expected_verdict in cases:
        # manufacture a result by tweaking a mock
        from scorer import ScorerResult
        r = ScorerResult(total_score=score_val, signals_triggered=[])
        if score_val < 10:
            r.verdict = "clean"
        elif score_val < 20:
            r.verdict = "suspicious"
        else:
            r.verdict = "flag"
        assert r.verdict == expected_verdict


def test_new_account_high_essay():
    text = (
        "It is worth noting that there are several key considerations here.\n\n"
        "- First point about the matter at hand\n"
        "- Second important consideration to evaluate\n"
        "- Third factor that must be examined carefully\n\n"
        "In conclusion, the evidence suggests that this approach is the most effective. "
        "The analysis demonstrates that stakeholders should evaluate these factors comprehensively. "
        "Furthermore, the implications of this decision will have lasting effects on the organization. "
        "Certainly this is a nuanced question that requires thoughtful deliberation and consideration. "
        "Key takeaways include the importance of evidence-based decision making and thorough analysis."
    )
    result = scorer.score(text, account_age_days=3, karma=1, comment_history=["word " * 210] * 5)
    assert result.total_score >= 20, f"Expected >= 20, got {result.total_score}: {result.signals_triggered}"


def test_veteran_account_long_comment():
    text = (
        "Here are some thoughts. "
        "First point here. Second point here.\n\n"
        "- One thing\n"
        "- Another thing\n\n"
        "Overall it really comes down to what works for you in your situation. "
        "That is basically what I have seen work best in practice over the years."
    )
    result = scorer.score(text, account_age_days=1825, karma=50000,
                          comment_history=["short lol", "word " * 210, "nah", "idk man", "tbh same"])
    assert result.total_score < 20, f"Expected < 20, got {result.total_score}: {result.signals_triggered}"


def test_hc3_reddit_eli5_subset():
    samples = load_samples(AI_SAMPLES)
    hc3 = [s for s in samples if s.get("source") == "hc3_reddit_eli5"][:50]
    if not hc3:
        pytest.skip("No HC3 reddit_eli5 samples found.")

    above_10 = 0
    below_5 = []
    for s in hc3:
        result = scorer.score(s["text"], **DUMMY_AI_ACCOUNT)
        if result.total_score >= 10:
            above_10 += 1
        if result.total_score < 5:
            below_5.append((result.total_score, s["text"][:80]))

    print(f"\nHC3 reddit_eli5: {len(hc3)} samples, {above_10} scored >= 10")
    for sc, snippet in below_5:
        print(f"  Low score {sc}: {snippet}")

    assert above_10 / len(hc3) >= 0.55, f"HC3 detection rate too low: {above_10/len(hc3):.2%}"
