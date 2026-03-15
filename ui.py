import curses
import subprocess

from jobs_db import get_jobs_by_status, update_status 
from cover_letters import main as cover_letter_loop

class app:
    def __init__(self):
        self.status_filter = 0
        self.status_text = [
            "pending",
            "excluded",
            "applied",
            "ALL"
        ] 

        self.selected = 0
        self.start_idx = 0

        self.jobs = get_jobs_by_status(self.status_text[self.status_filter])

    def run(self):
        curses.wrapper(self.main_loop)
    
    def main_loop(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
        
        while True:
            self.draw_main_menu()
            key = self.stdscr.getch()

            if   key in [curses.KEY_DOWN, ord("k")]: self.select(1)
            elif key in [curses.KEY_UP, ord("j")]: self.select(-1)
            elif key in [curses.KEY_RIGHT, ord("l")]: self.cycle_filter(1)
            elif key in [curses.KEY_LEFT, ord("h")]: self.cycle_filter(-1)
            elif key in [curses.KEY_NPAGE]: self.select(self.ln_visable)
            elif key in [curses.KEY_PPAGE]: self.select(-self.ln_visable)
            elif key in [ord('\n')]: self.job_details_menu()
            elif key in [27, ord("q"), ord("Q")]: break

    def select(self, delta):
        actual = self.start_idx + self.selected
        new_actual = max(0, min(actual + delta, len(self.jobs) - 1))

        if new_actual - self.start_idx >= self.ln_visable:
            self.start_idx = new_actual - self.ln_visable + 1
            self.selected = self.ln_visable - 1
        elif new_actual - self.start_idx < 0:
            self.start_idx = max(0, new_actual)
            self.selected = 0
        else:
            self.selected = new_actual - self.start_idx
    
    @property
    def status(self):
        return self.status_text[self.status_filter]

    def cycle_filter(self, delta):
        self.status_filter += delta
        self.status_filter %= len(self.status_text)
    
        self.selected = 0
        self.start_idx = 0
        
        self.jobs = get_jobs_by_status(self.status_text[self.status_filter])

    def draw_main_menu(self):
        self.my, self.mx = self.stdscr.getmaxyx()
        self.ln_visable = self.my - 4

        clean = " "*self.mx
        jobs = self.jobs[self.start_idx:] # do this for easy indexing on self.selected
        start_row = 2

        # write header
        self.stdscr.addstr(0, 0, clean)
        self.stdscr.addstr(1, 0, clean)
        self.stdscr.addstr(0, 0, f"Jobs - {self.status} ({len(self.jobs)} jobs)"[:self.mx-1], curses.A_REVERSE)
        
        # write footer
        self.stdscr.addstr(self.my - 2, 0, clean)
        self.stdscr.addstr(self.my - 1, 0, clean[:-1]) # breaks things for no reason
        self.stdscr.addstr(self.my - 1, 0, "[Enter] select [←→] filter [↑↓] scroll [Esc/q] quit"[:self.mx], curses.A_DIM)
        
        if not self.jobs:
            stdscr.addstr(start_row, 0, "No jobs found")
            return  
        
        # loop through each line and display job or just clean
        for job_idx in range(self.ln_visable):
            job = jobs[job_idx] if job_idx < len(jobs) else None
            y = job_idx + start_row
           
            if job:
                prefix = ">" if job_idx == self.selected else " "
                status_color = curses.A_REVERSE if job_idx == self.selected else curses.color_pair(1) if job['status'] == "pending" else curses.color_pair(2) if job['status'] == "applied" else curses.color_pair(3) if job["status"] == "excluded" else curses.A_REVERSE

                self.stdscr.addstr(y, 0, clean, status_color)
                self.stdscr.addstr(y, 0, f"{prefix} {job['title'][:(self.mx//3)*2-2]}", status_color)
                self.stdscr.addstr(y, (self.mx//3)*2, f"| {job['company'][:self.mx//3-2]}", status_color)

            else:
                self.stdscr.addstr(y, 0, clean)

    def open_current_in_browser(self):
        subprocess.Popen(["firefox", "--new-window", self.jobs[self.start_idx + self.selected]["url"]])

    def update_current_status(self, new_status):
        if new_status != self.status:
            job = self.jobs.pop(self.start_idx + self.selected)
            update_status(job['url'], new_status)

    def job_details_menu(self):
        job = self.jobs[self.start_idx + self.selected]
        
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
            # display options
            self.stdscr.clear()
            
            self.stdscr.addstr(0, 0, f"{job['title']} at {job['company']}", curses.A_REVERSE)
            self.stdscr.addstr(1, 0, f"Status: {job['status']}", curses.color_pair(1) if job['status'] == "pending" else curses.color_pair(2) if job['status'] == "applied" else curses.color_pair(3) if job['status'] == "excluded" else curses.color_pair(3))
            
            for i, opt in enumerate(options):
                prefix = ">" if i == selected else " "
                self.stdscr.addstr(i + 3, 0, f"{prefix} {opt}")
            
            key = self.stdscr.getch()
            
            if   key in [curses.KEY_UP, ord("k")]: selected = (selected - 1) % len(options)
            elif key in [curses.KEY_DOWN, ord("j")]: selected = (selected + 1) % len(options)
            elif key in [ord('\n'), curses.KEY_ENTER, 10, 13]:
                if   selected == 0: self.open_current_in_browser()
                elif selected == 1: cover_letter_loop(self.stdscr, job['url'])
                elif selected == 2:
                    self.update_current_status("applied")
                    return
                elif selected == 3:
                    self.update_current_status("excluded") 
                    return
                elif selected == 4:
                    self.update_current_status("pending")
                    return
                elif selected == 5: return None
            elif key in [27, ord("q"), ord("Q")]: return None


if __name__ == "__main__":
    obj = app()
    curses.wrapper(obj.main_loop)
