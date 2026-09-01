import re
import math
from dataclasses import dataclass, field

import textstat
from spellchecker import SpellChecker

spell = SpellChecker()

PROFANITY = {
    "fuck", "shit", "ass", "damn", "bitch", "crap", "piss", "dick", "cock",
    "pussy", "bastard", "asshole", "motherfucker", "bullshit", "wtf", "stfu",
    "ffs", "omfg",
}

REDDIT_SLANG = re.compile(
    r'\b(lol|lmao|lmfao|ngl|tbh|imo|imho|afaik|smh|bruh|nah|yeet|rn|tbf|istg|'
    r'idk|idgaf|fwiw|iirc|irl|rofl|lmk)\b|edit:|eta:',
    re.IGNORECASE,
)

ANECDOTE = re.compile(
    r'\b(i once|when i was|my (mom|dad|mother|father|sister|brother|wife|husband|'
    r'friend|roommate|coworker|boss|kid|son|daughter|partner|girlfriend|boyfriend)|'
    r'this happened to me)\b',
    re.IGNORECASE,
)

CLOSING_QUESTION = re.compile(
    r'(does that help|let me know if you have|happy to elaborate|hope that (helps|answers)|'
    r'feel free to ask|any (other )?questions|i hope this helps|hope this (helps|clarifies))\??\.?\s*$',
    re.IGNORECASE,
)

CONTRACTION = re.compile(
    r"\b(i'm|i've|i'll|i'd|you're|you've|you'll|you'd|he's|he'd|she's|she'd|"
    r"it's|we're|we've|we'll|we'd|they're|they've|they'll|they'd|can't|won't|"
    r"don't|doesn't|didn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't|"
    r"shouldn't|wouldn't|couldn't|mustn't|needn't|that's|there's|here's|who's|"
    r"what's|where's|when's|why's|how's)\b",
    re.IGNORECASE,
)

FIRST_PERSON = re.compile(r'\b(i|me|my|mine|we)\b', re.IGNORECASE)
OPINION_MARKER = re.compile(
    r'\b(i think|i believe|i feel|in my opinion|imo|imho|i suspect|i reckon|personally)\b',
    re.IGNORECASE,
)
EM_DASH = re.compile(r'—|–')
BOLD_HEADER = re.compile(r'^\*\*[A-Z][^*]*:?\*\*:?\s', re.MULTILINE)
BULLET = re.compile(r'^\s*[-*+]\s+|\d+\.\s+', re.MULTILINE)

# Transitional words that appear mid-comment (not just line starters)
TRANSITIONAL = re.compile(
    r'\b(additionally|furthermore|moreover|in addition|as a result|consequently|'
    r'therefore|thus|in contrast|on the other hand|in other words|to illustrate|'
    r'for instance|for example|specifically|in particular)\b',
    re.IGNORECASE,
)

# Definition-style opener: "X is a/an ..." or "X are ..."
EXPLANATORY_CONNECTOR = re.compile(
    r'\b(this is because|the reason (for this|is that|being)|this means that|'
    r'this is why|this (can|could|will|would) (be|help|allow|enable)|'
    r'in other words|to put it (simply|another way))\b',
    re.IGNORECASE,
)

DEFINITION_OPENER = re.compile(
    r'^[A-Z][a-zA-Z\s\(\)]{2,40}(is (a|an|the|one|used|when|what)|are (a|the|used|when|what))',
)

AI_PHRASES = [
    (r'\bcertainly\b\s*!', "certainly!"),
    (r'\bgreat question\b\s*!', "great question!"),
    (r"\bi hope this helps\b", "i hope this helps"),
    (r"\bit'?s worth noting\b", "it's worth noting"),
    (r"\bit is worth noting\b", "it is worth noting"),
    (r"\bit'?s important to note\b", "it's important to note"),
    (r"\bit is important to\b", "it is important to"),
    (r"\bfeel free to\b", "feel free to"),
    (r"\bin conclusion\b", "in conclusion"),
    (r"\bto summarize\b", "to summarize"),
    (r"\bin summary\b", "in summary"),
    (r"\bkey takeaways?\b", "key takeaways"),
    (r"\bas an ai\b", "as an ai"),
    (r"\bi cannot provide\b", "i cannot provide"),
    (r"\bi'?d be happy to\b", "i'd be happy to"),
    (r'\babsolutely\b\s*!', "absolutely!"),
    (r'\bof course\b\s*!', "of course!"),
    (r"\bthis is a nuanced\b", "this is a nuanced"),
    (r"\bon one hand\b.{0,200}\bon the other hand\b", "on one hand...on the other hand"),
    (r"\boverall,?\s+it(?:'s| is)\b", "overall it is"),
    (r"\bit(?:'s| is) worth (mentioning|highlighting|emphasizing)\b", "it is worth mentioning"),
]

IT_DEPENDS = re.compile(r"\bit depends on\b", re.IGNORECASE)


@dataclass
class ScorerResult:
    total_score: int
    signals_triggered: list = field(default_factory=list)
    verdict: str = "clean"
    confidence: float = 0.0


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r'\b\w+\b', text.lower())


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]


def _ttr(words: list[str]) -> float:
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _sentence_length_std(sentences: list[str]) -> float:
    if len(sentences) < 2:
        return 999.0
    lengths = [len(_words(s)) for s in sentences]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    return math.sqrt(variance)


