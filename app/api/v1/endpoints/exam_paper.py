import json
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.core.logger import logger
from app.core.task_store import task_store
from app.core.exceptions import ChapterNotFoundError, InsufficientSourceContentError
from app.schemas.exam_config import MarkConfigItem, DifficultyConfig
from app.schemas.exam_paper import QuestionPaper
from app.schemas.task_state import TaskResponse, TaskStatus
from app.services.text_extractor import TextExtractor
from app.services.docx_segmenter import DocxChapterSegmenter, TopicMarker
from app.services.chapter_segmenter import ChapterSegmenter
from app.services.llm_engine import LLMExamEngine, GroqExamEngine
from app.services.docx_generator import DocxGenerator

router = APIRouter()


def _parse_form_json_inputs(mark_config_str: str, difficulty_config_str: str):
    try:
        raw_marks = json.loads(mark_config_str) if mark_config_str else []
        if isinstance(raw_marks, list):
            mark_configs = [MarkConfigItem(**item) for item in raw_marks]
        elif isinstance(raw_marks, dict):
            mark_configs = [
                MarkConfigItem(markValue=int(k), count=int(v), isMCQ=(int(k) == 1))
                for k, v in raw_marks.items()
            ]
        else:
            mark_configs = []
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid markConfig JSON: {str(e)}")

    total_marks = sum(cfg.markValue * cfg.count for cfg in mark_configs)
    if total_marks > settings.MAX_QUESTION_PAPER_MARKS:
        raise HTTPException(
            status_code=400,
            detail=f"Requested total marks ({total_marks}) exceeds maximum allowed limit of {settings.MAX_QUESTION_PAPER_MARKS} marks."
        )

    try:
        raw_diff = json.loads(difficulty_config_str) if difficulty_config_str else {}
        difficulty = DifficultyConfig(**raw_diff)
    except Exception as e:
        difficulty = DifficultyConfig()

    return mark_configs, difficulty


def _validate_page_range(file_bytes: bytes, filename: str, page_start: Optional[int], page_end: Optional[int]) -> None:
    if page_start is None and page_end is None:
        return
    if page_start is not None and page_start < 1:
        raise HTTPException(status_code=400, detail="page_start must be at least 1.")
    if page_end is not None and page_end < 1:
        raise HTTPException(status_code=400, detail="page_end must be at least 1.")
    if page_start is not None and page_end is not None and page_end < page_start:
        raise HTTPException(status_code=400, detail="page_end must be greater than or equal to page_start.")
    if filename.lower().endswith(".pdf"):
        import pymupdf
        with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
            if page_start and page_start > doc.page_count:
                raise HTTPException(status_code=400, detail=f"page_start exceeds the PDF page count ({doc.page_count}).")
            if page_end and page_end > doc.page_count:
                raise HTTPException(status_code=400, detail=f"page_end exceeds the PDF page count ({doc.page_count}).")


