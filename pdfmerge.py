import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
from PyPDF2 import PdfMerger

class PDFMergerApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Merger")
        self.geometry("600x170")
        self.pdf_files = []  # list to store full PDF paths

        self.create_widgets()
        self.setup_dnd()

    def create_widgets(self):
        # mainframe
        main_frame = tk.Frame(self)
        main_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # listbox to hold PDF files
        self.listbox = tk.Listbox(main_frame, selectmode=tk.SINGLE)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # frame for butts
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        pady = 5
        tk.Button(btn_frame, text="Add files", command=self.add_files).pack(pady=pady)
        tk.Button(btn_frame, text="▲", command=self.move_up).pack(pady=pady)
        tk.Button(btn_frame, text="▼", command=self.move_down).pack(pady=pady)
        tk.Button(btn_frame, text="Remove", command=self.remove_file).pack(pady=pady)
        tk.Button(btn_frame, text="Merge", command=self.merge_files).pack(pady=25)

    def setup_dnd(self):
        # register the listbox as a drop tgt + bind drop event
        self.listbox.drop_target_register(DND_FILES)
        self.listbox.dnd_bind('<<Drop>>', self.on_drop)
        """ 
        these methods are added at *runtime* by tkinterdnd2 through the TkinterDnD.Tk root
        so neglect linter warning, cause it don't see it in Design time
        https://stackoverflow.com/questions/69102055/passing-data-to-tkinter-dnd-dragndrop-vs-event-binding-problem
        """

    def add_files(self):
        files = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        for file in files:
            if file not in self.pdf_files:
                self.pdf_files.append(file)
                self.listbox.insert(tk.END, os.path.basename(file))

    def on_drop(self, event):
        # event.data for file paths space-separated
        files = self.tk.splitlist(event.data)
        for file in files:
            if file.lower().endswith('.pdf') and file not in self.pdf_files:
                self.pdf_files.append(file)
                self.listbox.insert(tk.END, os.path.basename(file))

    def move_up(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        idx = selected[0]
        if idx == 0:
            return
        # swap upwards
        self.pdf_files[idx], self.pdf_files[idx - 1] = self.pdf_files[idx - 1], self.pdf_files[idx]
        self.refresh_listbox()
        self.listbox.selection_set(idx - 1)

    def move_down(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        idx = selected[0]
        if idx == len(self.pdf_files) - 1:
            return
        # swap downwards
        self.pdf_files[idx], self.pdf_files[idx + 1] = self.pdf_files[idx + 1], self.pdf_files[idx]
        self.refresh_listbox()
        self.listbox.selection_set(idx + 1)

    def remove_file(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        idx = selected[0]
        self.pdf_files.pop(idx)
        self.refresh_listbox()

    def refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for file in self.pdf_files:
            self.listbox.insert(tk.END, os.path.basename(file))

    def merge_files(self):
        if len(self.pdf_files) < 2:
            messagebox.showwarning("Not enough files", "At least 2 PDFs to merge are required")
            return

        output_file = os.path.normpath(filedialog.asksaveasfilename(defaultextension=".pdf",
                                                   filetypes=[("PDF files", "*.pdf")]))
        if not output_file:
            return

        merger = PdfMerger()
        try:
            for pdf in self.pdf_files:
                merger.append(pdf)
            merger.write(output_file)
            merger.close()
            messagebox.showinfo("Jobs done", f"PDFs merged into {output_file}")

        except Exception as e:
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    app = PDFMergerApp()
    app.mainloop()
