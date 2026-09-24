from typing import Any, Optional

from pydantic import BaseModel, Field


class FeedbackTrackerUpdateRequest(BaseModel):
    status: str = Field(default="pending")
    priority: Optional[str] = None
    owner: Optional[str] = None
    review_status: str = Field(default="pending")
    review_note: Optional[str] = None
    acceptance_issue: Optional[str] = None
    acceptance_feedback: Optional[str] = None
    adjusted_conversation: Optional[list[dict[str, Any]]] = None


class FeedbackSuggestionUpdateRequest(BaseModel):
    suggestion: str = Field(min_length=1)


class RegressionCaseUpdateRequest(BaseModel):
    status: str = Field(default="ready_for_review")
    owner: Optional[str] = None
    review_status: str = Field(default="pending")
    review_note: Optional[str] = None