def _background_generate_pipeline(
    task_id: str,
    file_bytes: bytes,
    filename: str,
    chapters_list: List[str],
    mark_configs: List[MarkConfigItem],
    difficulty: DifficultyConfig,
    provider: Optional[str] = None,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    use_entire_document: bool = False
):
    """
    Background asynchronous pipeline:
    1. Upload validation (DOCX or PDF up to configured limits)
    2. Chapter/section detection & metadata/content separation
    3. Selected chapter extraction (strict, NO whole-document fallback)
    4. Content sufficiency check (fails fast if only titles/metadata)
    5. Token-aware chunking (3,000–3,500 target, 5,000 ceiling)
    6. Multi-LLM question generation (Groq, OpenAI, Gemini, NIM)
    7. Post-generation source validation & structural question filter
    8. Deduplication & exam blueprint validation (up to 1,000 marks)
    9. Final Word (.docx) compilation
    """
    try:
        # Step 1: Validate the upload. Do not build a full-document text copy here:
        # the next step extracts only the requested chapter/topic. This keeps the
        # async path memory-bounded for large PDFs and DOCX files.
        TextExtractor.validate_file_size(file_bytes)
        file_size_mb = len(file_bytes) / (1024 * 1024)
        is_pdf = (filename or "").lower().endswith(".pdf")
        doc_type_str = "PDF" if is_pdf else "DOCX"

        task_store.update_task(
            task_id,
            status=TaskStatus.EXTRACTING,
            progress=15,
            message=f"Locating the selected chapter in the {doc_type_str} ({file_size_mb:.1f} MB)..."
        )

        # Step 2: Selected Chapter Extraction (strict, no silent fallback)
        task_store.update_task(
            task_id,
            progress=30,
            message=f"Locating and extracting selected chapter(s): {', '.join(chapters_list)}..."
        )

        if is_pdf:
            selected_targets = [] if use_entire_document else chapters_list
            chapter_content = ChapterSegmenter.extract_pdf_chapter_content(file_bytes, selected_targets, page_start, page_end)
        else:
            chapter_content = DocxChapterSegmenter.extract_chapter_content(file_bytes, chapters_list)

        logger.info(
            f"[Pipeline {task_id}] Extracted substantive chapter content: {len(chapter_content)} chars."
        )

        # Step 3: Content Sufficiency & Generation Dispatch
        engine = LLMExamEngine(provider=provider)
        active_provider = engine.provider.upper()

        task_store.update_task(
            task_id,
            status=TaskStatus.GENERATING,
            progress=50,
            message=f"Generating examination questions via {active_provider} ({engine.model})..."
        )

        paper: QuestionPaper = engine.generate_question_paper(
            context_content=chapter_content,
        chapters=chapters_list if not use_entire_document else ["Entire document"],
            mark_configs=mark_configs,
            difficulty=difficulty
        )

        # Step 4: Compiling Final Word (.docx) Document
        task_store.update_task(
            task_id,
            status=TaskStatus.RENDERING,
            progress=85,
            message="Compiling final Word (.docx) question paper..."
        )

        ch_str = ", ".join(chapters_list)
        doc = DocxGenerator.generate_docx(paper, chapters=ch_str)
        docx_file_path = settings.EXPORTS_DIR / f"{task_id}.docx"
        doc.save(str(docx_file_path))

        docx_url = f"/api/v1/tasks/{task_id}/download/docx"

        task_store.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Question paper generated successfully!",
            result=paper,
            docx_download_url=docx_url,
            log_message=f"Generated {paper.totalMarks} marks across {len(paper.sections)} sections. DOCX ready for download."
        )

    except InsufficientSourceContentError as e_ins:
        logger.error(f"[Pipeline {task_id}] Insufficient source content: {str(e_ins)}")
        task_store.update_task(
            task_id,
            status=TaskStatus.FAILED,
            progress=0,
            message="Insufficient educational content in selected chapter/topic",
            error=str(e_ins),
            log_message=str(e_ins)
        )
    except ChapterNotFoundError as e_ch:
        logger.error(f"[Pipeline {task_id}] Chapter not found: {str(e_ch)}")
        task_store.update_task(
            task_id,
            status=TaskStatus.FAILED,
            progress=0,
            message="Chapter not found in document",
            error=str(e_ch),
            log_message=str(e_ch)
        )
    except Exception as e:
        logger.error(f"[Pipeline {task_id}] Generation failed: {str(e)}", exc_info=True)
        task_store.update_task(
            task_id,
            status=TaskStatus.FAILED,
            progress=0,
            message="Generation failed",
            error=str(e),
            log_message=f"Error occurred: {str(e)}"
        )


# =========================================================================
# ASYNC TASK ENDPOINT (Supports DOCX up to 50 MB and PDF up to 500 pages)
# =========================================================================
@router.post(
    "/exam-papers/generate-async",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue async Question Paper generation (DOCX/PDF upload + Config)"
)
async def generate_exam_paper_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Textbook or curriculum file (DOCX or PDF up to 50 MB)"),
    chapters: str = Form("1", description="Comma-separated chapter numbers or topic titles (e.g. '1, 2' or 'Thermodynamics')"),
    markConfig: str = Form(..., description='JSON string: [{"markValue": 1, "count": 5, "isMCQ": true}]'),
    difficultyConfig: str = Form('{"easy": 30, "medium": 40, "hard": 30}', description="JSON string difficulty breakdown"),
    provider: Optional[str] = Form(None, description="LLM provider: 'groq' | 'openai' | 'gemini' | 'nim' (defaults to config)"),
    page_start: Optional[int] = Form(None, description="Optional 1-based first page to extract"),
    page_end: Optional[int] = Form(None, description="Optional 1-based last page to extract"),
    use_entire_document: bool = Form(False, description="Explicitly use the entire document when it contains one chapter")
):
    """
    Submits a textbook DOCX or PDF (up to 50 MB) for question paper generation.
    Returns immediately with a task_id to poll progress and download the compiled Word (.docx) paper.
    """
    filename_lower = (file.filename or "").lower()
    if not (filename_lower.endswith(".docx") or filename_lower.endswith(".pdf")):
        raise HTTPException(status_code=400, detail="Only Word (.docx) and PDF (.pdf) files are supported.")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        TextExtractor.validate_file_size(file_bytes)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    _validate_page_range(file_bytes, file.filename or "", page_start, page_end)

    mark_configs, difficulty = _parse_form_json_inputs(markConfig, difficultyConfig)
    chapters_list = [c.strip() for c in chapters.split(",") if c.strip()]
    if not chapters_list:
        raise HTTPException(status_code=400, detail="At least one chapter number or title is required.")

    task_id = task_store.create_task()

    background_tasks.add_task(
        _background_generate_pipeline,
        task_id=task_id,
        file_bytes=file_bytes,
        filename=file.filename or "",
        chapters_list=chapters_list,
        mark_configs=mark_configs,
        difficulty=difficulty,
        provider=provider,
        page_start=page_start,
        page_end=page_end,
        use_entire_document=use_entire_document
    )

    return task_store.get_task(task_id)


