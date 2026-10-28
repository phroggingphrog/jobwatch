"""Third opinion on a cover letter: plain rules distilled from open-source letter writers.

Sources: jobsync (no placeholders, no derived numbers), career-ops (banned openers and buzzwords,
"could this sentence be in any letter?"), Reactive Resume (facts only, no clichés), Resume-Matcher
(facts only; eagerness is wanted, owner 2026-10-20). The writer and the reviewer are the first two opinions; these
notes go back to the writer once, they never set the letter's structure.
"""
from __future__ import annotations

import re

BANNED = ("i am writing to", "i'm writing to", "please accept my application", "perfect fit", "strong track record",
          "hit the ground running", "move the needle", "dream job",
          "data-driven", "holistic", "orchestrated", "synergy", "go-getter", "think outside the box",
          "i pride myself", "proven ability")
# Kept short on purpose: growing this list was whack-a-mole, the model just finds synonyms (2026-10-20).


def letter_text(content: dict) -> str:
    paras = (content.get("letter") or {}).get("paragraphs") or []
    return "\n\n".join(" ".join(str(c.get("text", "")) for c in p if isinstance(c, dict)) for p in paras)


def third_opinion(content: dict) -> list[str]:
    """Notes for the writer; empty when the letter passes."""
    text = letter_text(content)
    low = text.casefold()
    notes = [f'Cut the stock phrase "{b}" and say the specific thing instead.' for b in BANNED if b in low]
    if re.search(r"\[[^\]]+\]|\{[^}]+\}|<[a-z ]+>", text):
        notes.append("Remove placeholder text in brackets; write the real words or leave it out.")
    if "—" in text:
        notes.append("Replace em dashes with commas or full stops; people rarely type them.")
    if len(re.findall(r"[^.!?]+[.!?]", text)) and max((len(s.split()) for s in re.split(r"[.!?]", text)), default=0) > 40:
        notes.append("Split sentences over 40 words; read it aloud.")
    return notes
