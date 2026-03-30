"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/retrieve/formatter.py
Description: Memory Cards formatter for LLM context injection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import List

from memory.memory.models.memory_entry import MemoryCard


class Formatter:
    """
    Format Memory Cards into structured text for LLM context injection.

    Output grouped by confidence: HIGH / MODERATE / LOW.
    """

    @staticmethod
    def format_cards(cards: List[MemoryCard]) -> str:
        """
        Format a list of MemoryCards into context block.

        Returns empty string if no cards — "better empty than dirty".
        """
        if not cards:
            return ""

        high = [c for c in cards if c.confidence == "high"]
        moderate = [c for c in cards if c.confidence == "moderate"]
        low = [c for c in cards if c.confidence == "low"]

        lines = ["[MEMORY CONTEXT — retrieved, not part of conversation]", ""]

        if high:
            lines.append("[HIGH CONFIDENCE — confirmed facts]")
            for card in high:
                lines.append(f"- {card.content}")
            lines.append("")

        if moderate:
            lines.append("[MODERATE CONFIDENCE — recent context]")
            for card in moderate:
                lines.append(f"- {card.content}")
            lines.append("")

        if low:
            lines.append("[LOW CONFIDENCE — verify if relevant]")
            for card in low:
                lines.append(f"- {card.content}")
            lines.append("")

        lines.append("[END MEMORY CONTEXT]")
        return "\n".join(lines)


__all__ = ["Formatter"]
