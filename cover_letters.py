from dotenv import load_dotenv
import subprocess
import PyPDF2
import os
from openai import OpenAI

load_dotenv()
RESUME_PATH = os.getenv("RESUME_PATH")
COVER_SAVE_PATH = os.getenv("COVER_SAVE_PATH")
TERMINAL = [s.strip().strip('"').strip("'") for s in os.getenv("TERMINAL").strip("[]").split(",")]
EDITOR = [s.strip().strip('"').strip("'") for s in os.getenv("EDITOR").strip("[]").split(",")]
FULL_NAME = os.getenv("FULL_NAME")
EMAIL = os.getenv("EMAIL")

# Files
TMP_DESCRIPTION = ".desc.tmp"
TMP_COVER = "tmp_cover.tex"
TMP_COVER_PDF = ".tmp_cover.pdf"
COVER_BACKUP = ".cover_letter_backup"

# LLM prompts
SYSTEM_PROMPT = """You are a professional cover letter writer. 
Write a compelling, personalized cover letter based on the provided resume and job description.
- Match the tone and style to the job description
- Highlight relevant skills and experience from the resume
- Keep it to 3-4 paragraphs (300-400 words)
- Use a professional but engaging tone
- Don't repeat the resume verbatim - expand on relevant points
- Include a call to action at the end"""

USER_PROMPT = """Resume:
{resume_text}

Job Description:
{job_description}

Please write a tailored cover letter for this position."""

# latex formating
COVER_START = """\\documentclass[11pt]{letter}

\\usepackage[margin=1in]{geometry}
\\usepackage{helvet}
\\renewcommand{\\familydefault}{\\sfdefault}
\\usepackage[T1]{fontenc}
\\usepackage{microtype}

\\begin{document}

Dear Hiring Manager,

"""

COVER_END = """

Kind Regards, {FULL_NAME} \\\\
{EMAIL}
\\end{document}
""".format(FULL_NAME=FULL_NAME, EMAIL=EMAIL, document="{document}")

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

def latexify(content) -> str:
    ## TODO: make this better, it is bad and only catches common exmples
    safe_content = content.replace("&", "\\&").replace("#", "//#")

    return COVER_START + safe_content + COVER_END

def generate_cover_letter(resume_text, job_description) -> str:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    user_prompt = USER_PROMPT.format(resume_text=resume_text, job_description=job_description)

    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        #temperature=1,
    )

    return response.choices[0].message.content

########### main workflow and loop ###########
def main(stdscr, uniq):
    stdscr.clear()

    if not os.path.exists(RESUME_PATH):
        print(f"Resume not found: {resume_path}")
        sys.exit(1)
    
    resume_text = read_resume(RESUME_PATH)
    stdscr.addstr(0,0, "Got Resume")
    stdscr.addstr(1,0, "Paste Description")
    stdscr.refresh()

    #with open(TMP_DESCRIPTION, "w") as f:
    #    f.write("Paste Description")
    
    subprocess.run(TERMINAL + EDITOR + [TMP_DESCRIPTION])
    
    with open(TMP_DESCRIPTION, "r") as f:
        job_description = f.read(). replace("\n\n", "\n")

    os.remove(TMP_DESCRIPTION)
    stdscr.addstr(1,0, "Got Description  ")
    stdscr.addstr(2,0, "Generating Cover")
    stdscr.refresh()

    cover_letter = generate_cover_letter(resume_text, job_description)
    l_cl = latexify(cover_letter)

    with open(TMP_COVER, "w") as f:
        f.write(l_cl)

    subprocess.run(TERMINAL + EDITOR + [TMP_COVER])
    
    (os.remove(TMP_COVER_PDF) if os.path.exists(TMP_COVER_PDF) else None)
    subprocess.run(["pdftexi2dvi", "--quiet", "--clean", f"--output={TMP_COVER_PDF}", TMP_COVER])
    subprocess.Popen(["firefox", "--new-window", os.path.join(os.getcwd(), TMP_COVER_PDF)])

    stdscr.addstr(3,0, "Opening in firefox as preview happy [y/n]: ")
    key = stdscr.getch()

    while True: 
        if key in [ord("y"), ord("Y")]:
            # write backup with hash of url and write pdf to wanted path
            with open(TMP_COVER, "r") as f:
                latex = f.read()

            os.makedirs(COVER_BACKUP, exist_ok=True)

            with open(os.path.join(os.getcwd(), COVER_BACKUP, f"{hash(uniq)}.tex"), "w") as f:
                f.write(latex)

            (os.remove(COVER_SAVE_PATH) if os.path.exists(COVER_SAVE_PATH) else None)
            subprocess.run(["pdftexi2dvi", "--quiet", "--clean", f"--output={COVER_SAVE_PATH}", TMP_COVER])
            (os.remove(TMP_COVER) if os.path.exists(TMP_COVER) else None)

            break
        elif key in [ord("n"), ord("N")]:
            subprocess.run(TERMINAL + EDITOR + [TMP_COVER])
            
            (os.remove(TMP_COVER_PDF) if os.path.exists(TMP_COVER_PDF) else None)
            subprocess.run(["pdftexi2dvi", "--quiet", "--clean", f"--output={TMP_COVER_PDF}", TMP_COVER])
            subprocess.Popen(["firefox", "--new-window", os.path.join(os.getcwd(), TMP_COVER_PDF)])
                 
        key = stdscr.getch()

