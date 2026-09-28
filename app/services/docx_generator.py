import io
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from app.schemas.exam_paper import QuestionPaper

class DocxGenerator:
    @staticmethod
    def generate_docx(paper: QuestionPaper, chapters: str = "") -> Path:
        """
        Creates an academic Word document (.docx) with question paper layout
        and an appended Answer Key on a separate page.
        """
        doc = Document()

        # Page margins
        for section in doc.sections:
            section.top_margin = Inches(0.8)
            section.bottom_margin = Inches(0.8)
            section.left_margin = Inches(0.8)
            section.right_margin = Inches(0.8)

        # Header: School Name
        p_school = doc.add_paragraph()
        p_school.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_school = p_school.add_run("EXAMINATION ASSESSMENT\n")
        r_school.bold = True
        r_school.font.size = Pt(16)
        r_school.font.color.rgb = RGBColor(30, 41, 59)

        # Title
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_title = p_title.add_run(f"{paper.title.upper()}\n")
        r_title.bold = True
        r_title.font.size = Pt(13)

        # Metadata Row
        p_meta = doc.add_paragraph()
        p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        ch_text = f"Chapters: {chapters}   |   " if chapters else ""
        r_meta = p_meta.add_run(f"{ch_text}Time: 3 Hours   |   Maximum Marks: {paper.totalMarks}")
        r_meta.bold = True
        r_meta.font.size = Pt(10)
        r_meta.font.color.rgb = RGBColor(71, 85, 105)

        # Divider line
        p_div = doc.add_paragraph("─" * 60)
        p_div.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_div.paragraph_format.space_after = Pt(14)

        # Question Index Counter
        global_q_index = 1
        answer_key_entries = []

        # Sections & Questions
        for sec_idx, section in enumerate(paper.sections):
            sec_char = chr(65 + sec_idx)
            p_sec = doc.add_paragraph()
            p_sec.paragraph_format.space_before = Pt(12)
            p_sec.paragraph_format.space_after = Pt(6)
            
            r_sec = p_sec.add_run(f"SECTION {sec_char} ({section.markValue} Mark Questions)")
            r_sec.bold = True
            r_sec.font.size = Pt(11)
            r_sec.font.color.rgb = RGBColor(15, 23, 42)

            for q in section.questions:
                p_q = doc.add_paragraph()
                p_q.paragraph_format.left_indent = Inches(0.2)
                p_q.paragraph_format.space_after = Pt(4)

                # Question text
                p_q.add_run(f"{global_q_index}.  {q.text} ").bold = False
                
                # Mark badge on right
                r_mark = p_q.add_run(f"[{section.markValue}]")
                r_mark.bold = True

                # Options for MCQ (remove * for student paper)
                if q.type == "MCQ" and q.options:
                    correct_opt = ""
                    for opt in q.options:
                        if "*" in opt:
                            correct_opt = opt.replace("*", "").strip()
                        clean_opt = opt.replace("*", "").strip()
                        p_opt = doc.add_paragraph()
                        p_opt.paragraph_format.left_indent = Inches(0.5)
                        p_opt.paragraph_format.space_after = Pt(2)
                        p_opt.add_run(clean_opt)

                    if correct_opt:
                        answer_key_entries.append((global_q_index, correct_opt, q.topic))
                else:
                    answer_key_entries.append((global_q_index, f"Subjective ({section.markValue} marks criteria)", q.topic))

                global_q_index += 1

        # ==========================================
        # PAGE BREAK: TEACHER'S ANSWER KEY
        # ==========================================
        doc.add_page_break()
        p_ans_header = doc.add_paragraph()
        p_ans_header.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_ans_h = p_ans_header.add_run("TEACHER'S ANSWER KEY & MARKING SCHEME\n")
        r_ans_h.bold = True
        r_ans_h.font.size = Pt(14)
        r_ans_h.font.color.rgb = RGBColor(185, 28, 28)

        p_ans_sub = doc.add_paragraph("Confidential - For Evaluator Reference Only\n")
        p_ans_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_ans_sub.paragraph_format.space_after = Pt(14)

        for q_num, ans_text, topic in answer_key_entries:
            p_ak = doc.add_paragraph()
            p_ak.paragraph_format.left_indent = Inches(0.2)
            p_ak.paragraph_format.space_after = Pt(3)
            p_ak.add_run(f"Q{q_num}. ").bold = True
            p_ak.add_run(f"Answer: {ans_text}  ").bold = False
            r_top = p_ak.add_run(f"[Topic: {topic}]")
            r_top.italic = True
            r_top.font.color.rgb = RGBColor(100, 116, 139)

        return doc
