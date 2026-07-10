import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import docx


def clean_and_convert(input_path, output_path):
    doc = docx.Document()

    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()

    # Split text by double newlines (actual paragraph breaks)
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        # Replace single newlines inside a paragraph with a space
        cleaned_para = re.sub(r'(?<!\n)\n(?!\n)', ' ', para)
        # Clean up any accidental multiple spaces
        cleaned_para = re.sub(r' +', ' ', cleaned_para).strip()

        if cleaned_para:
            doc.add_paragraph(cleaned_para)

    doc.save(output_path)


def browse_file():
    # Hide the main root window during file selection
    root.withdraw()

    # Open file dialog to choose the ASCII text file
    file_path = filedialog.askopenfilename(
        title="Select ASCII Text File",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
    )

    if not file_path:
        # User canceled
        root.destroy()
        return

    # Automatically generate the output path in the same directory
    base_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_docx_path = os.path.join(base_dir, f"{base_name}_fixed.docx")

    try:
        clean_and_convert(file_path, output_docx_path)
        messagebox.showinfo("Success!", f"File converted successfully!\n\nSaved to:\n{output_docx_path}")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred:\n{str(e)}")

    root.destroy()


if __name__ == "__main__":
    # Initialize tkinter
    root = tk.Tk()
    browse_file()