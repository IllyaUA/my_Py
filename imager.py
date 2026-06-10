import os
from tkinter import Tk, filedialog, Button, Label
from PIL import Image

def convert_webp_to_jpeg(folder_path):
    converted_files = 0
    for file_name in os.listdir(folder_path):
        if file_name.lower().endswith('.webp'):
            webp_path = os.path.join(folder_path, file_name)
            jpeg_path = os.path.splitext(webp_path)[0] + ".jpeg"
            try:
                with Image.open(webp_path) as im:
                    rgb_im = im.convert("RGB")
                    rgb_im.save(jpeg_path, "JPEG")
                converted_files += 1
            except Exception as e:
                print(f"Error converting {file_name}: {e}")
    return converted_files

def browse_folder():
    folder_selected = filedialog.askdirectory()
    if folder_selected:
        label.config(text=f"Processing folder:\n{folder_selected}")
        count = convert_webp_to_jpeg(folder_selected)
        label.config(text=f"Converted {count} WEBP files to JPEG in:\n{folder_selected}")

# GUI setup
root = Tk()
root.title("WEBP to JPEG Converter")
root.geometry("400x200")

label = Label(root, text="Select a folder to convert WEBP to JPEG", wraplength=380, justify="center")
label.pack(pady=20)

browse_btn = Button(root, text="Browse Folder", command=browse_folder)
browse_btn.pack(pady=10)

root.mainloop()
