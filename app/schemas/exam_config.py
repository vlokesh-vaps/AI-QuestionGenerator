from typing import Optional, List
from pydantic import BaseModel, Field

class MarkConfigItem(BaseModel):
    markValue: int = Field(..., ge=1, description="Mark value per question (e.g., 1, 2, 5, 10)")
    count: int = Field(..., ge=0, description="Total number of questions for this mark value")
    isMCQ: Optional[bool] = Field(default=False, description="True if 1-mark question should be MCQ with 4 options")

class DifficultyConfig(BaseModel):
    easy: int = Field(default=30, ge=0, le=100, description="Percentage of easy questions")
    medium: int = Field(default=40, ge=0, le=100, description="Percentage of medium questions")
    hard: int = Field(default=30, ge=0, le=100, description="Percentage of hard questions")
