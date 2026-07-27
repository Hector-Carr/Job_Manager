from dotenv import load_dotenv
import subprocess
import tempfile
import textwrap
import hashlib
import shutil
import curses
import PyPDF2
import os
import re
import anthropic

load_dotenv()
RESUME_PATH = os.getenv("RESUME_PATH")
COVER_SAVE_PATH = os.getenv("COVER_SAVE_PATH")
TERMINAL = [s.strip().strip('"').strip("'") for s in os.getenv("TERMINAL").strip("[]").split(",")]
EDITOR = [s.strip().strip('"').strip("'") for s in os.getenv("EDITOR").strip("[]").split(",")]
FULL_NAME = os.getenv("FULL_NAME")
EMAIL = os.getenv("EMAIL")

MODEL = "claude-opus-5"
EFFORT = "medium"   # low | medium | high | xhigh | max - raise if drafts feel shallow
MAX_TOKENS = 16000  # covers thinking + the letter; opus 5 thinks by default

# Files
TMP_DESCRIPTION = ".desc.tmp"
TMP_COVER = "tmp_cover.tex"
TMP_COVER_PDF = ".tmp_cover.pdf"
COVER_BACKUP = ".cover_letter_backup"

# latex template the model must follow
TEMPLATE = """\\documentclass[11pt]{{letter}}

\\usepackage[margin=1in]{{geometry}}
\\usepackage{{helvet}}
\\renewcommand{{\\familydefault}}{{\\sfdefault}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{microtype}}

\\begin{{document}}

Dear Hiring Manager,

<body paragraphs go here, blank line between each>

Kind Regards, {FULL_NAME} \\\\
{EMAIL}
\\end{{document}}
""".format(FULL_NAME=FULL_NAME, EMAIL=EMAIL)

# LLM prompts
SYSTEM_PROMPT = """You are a professional cover letter writer who works directly in LaTeX.

You produce a complete, compilable LaTeX document and revise it when the user asks.

Content rules:
- Match the tone and style to the job description
- Highlight relevant skills and experience from the resume
- Keep the body to 3-4 paragraphs (300-400 words)
- Use a professional but engaging tone
- Don't repeat the resume verbatim - expand on relevant points
- Include a call to action at the end
- Address it to a named person if the job description gives one, otherwise "Dear Hiring Manager,"
- Sign off as {FULL_NAME} with {EMAIL} underneath

LaTeX rules:
- Output the ENTIRE document, from \\documentclass through \\end{{document}}
- Escape LaTeX specials in prose: & % $ # _ {{ }} must be backslash-escaped
- It must compile with pdflatex using only the packages in the template below
- Keep the preamble exactly as given unless the user asks you to change it
- Output LaTeX source ONLY - no markdown, no code fences, no commentary before or after

Template:
{TEMPLATE}""".format(FULL_NAME=FULL_NAME, EMAIL=EMAIL, TEMPLATE=TEMPLATE)

FIRST_DRAFT_PROMPT = """Resume:
{resume_text}

Job Description:
{job_description}

Write a tailored cover letter for this position, as a complete LaTeX document."""

MANUAL_EDIT_PROMPT = """I edited the LaTeX by hand. This is now the current version - base your next revision on it:

{latex}"""

COMPILE_ERROR_PROMPT = """That document failed to compile with pdflatex. The errors were:

{errors}

Return the full corrected document."""


############ helpers ##########
def read_resume(path) -> str:
    text = ""
    likely_type = path.split(".")[-1]

    if likely_type == "pdf":
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"

    elif likely_type == "txt":
        with open(path, "r") as f:
            text = f.read()

    else:
        raise Exception(f"unknown resume file suffix {likely_type}")

    return text