# =========================================================================
# MARKERS & TABLE OF CONTENTS DISCOVERY (DOCX / PDF)
# =========================================================================
@router.post(
    "/exam/docx/markers",
    response_model=List[TopicMarker],
    summary="Extract chapter & topic markers from document index & headings"
)
@router.post(
    "/exam/markers",
    response_model=List[TopicMarker],
    summary="Extract chapter & topic markers from uploaded document (DOCX or PDF)"
)
async def get_document_markers(
    file: UploadFile = File(..., description="Textbook Word (.docx) or PDF (.pdf) file")
):
    """
    Discovers all chapter and topic markers from the Table of Contents (TOC) and Headings.
    Returns normalized numbers, titles, start/end pages, and hierarchy levels.
    """
    filename_lower = (file.filename or "").lower()
    if not (filename_lower.endswith(".docx") or filename_lower.endswith(".pdf")):
        raise HTTPException(status_code=400, detail="Only Word (.docx) and PDF (.pdf) files are supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        TextExtractor.validate_file_size(file_bytes)
        if filename_lower.endswith(".pdf"):
            markers = await run_in_threadpool(ChapterSegmenter.parse_pdf_markers, file_bytes)
        else:
            markers = await run_in_threadpool(DocxChapterSegmenter.parse_document_markers, file_bytes)
        # The public discovery API is intentionally chapter-only. Child sections
        # remain attached to each chapter marker via child_topics.
        return [marker for marker in markers if marker.level == 1]

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error extracting markers: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to extract document markers: {str(e)}")


# =========================================================================
# SYNCHRONOUS DROP-IN REPLACEMENT (Direct Swagger test)
# =========================================================================
@router.post(
    "/exam/generate-questions",
    response_model=QuestionPaper,
    summary="Synchronous Direct Question Paper Generation (DOCX or PDF)"
)
async def generate_questions_sync(
    file: UploadFile = File(..., description="Textbook or syllabus file (DOCX or PDF)"),
    chapters: str = Form("1", description="Target chapter numbers or topic titles (e.g. '1, 2' or 'Thermodynamics')"),
    markConfig: str = Form(..., description='JSON array of sections mark configuration'),
    difficultyConfig: str = Form('{"easy": 30, "medium": 40, "hard": 30}', description="Difficulty distribution"),
    provider: Optional[str] = Form(None, description="LLM provider: 'groq' | 'openai' | 'gemini' | 'nim' (defaults to config)"),
    page_start: Optional[int] = Form(None),
    page_end: Optional[int] = Form(None),
    use_entire_document: bool = Form(False)
):
    """
    Synchronous endpoint for direct question paper generation.
    Accepts DOCX or PDF files.
    """
    filename_lower = (file.filename or "").lower()
    if not (filename_lower.endswith(".docx") or filename_lower.endswith(".pdf")):
        raise HTTPException(status_code=400, detail="Only Word (.docx) and PDF (.pdf) files are supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="No file uploaded")

    try:
        TextExtractor.validate_file_size(file_bytes)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    _validate_page_range(file_bytes, file.filename or "", page_start, page_end)

    mark_configs, difficulty = _parse_form_json_inputs(markConfig, difficultyConfig)
    chapters_list = [c.strip() for c in chapters.split(",") if c.strip()]
    if not chapters_list:
        raise HTTPException(status_code=400, detail="At least one chapter number or title is required.")

    try:
        # 1. Segment relevant content (PDF or DOCX)
        if filename_lower.endswith(".pdf"):
            context = ChapterSegmenter.extract_pdf_chapter_content(
                file_bytes, [] if use_entire_document else chapters_list, page_start, page_end
            )
        else:
            context = DocxChapterSegmenter.extract_chapter_content(file_bytes, chapters_list)

        # 2. LLM Generate with token-aware chunking and bounded requests
        engine = LLMExamEngine(provider=provider)
        paper = engine.generate_question_paper(
            context_content=context,
            chapters=chapters_list,
            mark_configs=mark_configs,
            difficulty=difficulty
        )

        return paper

    except InsufficientSourceContentError as e_ins:
        logger.warning(f"Sync generation insufficient content: {str(e_ins)}")
        return JSONResponse(
            status_code=422,
            content={
                "error": "Insufficient Source Content",
                "details": str(e_ins)
            }
        )
    except ChapterNotFoundError as e_ch:
        logger.warning(f"Sync generation chapter not found: {str(e_ch)}")
        return JSONResponse(
            status_code=404,
            content={
                "error": "Chapter Not Found",
                "details": str(e_ch)
            }
        )
    except Exception as e:
        logger.error(f"Sync generation error: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to generate questions: {str(e)}",
                "details": str(e)
            }
        )
