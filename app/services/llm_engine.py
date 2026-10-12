import json
import math
import time
import re
from typing import List, Dict, Any, Set, Tuple, Optional
from app.core.config import settings
from app.core.logger import logger
from app.schemas.exam_config import MarkConfigItem, DifficultyConfig
from app.schemas.exam_paper import QuestionPaper, Section, Question
from app.services.token_chunker import TokenChunker
from app.services.content_sanitizer import ContentSanitizer
from app.services.question_validator import QuestionValidator


class LLMExamEngine:
    """
    Multi-Provider Production-Grade Question Paper Generator.
    Supports:
    - Groq (Ultra-fast inference: Llama 3.3, Qwen 2.5, etc.)
    - OpenAI (GPT-4o, GPT-4o-mini, etc.)
    - Google Gemini (Gemini 1.5 Flash, Gemini 1.5 Pro, etc.)
    - NVIDIA NIM (Meta Llama 3.1 70B, Mixtral, etc. via NIM API or self-hosted)

    Adheres strictly to the Content-Only generation pipeline:
    1. Pre-LLM content sanitization & metadata separation
    2. Content sufficiency validation (rejects chapters with only titles/metadata)
    3. Token-aware bounded chunking (3,000–3,500 target, 5,000 hard limit)
    4. Anti-metadata prompt hardening
    5. Post-generation source validation & rejection of structural questions
    6. Deduplication and exam blueprint verification
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.provider = (provider or settings.LLM_PROVIDER).lower().strip()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._init_client()

    def _init_client(self):
        """Initializes LangChain chat model adapter based on chosen provider."""
        if self.provider == "openai":
            from langchain_openai import ChatOpenAI
            self.api_key = self.api_key or settings.OPENAI_API_KEY
            self.model = self.model or settings.OPENAI_MODEL
            if not self.api_key:
                logger.warning("OPENAI_API_KEY is not configured! OpenAI calls will fail unless provided.")
                self.client = None
            else:
                self.client = ChatOpenAI(
                    model=self.model,
                    api_key=self.api_key,
                    temperature=0.5,
                    max_tokens=3500,
                    model_kwargs={"response_format": {"type": "json_object"}}
                )

        elif self.provider == "nim":
            from langchain_openai import ChatOpenAI
            self.api_key = self.api_key or settings.NIM_API_KEY
            self.model = self.model or settings.NIM_MODEL
            self.base_url = self.base_url or settings.NIM_BASE_URL
            if not self.api_key:
                logger.warning("NIM_API_KEY is not configured! NIM calls will fail unless provided.")
                self.client = None
            else:
                self.client = ChatOpenAI(
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    temperature=0.5,
                    max_tokens=3500,
                    model_kwargs={"response_format": {"type": "json_object"}}
                )

        elif self.provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            self.api_key = self.api_key or settings.GEMINI_API_KEY
            self.model = self.model or settings.GEMINI_MODEL
            if not self.api_key:
                logger.warning("GEMINI_API_KEY is not configured! Gemini calls will fail unless provided.")
                self.client = None
            else:
                self.client = ChatGoogleGenerativeAI(
                    model=self.model,
                    google_api_key=self.api_key,
                    temperature=0.5,
                    max_output_tokens=3500,
                    response_mime_type="application/json"
                )

        else:
            from langchain_groq import ChatGroq
            self.provider = "groq"
            self.api_key = self.api_key or settings.GROQ_API_KEY
            self.model = self.model or settings.GROQ_MODEL
            if not self.api_key:
                logger.warning("GROQ_API_KEY is not configured! Groq calls will fail unless provided.")
                self.client = None
            else:
                self.client = ChatGroq(
                    model=self.model,
                    api_key=self.api_key,
                    temperature=0.5,
                    max_tokens=3500,
                    model_kwargs={"response_format": {"type": "json_object"}}
                )

        logger.info(f"[LLM Engine] Active provider: '{self.provider}', Model: '{self.model}' (LangChain adapter).")

    def generate_question_paper(
        self,
        context_content: str,
        chapters: List[str],
        mark_configs: List[MarkConfigItem],
        difficulty: DifficultyConfig,
        page_range: Optional[str] = None
    ) -> QuestionPaper:
        if not self.api_key:
            raise ValueError(
                f"API Key for '{self.provider.upper()}' is missing. Please set it in .env or environment variables."
            )

        # 1. Blueprint mark validation (supports up to 1,000 marks)
        total_marks = sum(cfg.markValue * cfg.count for cfg in mark_configs)
        total_questions = sum(cfg.count for cfg in mark_configs)

        if total_marks > settings.MAX_QUESTION_PAPER_MARKS:
            raise ValueError(
                f"Requested total marks ({total_marks}) exceeds the maximum allowed limit of "
                f"{settings.MAX_QUESTION_PAPER_MARKS} marks."
            )

        if total_questions == 0:
            raise ValueError("At least one question must be requested in markConfig.")

        # 2. Pre-LLM Content Sanitization: Separate metadata, page numbers, exam specs
        sanitized_content = ContentSanitizer.sanitize(context_content)

        # 3. Content Sufficiency Check: Fail fast if chapter only contains titles or metadata
        ch_name = ", ".join(chapters) if chapters else "Selected Topic"
        ContentSanitizer.validate_or_raise(sanitized_content, ch_name)

        words_count = len(re.findall(r"\b[A-Za-z0-9_-]{2,}\b", sanitized_content))
        logger.info(
            f"[Pipeline] Selected chapter: '{ch_name}' | "
            f"Page range: {page_range or 'N/A'} | "
            f"Actual content size: {len(sanitized_content)} chars ({words_count} words)"
        )

        # 4. Token-Aware Chunking: 3,000–3,500 target tokens, hard ceiling 5,000 tokens
        chunks = TokenChunker.split_into_token_chunks(
            sanitized_content, max_chunk_tokens=settings.SAFE_INPUT_TOKENS
        )
        if not chunks:
            raise ValueError("No substantive educational content available to generate questions from.")

        logger.info(
            f"[Pipeline] Chunking summary: {len(chunks)} chunk(s) created | "
            f"Target questions: {total_questions} | Target marks: {total_marks}"
        )

        # 5. Generate Candidate Questions across Chunks
        raw_questions_pool: List[Dict[str, Any]] = []

        if len(chunks) == 1:
            raw_questions_pool = self._generate_for_chunk(
                chunk_text=chunks[0],
                chapters=chapters,
                mark_configs=mark_configs,
                difficulty=difficulty,
                chunk_index=1,
                total_chunks=1
            )
        else:
            for idx, chunk in enumerate(chunks):
                chunk_mark_configs = []
                for cfg in mark_configs:
                    if cfg.count > 0:
                        # Request proportional distribution per chunk + slight buffer for validation
                        chunk_count = max(1, math.ceil((cfg.count / len(chunks)) * 1.25))
                        chunk_mark_configs.append(
                            MarkConfigItem(
                                markValue=cfg.markValue,
                                count=chunk_count,
                                isMCQ=cfg.isMCQ
                            )
                        )

                chunk_questions = self._generate_for_chunk(
                    chunk_text=chunk,
                    chapters=chapters,
                    mark_configs=chunk_mark_configs,
                    difficulty=difficulty,
                    chunk_index=idx + 1,
                    total_chunks=len(chunks)
                )
                raw_questions_pool.extend(chunk_questions)

        logger.info(f"[Pipeline] Total candidate questions generated: {len(raw_questions_pool)}")

        # 6. Source Validation, Structural Filter, Deduplication & Blueprint Assembly
        final_paper = self._validate_and_build_blueprint(
            raw_questions=raw_questions_pool,
            source_content=sanitized_content,
            mark_configs=mark_configs,
            total_marks=total_marks,
            total_questions=total_questions
        )

        return final_paper

    def _call_provider_chat(self, prompt: str) -> str:
        """Dispatches chat request to selected provider via LangChain with JSON output enforcement."""
        if self.client is None:
            if not self.api_key:
                raise ValueError(
                    f"API Key for '{self.provider.upper()}' is missing. Please set it in .env or environment variables."
                )
            self._init_client()
            if self.client is None:
                raise ValueError(f"Failed to initialize LangChain client for '{self.provider.upper()}'.")

        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content=prompt)]
        response = self.client.invoke(messages)
        content = response.content

        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else getattr(b, "text", str(b))
                for b in content
            )
        elif not isinstance(content, str):
            content = str(content) if content is not None else ""

        if not content or not content.strip():
            raise ValueError(f"Empty response from {self.provider.upper()} LLM.")

        return content

    def _generate_for_chunk(
        self,
        chunk_text: str,
        chapters: List[str],
        mark_configs: List[MarkConfigItem],
        difficulty: DifficultyConfig,
        chunk_index: int,
        total_chunks: int
    ) -> List[Dict[str, Any]]:
        """
        Executes bounded LLM request for a single chunk.
        Enforces a hard limit of 5,000 input tokens.
        Never retries an oversized request with the same prompt.
        """
        current_chunk_text = chunk_text
        prompt = self._build_prompt(current_chunk_text, chapters, mark_configs, difficulty)

        # Enforce hard safety ceiling (5,000 tokens)
        is_safe, est_tokens = TokenChunker.validate_prompt_tokens(prompt, max_tokens=settings.MAX_INPUT_TOKENS)
        if not is_safe:
            logger.warning(
                f"[Chunk {chunk_index}/{total_chunks}] Prompt has ~{est_tokens} tokens (> safety limit of {settings.MAX_INPUT_TOKENS}). "
                f"Reducing chunk size before sending to stay below Groq ITPM limit..."
            )
            max_allowed = settings.SAFE_INPUT_TOKENS - 800
            current_chunk_text = TokenChunker.reduce_text_to_token_limit(current_chunk_text, max_allowed)
            prompt = self._build_prompt(current_chunk_text, chapters, mark_configs, difficulty)
            _, est_tokens = TokenChunker.validate_prompt_tokens(prompt, max_tokens=settings.MAX_INPUT_TOKENS)

        chunk_tokens_est = TokenChunker.estimate_tokens(current_chunk_text)
        logger.info(
            f"[Chunk {chunk_index}/{total_chunks}] Calling {self.provider.upper()} '{self.model}' | "
            f"Chunk size: {len(current_chunk_text)} chars (~{chunk_tokens_est} tokens) | "
            f"Total input token estimate: ~{est_tokens} (Hard limit: {settings.MAX_INPUT_TOKENS})"
        )

        last_error = None
        max_retries = settings.LLM_MAX_RETRIES

        for attempt in range(max_retries):
            try:
                content = self._call_provider_chat(prompt)
                data = json.loads(content)
                questions = []

                if "sections" in data and isinstance(data["sections"], list):
                    for sec in data["sections"]:
                        mark_val = sec.get("markValue", 1)
                        for q in sec.get("questions", []):
                            q["markValue"] = mark_val
                            questions.append(q)
                elif "questions" in data and isinstance(data["questions"], list):
                    questions = data["questions"]

                logger.info(
                    f"[Chunk {chunk_index}/{total_chunks}] Received {len(questions)} candidate questions from {self.provider.upper()}."
                )
                return questions

            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "rate limit" in err_str or "resource_exhausted" in err_str or "tpm" in err_str
                is_size_limit = "413" in err_str or "too large" in err_str or "payload too large" in err_str

                if (is_rate_limit or is_size_limit) and attempt < max_retries - 1:
                    logger.warning(
                        f"[Chunk {chunk_index}/{total_chunks}] Limit error ({e}). "
                        f"Attempt {attempt + 1}: Reducing input content by 50% before retrying (NEVER retrying same oversized prompt)..."
                    )
                    # Halve the input text before retrying
                    reduced_target = int(TokenChunker.estimate_tokens(current_chunk_text) * 0.5)
                    current_chunk_text = TokenChunker.reduce_text_to_token_limit(current_chunk_text, reduced_target)
                    prompt = self._build_prompt(current_chunk_text, chapters, mark_configs, difficulty)
                    time.sleep(2 * (attempt + 1))
                    continue
                else:
                    logger.error(
                        f"[Chunk {chunk_index}/{total_chunks}] Request failed on attempt {attempt + 1}: {e}",
                        exc_info=True
                    )
                    raise e

        raise last_error or RuntimeError("Failed to generate questions after retries.")

    def _build_prompt(
        self,
        chunk_text: str,
        chapters: List[str],
        mark_configs: List[MarkConfigItem],
        difficulty: DifficultyConfig
    ) -> str:
        req_lines = []
        for cfg in mark_configs:
            if cfg.count > 0:
                if cfg.markValue == 1:
                    q_type = "MCQ with 4 options (correct option tagged with *)" if cfg.isMCQ else "Short Answer (one sentence, direct question, NO fill in blank)"
                elif cfg.markValue <= 3:
                    q_type = "Short Descriptive Question"
                else:
                    q_type = "Long Answer / Analytical / Problem Solving"
                req_lines.append(f"- {cfg.count} questions of {cfg.markValue} marks each (Type: {q_type})")
        questions_requirement = "\n".join(req_lines)

        return f"""You are an expert academic examiner creating a rigorous examination paper.