def strip_fences(text) -> str:
    """models like wrapping latex in ```latex ... ``` no matter how nicely you ask"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def latex_body_as_prose(latex) -> str:
    """pull the readable prose out of the document so it can be shown in the transcript"""
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", latex, re.DOTALL)
    body = m.group(1) if m else latex

    body = body.replace("\\\\", "")
    body = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", "", body)
    body = re.sub(r"\\([&%$#_{}])", r"\1", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def word_count(latex) -> int:
    return len(latex_body_as_prose(latex).split())


def compile_pdf(tex_path, pdf_path):
    """returns (ok, error_text). builds in a temp dir so no aux files land in the repo"""
    if os.path.exists(pdf_path):
        os.remove(pdf_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
             f"-output-directory={tmpdir}", os.path.abspath(tex_path)],
            capture_output=True, text=True,
        )

        built = os.path.join(tmpdir, os.path.splitext(os.path.basename(tex_path))[0] + ".pdf")

        if proc.returncode == 0 and os.path.exists(built):
            shutil.copyfile(built, pdf_path)
            return True, ""

        output = (proc.stdout or "") + (proc.stderr or "")
        errors = [ln for ln in output.splitlines() if ln.startswith("!") or ln.startswith("l.")]
        return False, "\n".join(errors[:12]) or output[-800:]


def preview_pdf(pdf_path):
    subprocess.Popen(
        ["firefox", "--new-window", os.path.join(os.getcwd(), pdf_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def open_in_editor(path):
    subprocess.run(TERMINAL + EDITOR + [path])


############ the chat ##########
class ChatError(Exception):
    """anything that stopped us getting a draft back, already phrased for the transcript"""


class CoverLetterChat:
    def __init__(self, resume_text, job_description):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        # the resume + job description never change, so cache them as a prefix and
        # let each round of feedback ride on top
        self.messages = [{
            "role": "user",
            "content": [{
                "type": "text",
                "text": FIRST_DRAFT_PROMPT.format(
                    resume_text=resume_text, job_description=job_description),
                "cache_control": {"type": "ephemeral"},
            }],
        }]

        self.latex = ""       # what is on disk right now
        self.last_reply = ""  # what the model last returned, to spot manual edits
        self.drafts = 0

    def note_manual_edit(self, latex):
        """called after the user edits the .tex so the next revision builds on their version"""
        self.latex = latex
        if latex.strip() != self.last_reply.strip():
            self.messages.append({"role": "user", "content": MANUAL_EDIT_PROMPT.format(latex=latex)})
            self.last_reply = latex

    def send(self, feedback=None):
        if feedback:
            self.messages.append({"role": "user", "content": feedback})

        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=self.messages,
                output_config={"effort": EFFORT},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise ChatError("ANTHROPIC_API_KEY was rejected - check the key in .env")
        except anthropic.RateLimitError:
            raise ChatError("Rate limited by the API, wait a moment and try again")
        except anthropic.APIConnectionError:
            raise ChatError("Could not reach the API - check your connection")
        except anthropic.APIStatusError as e:
            raise ChatError(f"API error {e.status_code}: {e.message}")

        if response.stop_reason == "refusal":
            raise ChatError("The model declined to answer that request")

        # thinking blocks come back alongside the text, so pull out the text only
        reply = strip_fences("".join(b.text for b in response.content if b.type == "text"))
        if not reply:
            raise ChatError(f"Empty response from the model (stop_reason: {response.stop_reason})")

        # echo the full content back so thinking blocks survive the next turn
        self.messages.append({"role": "assistant", "content": response.content})
        self.latex = reply
        self.last_reply = reply
        self.drafts += 1
        return reply


############ the tui ##########
class ChatUI:
    def __init__(self, stdscr, chat, uniq):
        self.stdscr = stdscr
        self.chat = chat
        self.uniq = uniq
        self.entries = []   # [{"role": you|ai|sys, "text": str}]
        self.scroll = 0
        self.follow = True  # stick to the bottom until the user scrolls up
        self.status = ""

    ##### drawing #####
    def say(self, role, text):
        self.entries.append({"role": role, "text": text})
        self.follow = True

    def addstr(self, y, x, text, attr=curses.A_NORMAL):
        """curses throws if you write to the last cell of the screen"""
        if y < 0 or y >= self.my or x >= self.mx:
            return
        try:
            self.stdscr.addstr(y, x, text[:self.mx - x - 1], attr)
        except curses.error:
            pass

    def transcript_lines(self):
        labels = {"you": "You", "ai": "AI ", "sys": "-- "}
        width = self.mx - 5
        lines = []

        for entry in self.entries:
            label = labels.get(entry["role"], "   ")
            first = True
            for para in entry["text"].split("\n"):
                if not para.strip():
                    lines.append(("", entry["role"]))
                    continue
                for chunk in textwrap.wrap(para, max(10, width)):
                    prefix = f"{label} " if first else "    "
                    lines.append((prefix + chunk, entry["role"]))
                    first = False
            lines.append(("", entry["role"]))

        return lines

    def draw(self):
        self.my, self.mx = self.stdscr.getmaxyx()
        self.stdscr.erase()

        body_top = 2
        body_h = max(1, self.my - 5)

        header = f"Cover letter chat - draft {self.chat.drafts}" if self.chat.drafts else "Cover letter chat"
        self.addstr(0, 0, header.ljust(self.mx), curses.A_REVERSE)

        lines = self.transcript_lines()
        max_scroll = max(0, len(lines) - body_h)
        if self.follow:
            self.scroll = max_scroll
        self.scroll = max(0, min(self.scroll, max_scroll))

        for i in range(body_h):
            idx = self.scroll + i
            if idx >= len(lines):
                break
            text, role = lines[idx]
            attr = curses.A_BOLD if role == "you" else curses.A_DIM if role == "sys" else curses.A_NORMAL
            self.addstr(body_top + i, 0, text, attr)

        if self.status:
            self.addstr(self.my - 3, 0, self.status.ljust(self.mx), curses.A_BOLD)

        self.addstr(
            self.my - 1, 0,
            "[c] chat  [e] edit tex  [p] preview  [y] save  [r] restart  [^v] scroll  [q] discard",
            curses.A_DIM,
        )
        self.stdscr.refresh()

    def set_status(self, text):
        self.status = text
        self.draw()

    ##### input #####
    def prompt(self, label):
        """single line input, returns None if cancelled"""
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        buf = ""

        try:
            while True:
                self.draw()
                shown = f"{label}{buf}"
                overflow = max(0, len(shown) - (self.mx - 2))
                self.addstr(self.my - 2, 0, shown[overflow:].ljust(self.mx - 1))
                self.stdscr.move(self.my - 2, min(len(shown), self.mx - 2))
                self.stdscr.refresh()

                key = self.stdscr.getch()

                if key in [curses.KEY_BACKSPACE, 127, 8]:
                    buf = buf[:-1]
                elif key in [ord("\n"), curses.KEY_ENTER, 10, 13]:
                    return buf.strip() or None
                elif key == 27:
                    return None
                elif key == curses.KEY_RESIZE:
                    continue
                elif 32 <= key < 127:
                    buf += chr(key)
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def confirm(self, question):
        self.set_status(question + " [y/n]")
        while True:
            key = self.stdscr.getch()
            if key in [ord("y"), ord("Y")]:
                return True
            if key in [ord("n"), ord("N"), 27, ord("q"), ord("Q")]:
                return False

    ##### actions #####
    def write_and_preview(self, fix_attempts=0):
        """write current latex to disk, compile, preview. offers to hand errors back to the ai"""
        with open(TMP_COVER, "w") as f:
            f.write(self.chat.latex)

        self.set_status("Compiling...")
        ok, errors = compile_pdf(TMP_COVER, TMP_COVER_PDF)

        if ok:
            preview_pdf(TMP_COVER_PDF)
            self.set_status("")
            return True

        self.say("sys", f"LaTeX failed to compile:\n{errors}")
        self.status = ""

        if fix_attempts >= 2:
            self.say("sys", "Still not compiling after 2 attempts - fix it by hand with [e].")
            return False

        if self.confirm("Ask the AI to fix the compile error?"):
            self.revise(COMPILE_ERROR_PROMPT.format(errors=errors),
                        show="(sent compile errors)", role="sys", fix_attempts=fix_attempts + 1)
        else:
            self.status = ""
        return False

    def revise(self, feedback, show=None, role="you", fix_attempts=0):
        self.say(role if feedback else "sys", show or feedback)
        self.set_status("Generating...")

        try:
            latex = self.chat.send(feedback)
        except ChatError as e:
            self.status = ""
            self.say("sys", str(e))
            return
        except Exception as e:
            self.status = ""
            self.say("sys", f"Unexpected error: {e}")
            return

        self.say("ai", f"Draft {self.chat.drafts} ({word_count(latex)} words)\n\n{latex_body_as_prose(latex)}")
        self.write_and_preview(fix_attempts)

    def edit_tex(self):
        with open(TMP_COVER, "w") as f:
            f.write(self.chat.latex)

        open_in_editor(TMP_COVER)

        with open(TMP_COVER, "r") as f:
            edited = f.read()

        if edited.strip() == self.chat.latex.strip():
            self.say("sys", "No changes made in the editor.")
            return

        self.chat.note_manual_edit(edited)
        self.say("sys", f"You edited the LaTeX by hand ({word_count(edited)} words). The AI will build on your version.")
        self.write_and_preview()

    def save(self):
        with open(TMP_COVER, "w") as f:
            f.write(self.chat.latex)

        self.set_status("Compiling final...")
        ok, errors = compile_pdf(TMP_COVER, TMP_COVER_PDF)
        if not ok:
            self.status = ""
            self.say("sys", f"Refusing to save, it does not compile:\n{errors}")
            return False

        os.makedirs(COVER_BACKUP, exist_ok=True)
        stamp = hashlib.sha1(self.uniq.encode()).hexdigest()[:16]
        with open(os.path.join(os.getcwd(), COVER_BACKUP, f"{stamp}.tex"), "w") as f:
            f.write(self.chat.latex)

        if os.path.exists(COVER_SAVE_PATH):
            os.remove(COVER_SAVE_PATH)
        compile_pdf(TMP_COVER, COVER_SAVE_PATH)

        for path in [TMP_COVER, TMP_COVER_PDF]:
            if os.path.exists(path):
                os.remove(path)

        return True

    ##### loop #####
    def run(self):
        while True:
            self.draw()
            page = max(1, self.my - 6)
            key = self.stdscr.getch()

            if key in [ord("c"), ord("C"), ord("\n"), curses.KEY_ENTER, 10, 13]:
                feedback = self.prompt("> ")
                if feedback:
                    self.revise(feedback)

            elif key in [ord("e"), ord("E")]:
                self.edit_tex()

            elif key in [ord("p"), ord("P")]:
                self.write_and_preview()

            elif key in [ord("r"), ord("R")]:
                if self.confirm("Throw away this draft and generate a fresh one?"):
                    self.revise("Start over and write a completely new cover letter from scratch, "
                                "taking a different angle to the drafts so far.",
                                show="(restart - new draft from scratch)")

            elif key in [ord("y"), ord("Y")]:
                if self.save():
                    return True

            elif key in [curses.KEY_UP, ord("k")]:
                self.scroll -= 1
                self.follow = False
            elif key in [curses.KEY_DOWN, ord("j")]:
                self.scroll += 1
                self.follow = False
            elif key == curses.KEY_PPAGE:
                self.scroll -= page
                self.follow = False
            elif key == curses.KEY_NPAGE:
                self.scroll += page
                self.follow = False

            elif key in [27, ord("q"), ord("Q")]:
                if self.confirm("Discard this cover letter?"):
                    for path in [TMP_COVER, TMP_COVER_PDF]:
                        if os.path.exists(path):
                            os.remove(path)
                    return False
                self.status = ""


########### main workflow ###########
def get_job_description(stdscr):
    stdscr.clear()
    stdscr.addstr(0, 0, "Paste the job description in the editor, then save and quit.")
    stdscr.refresh()

    open_in_editor(TMP_DESCRIPTION)

    if not os.path.exists(TMP_DESCRIPTION):
        return None

    with open(TMP_DESCRIPTION, "r") as f:
        job_description = f.read().replace("\n\n", "\n").strip()

    os.remove(TMP_DESCRIPTION)
    return job_description or None


def main(stdscr, uniq):
    stdscr.clear()

    if not RESUME_PATH or not os.path.exists(RESUME_PATH):
        stdscr.addstr(0, 0, f"Resume not found: {RESUME_PATH} - press any key")
        stdscr.getch()
        return

    resume_text = read_resume(RESUME_PATH)

    job_description = get_job_description(stdscr)
    if not job_description:
        stdscr.clear()
        stdscr.addstr(0, 0, "No job description given, aborting - press any key")
        stdscr.getch()
        return

    chat = CoverLetterChat(resume_text, job_description)
    ui = ChatUI(stdscr, chat, uniq)

    ui.say("sys", f"Resume loaded, job description captured ({len(job_description.split())} words).")
    ui.revise(None, show="(generate first draft)")

    ui.run()
    stdscr.clear()


if __name__ == "__main__":
    curses.wrapper(main, "https://example.com/test-job")
