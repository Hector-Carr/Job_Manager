import sqlite3
import subprocess
import curses
import os
import importlib
import time
from jobs_db import DB_PATH

#from "update_jobs" import query_ as "query_update"
module = importlib.import_module("update_jobs")
query_update = getattr(module, "query_")                                                                                                                                                                                                                                                                                    

def get_jobs_by_status(status_filter=None):
    conn = sqlite3.connect(DB_PATH)
    if status_filter:
        cursor = conn.execute(
            "SELECT reference_url, job_title, company, status FROM jobs WHERE status = ? ORDER BY rowid DESC",
            (status_filter,)
        )
    else:
        cursor = conn.execute("SELECT reference_url, job_title, company, status FROM jobs ORDER BY rowid DESC")
    jobs = cursor.fetchall()
    conn.close()
    return jobs

def update_status(reference_url, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET status = ? WHERE reference_url = ?", (status, reference_url))
    conn.commit()
    conn.close()

def open_in_firefox(url):
    subprocess.Popen(["firefox", "--new-window", url])

def write_cover_letter(company, job_title):
    filename = f"cover_letter_{company.replace(' ', '_')}.txt"
    with open(filename, "w") as f:
        f.write(f"Dear Hiring Manager,\n\n")
        f.write(f"I am writing to apply for the {job_title} position at {company}.\n\n")
        f.write(f"[Your cover letter content here]\n\n")
        f.write(f"Best regards,\n[Your Name]")
    return filename

def draw_job_list(stdscr, jobs, selected, status_filter, start_idx):
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    
    title = f"Jobs - {status_filter if status_filter else 'All'} ({len(jobs)} jobs)"
    stdscr.addstr(0, 0, title[:width-1], curses.A_REVERSE)
    stdscr.addstr(0, width - 30, "[↑↓] scroll  [click]", curses.A_DIM)
    
    jobs = jobs[start_idx:]
    start_row = 2
    visible_rows = height - 5
    clean = " "*width
    
    if not jobs:
        stdscr.addstr(start_row, 0, "No jobs found")
        return 0, 0, 0 
    
    for job_idx in range(min(len(jobs), visible_rows)):
        job = jobs[job_idx]
        y = job_idx + start_row
        
        prefix = ">" if job_idx == selected else " "
        status_color = curses.A_REVERSE if job_idx == selected else curses.color_pair(1) if job[3] == "pending" else curses.color_pair(2) if job[3] == "applied" else curses.color_pair(3) if job[3] == "excluded" else curses.A_REVERSE

        stdscr.addstr(y, 0, clean, status_color)
        stdscr.addstr(y, 0, f"{prefix} {job[1][:(width//3)*2-2]}", status_color)
        stdscr.addstr(y, (width//3)*2, f"| {job[2][:width//3-2]}", status_color)
    
    return start_row, visible_rows, start_idx

def draw_status_menu(stdscr, current):
    height, width = stdscr.getmaxyx()
    options = ["All", "pending", "excluded", "applied"]
    
    stdscr.addstr(0, 0, "Filter by status:", curses.A_REVERSE)
    
    x = 20
    for opt in options:
        if opt == current:
            stdscr.addstr(0, x, f" [{opt}] ", curses.A_BOLD)
        else:
            stdscr.addstr(0, x, f" {opt} ", curses.A_DIM)
        x += len(opt) + 4

def job_detail_menu(stdscr, job):
    reference_url, job_title, company, status = job
    selected = 0
    options = [
        "Open job in Firefox",
        "Write cover letter",
        "Mark as applied",
        "Mark as excluded",
        "Mark as pending",
        "Back",
    ]
    
    while True:
        height, width = stdscr.getmaxyx()
        stdscr.clear()
        
        stdscr.addstr(0, 0, f"{job_title} at {company}", curses.A_REVERSE)
        stdscr.addstr(1, 0, f"Status: {status}", curses.color_pair(1) if status == "pending" else curses.color_pair(2) if status == "applied" else curses.color_pair(3) if status == "excluded" else curses.color_pair(3))
        
        for i, opt in enumerate(options):
            prefix = ">" if i == selected else " "
            stdscr.addstr(i + 3, 0, f"{prefix} {opt}")
        
        key = stdscr.getch()
        
        if key == curses.KEY_UP:
            selected = (selected - 1) % len(options)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(options)
        elif key in [ord('\n'), curses.KEY_ENTER, 10, 13]:
            if selected == 0:
                open_in_firefox(reference_url)
            elif selected == 1:
                filename = write_cover_letter(company, job_title)
                stdscr.addstr(height - 1, 0, f"Created {filename}")
                stdscr.getch()
            elif selected == 2:
                update_status(reference_url, "applied")
                return "applied"
            elif selected == 3:
                update_status(reference_url, "excluded")
                return "excluded"
            elif selected == 4:
                update_status(reference_url, "pending")
                return "pending"
            elif selected == 5:
                return None
        elif key in [27, ord("q"), ord("Q")]:
            return None

def main(stdscr):
    curses.curs_set(0)
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
    
    status_filter = "pending"
    selected = 0
    start_idx = 0
    jobs = get_jobs_by_status(status_filter)
    
    last_click_time = 0
    last_click_y = -3
    
    while True:
        height, width = stdscr.getmaxyx()
        jobs = get_jobs_by_status(status_filter if status_filter != "All" else None)
        
        draw_status_menu(stdscr, status_filter)
        start_row, visible_rows, start_idx = draw_job_list(stdscr, jobs, selected, status_filter, start_idx)
        
        stdscr.addstr(height - 2, 0, "[Enter/click] select  [←→] filter  [Esc] quit", curses.A_DIM)
        
        key = stdscr.getch()
        
        if key == curses.KEY_UP:
            selected -= 1
            if selected < 0:
                selected += 1
                start_idx = max(0, start_idx-1)

        elif key == curses.KEY_DOWN:
            selected += 1
            if selected >= visible_rows:
                selected -= 1
                start_idx = min(len(jobs)-visible_rows, start_idx+1)
                
            
        elif key == ord('\n') and jobs:
            #old_selected = selected
            ret = job_detail_menu(stdscr, jobs[start_idx + selected])
            #if ret:
            #    selected = min(len(jobs) - 2, old_selected)

        elif key == curses.KEY_LEFT:
            options = ["All", "pending", "excluded", "applied"]
            idx = options.index(status_filter) if status_filter in options else 0
            status_filter = options[(idx - 1) % len(options)]

            start_idx = 0
            selected = 0
            
        elif key == curses.KEY_RIGHT:
            options = ["All", "pending", "excluded", "applied"]
            idx = options.index(status_filter) if status_filter in options else 0
            status_filter = options[(idx + 1) % len(options)]

            start_idx = 0
            selected = 0

        elif key in [27, ord("q"), ord("Q")]:
            break

if __name__ == "__main__":
    #query_update()
    curses.wrapper(main)
