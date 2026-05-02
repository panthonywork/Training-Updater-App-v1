import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChangeType(Enum):
    NO_CHANGE = "no_change"
    UPDATE = "update"
    GAP = "gap"


class ReviewState(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


@dataclass
class Section:
    index: int
    heading: str
    original_text: str
    change_type: ChangeType = ChangeType.NO_CHANGE
    proposed_text: Optional[str] = None
    review_state: ReviewState = ReviewState.PENDING
    final_text: Optional[str] = None
    classify_reason: Optional[str] = None
    paragraph_indices: list[int] = field(default_factory=list)
    processing_failed: bool = False

    def is_resolved(self) -> bool:
        return self.review_state != ReviewState.PENDING

    def effective_text(self) -> str:
        """Return the text that will be written to the output file."""
        if self.review_state == ReviewState.REJECTED or self.change_type == ChangeType.NO_CHANGE:
            return self.original_text
        if self.review_state == ReviewState.EDITED and self.final_text is not None:
            return self.final_text
        if self.review_state == ReviewState.ACCEPTED and self.proposed_text is not None:
            return self.proposed_text
        return self.original_text


def sections_to_json(sections: "list[Section]") -> str:
    return json.dumps([{
        "index": s.index,
        "heading": s.heading,
        "original_text": s.original_text,
        "change_type": s.change_type.value,
        "proposed_text": s.proposed_text,
        "review_state": s.review_state.value,
        "final_text": s.final_text,
        "classify_reason": s.classify_reason,
        "paragraph_indices": s.paragraph_indices,
        "processing_failed": s.processing_failed,
    } for s in sections])


def sections_from_json(data: str) -> "list[Section]":
    return [Section(
        index=d["index"],
        heading=d["heading"],
        original_text=d["original_text"],
        change_type=ChangeType(d["change_type"]),
        proposed_text=d.get("proposed_text"),
        review_state=ReviewState(d["review_state"]),
        final_text=d.get("final_text"),
        classify_reason=d.get("classify_reason"),
        paragraph_indices=d.get("paragraph_indices", []),
        processing_failed=d.get("processing_failed", False),
    ) for d in json.loads(data)]