class CommentScorer:
    def score(
        self,
        comment_text: str,
        account_age_days: int,
        karma: int,
        comment_history: list[str],
    ) -> ScorerResult:
        total = 0
        signals = []
        text = comment_text
        lower = text.lower()
        words = _words(text)
        word_count = len(words)
        sentences = _sentences(text)
        paragraphs = _paragraphs(text)

        # Group A - AI phrase fingerprints
        group_a = 0
        for pattern, label in AI_PHRASES:
            if re.search(pattern, lower):
                group_a += 3
                signals.append(f"ai_phrase:{label}")
        if len(IT_DEPENDS.findall(lower)) >= 2:
            group_a += 3
            signals.append("ai_phrase:it depends on (repeated)")
        group_a = min(group_a, 15)
        total += group_a

        # Group B - structural signals
        bullet_count = len(BULLET.findall(text))
        if bullet_count >= 3:
            total += 5
            signals.append("structural:3+ bullet/list items")

        if BOLD_HEADER.search(text):
            total += 5
            signals.append("structural:bold markdown headers")

        if word_count > 150 and len(FIRST_PERSON.findall(text)) < 3:
            total += 4
            signals.append("structural:long comment low first-person")

        if len(EM_DASH.findall(text)) > 2:
            total += 3
            signals.append("structural:em dash overuse")

        if len(paragraphs) >= 4:
            even = all(2 <= len(_sentences(p)) <= 5 for p in paragraphs)
            if even:
                total += 3
                signals.append("structural:uniform paragraph structure")

        if word_count > 100 and not CONTRACTION.search(text):
            total += 3
            signals.append("structural:no contractions in long comment")

        if CLOSING_QUESTION.search(text):
            total += 2
            signals.append("structural:closing discussion prompt")

        # No personal opinion markers in a substantive comment = AI register
        if word_count > 100 and not OPINION_MARKER.search(text):
            total += 2
            signals.append("structural:no personal opinion markers")

        # Definition-style opener: "X is a ..."
        if DEFINITION_OPENER.match(text.strip()):
            total += 3
            signals.append("structural:definition-style opener")

        # Explanatory connector overuse: AI explains everything sequentially
        expl_count = len(EXPLANATORY_CONNECTOR.findall(text))
        if expl_count >= 2:
            total += 3
            signals.append(f"structural:explanatory connector overuse ({expl_count})")
        elif expl_count == 1 and word_count > 100:
            total += 1
            signals.append("structural:explanatory connector present")

        # Transitional connective overuse: 3+ = strong AI signal
        transitional_count = len(TRANSITIONAL.findall(text))
        if transitional_count >= 3:
            total += 4
            signals.append(f"structural:transitional connective overuse ({transitional_count})")
        elif transitional_count >= 2:
            total += 2
            signals.append(f"structural:multiple transitional connectives ({transitional_count})")

        # Group C - account signals
        if account_age_days < 7:
            total += 7
            signals.append("account:age < 7 days")
        elif account_age_days < 30:
            total += 5
            signals.append("account:age < 30 days")

        if karma < 50 and word_count > 200:
            total += 4
            signals.append("account:low karma + long comment")

        if comment_history:
            long_comments = [c for c in comment_history if len(_words(c)) > 200]
            if len(long_comments) == len(comment_history):
                total += 3
                signals.append("account:all history comments are long")

            casual = [c for c in comment_history if len(_words(c)) <= 20]
            if len(casual) == 0 and len(comment_history) >= 5:
                total += 3
                signals.append("account:no casual/short comments in history")

        # Group D - statistical signals
        if word_count > 100:
            ttr = _ttr(words)
            if ttr > 0.65:
                total += 4
                signals.append(f"statistical:high lexical diversity TTR={ttr:.2f}")

        if len(sentences) > 5:
            std = _sentence_length_std(sentences)
            if std < 5:
                total += 3
                signals.append(f"statistical:low sentence length variance std={std:.2f}")

        if word_count > 50:
            fk = textstat.flesch_kincaid_grade(text)
            if fk > 10:
                total += 2
                signals.append(f"statistical:high readability grade FK={fk:.1f}")

        # Group E - human penalties
        word_set = set(words)
        if word_set & PROFANITY:
            total -= 5
            signals.append("penalty:profanity/slang detected")

        if word_count > 20:
            # contraction stems produced by word tokenizer (e.g. doesn't -> "doesn")
            _contraction_stems = {
                "doesn", "didn", "wouldn", "couldn", "shouldn", "weren",
                "haven", "hadn", "isn", "aren", "wasn", "mustn", "needn",
            }
            checkable = [
                w for w in words
                if w.isalpha() and 4 <= len(w) <= 15 and w == w.lower()
                and w not in _contraction_stems
            ]
            misspelled = spell.unknown(checkable)
            if len(misspelled) == 1:
                total -= 2
                signals.append("penalty:possible typo (1)")
            elif 2 <= len(misspelled) <= 4:
                total -= 4
                signals.append(f"penalty:typos detected ({len(misspelled)})")

        if word_count < 80:
            total -= 3
            signals.append("penalty:comment < 80 words")

        if REDDIT_SLANG.search(text):
            total -= 3
            signals.append("penalty:reddit slang/references")

        if ANECDOTE.search(text):
            total -= 2
            signals.append("penalty:personal anecdote marker")

        if total < 10:
            verdict = "clean"
        elif total < 20:
            verdict = "suspicious"
        else:
            verdict = "flag"

        max_possible = 15 + 5 + 5 + 4 + 3 + 3 + 3 + 2 + 3 + 4 + 7 + 4 + 3 + 3 + 4 + 3 + 2
        confidence = max(0.0, min(1.0, total / max_possible))

        return ScorerResult(
            total_score=total,
            signals_triggered=signals,
            verdict=verdict,
            confidence=confidence,
        )