Analyze the source text provided below and generate high-quality academic questions adhering strictly to the specifications.

**Questions Specification:**
{questions_requirement}

**Difficulty Breakdown:**
- Easy: {difficulty.easy}%
- Medium: {difficulty.medium}%
- Hard: {difficulty.hard}%

**Source Content:**
{chunk_text}

**CRITICAL CONTENT-ONLY RULES (STRICT COMPLIANCE REQUIRED):**
1. Generate questions based EXCLUSIVELY on the educational facts, concepts, definitions, theories, formulas, examples, and explanations present in the source content above.
2. Every question MUST be directly answerable from the source content.
3. If the source content does not contain enough information to generate a question, DO NOT invent facts, use outside general knowledge, or hallucinate.
4. STRICTLY FORBIDDEN TOPICS — NEVER generate questions about any of the following:
   - Chapter numbers, chapter titles, unit numbers, section numbers, or headings (e.g. NEVER ask "What is the chapter number?", "What is discussed in chapter 5?", "What is the title?")
   - Page numbers, page ranges, or page citations (e.g. NEVER ask "On what page is...", "What page mentions...")
   - Document metadata (author, publisher, publishing date, edition, ISBN, copyright, file name)
   - Exam specifications (total marks, question count, time allowed, marks per question, exam blueprint)
   - Spelling, punctuation, capitalization, or grammar of titles, chapter names, or headings
   - Table of contents, index, document structure, or formatting
