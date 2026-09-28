from typing import List, Optional
from pydantic import BaseModel, Field

class Question(BaseModel):
    id: int = Field(..., description="Sequential question identifier")
    text: str = Field(..., description="The question text")
    type: str = Field(..., description="Type: 'MCQ' | 'Short Answer' | 'Descriptive' | 'Long Answer'")
    options: Optional[List[str]] = Field(default=None, description="Array of 4 options for MCQ (correct option flagged with *)")
    difficulty: str = Field(..., description="'Easy' | 'Medium' | 'Hard'")
    topic: str = Field(..., description="Topic or syllabus concept")

class Section(BaseModel):
    markValue: int = Field(..., description="Marks assigned to each question in this section")
    questions: List[Question] = Field(..., description="List of questions within this section")

class QuestionPaper(BaseModel):
    title: str = Field(default="AI Question Paper", description="Title of the examination paper")
    totalMarks: int = Field(..., description="Grand total marks of all questions combined")
    sections: List[Section] = Field(..., description="Sections grouped by mark value")