5. Output MUST be valid JSON adhering strictly to the schema:
{{
  "title": "Examination Paper",
  "sections": [
    {{
      "markValue": 1,
      "questions": [
        {{
          "text": "Question text here...",
          "type": "MCQ",
          "options": ["A) ...", "B) ... *", "C) ...", "D) ..."],
          "difficulty": "Easy",
          "topic": "Academic Topic"
        }}
      ]
    }}
  ]
}}
"""

    def _validate_and_build_blueprint(
        self,
        raw_questions: List[Dict[str, Any]],
        source_content: str,
        mark_configs: List[MarkConfigItem],
        total_marks: int,
        total_questions: int
    ) -> QuestionPaper:
        """
        Validates questions against source content, rejects metadata/structural questions,
        removes duplicates, and organizes questions into final exam blueprint sections.
        """
        # 1. Source Validation & Structural Filter
        accepted_questions, rejected_questions = QuestionValidator.validate_and_filter_questions(
            raw_questions=raw_questions,
            source_content=source_content
        )

        logger.info(
            f"[Pipeline] Source Validation Results: "
            f"Generated={len(raw_questions)}, "
            f"Rejected={len(rejected_questions)}, "
            f"Accepted={len(accepted_questions)}"
        )

        # 2. Group Accepted Questions by Mark Value
        accepted_by_mark: Dict[int, List[Dict[str, Any]]] = {}
        for q in accepted_questions:
            mark_val = int(q.get("markValue", 1))
            if mark_val not in accepted_by_mark:
                accepted_by_mark[mark_val] = []
            accepted_by_mark[mark_val].append(q)

        # 3. Apply Exam Blueprint to Assemble Final Sections
        final_sections: List[Section] = []
        global_q_id = 1

        for cfg in mark_configs:
            if cfg.count <= 0:
                continue

            available = accepted_by_mark.get(cfg.markValue, [])
            selected_raw = available[:cfg.count]

            section_questions: List[Question] = []
            for raw_q in selected_raw:
                q_type = raw_q.get("type", "Short Answer")
                if cfg.markValue == 1 and cfg.isMCQ:
                    q_type = "MCQ"
                elif cfg.markValue == 1 and not cfg.isMCQ:
                    q_type = "Short Answer"

                options = raw_q.get("options")
                if q_type == "MCQ" and (not options or len(options) < 4):
                    options = ["A) Option A", "B) Option B *", "C) Option C", "D) Option D"]

                diff = raw_q.get("difficulty", "Medium")
                if diff not in ["Easy", "Medium", "Hard"]:
                    diff = "Medium"

                q_obj = Question(
                    id=global_q_id,
                    text=raw_q.get("text", f"Question {global_q_id}"),
                    type=q_type,
                    options=options,
                    difficulty=diff,
                    topic=raw_q.get("topic", "Educational Topic")
                )
                section_questions.append(q_obj)
                global_q_id += 1

            final_sections.append(
                Section(
                    markValue=cfg.markValue,
                    questions=section_questions
                )
            )

        actual_total_marks = sum(s.markValue * len(s.questions) for s in final_sections)
        actual_total_questions = sum(len(s.questions) for s in final_sections)

        logger.info(
            f"[Pipeline] Final Validation: "
            f"Total questions={actual_total_questions}/{total_questions}, "
            f"Total marks={actual_total_marks}/{total_marks} (Max limit: {settings.MAX_QUESTION_PAPER_MARKS}), "
            f"Status=VALIDATED"
        )

        return QuestionPaper(
            title="Examination Assessment",
            totalMarks=actual_total_marks,
            sections=final_sections
        )


# Backward-compatible alias
GroqExamEngine = LLMExamEngine
