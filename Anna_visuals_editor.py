import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox, filedialog


def load_image(filename: str) -> np.ndarray:
    image_file = Image.open(filename)
    image_file.load()
    Img = np.asarray(image_file, dtype=np.float32)
    Img_max = np.max(Img)
    if Img_max == 0:
        return Img
    Img *= 1 / Img_max
    return Img


######
def display_image(Img: np.ndarray, label_widget: tk.Label) -> None:
    uint8_img = (Img * 255).astype(np.uint8)
    pil_img = Image.fromarray(uint8_img)
    label_widget.update_idletasks()
    avail_width = label_widget.winfo_width()
    avail_height = label_widget.winfo_height()
    max_preview_size = (avail_width, avail_height)

    pil_img.thumbnail(max_preview_size, Image.Resampling.LANCZOS)  # thx geeksforgeeks
    tk_img = ImageTk.PhotoImage(image=pil_img)
    label_widget.config(image=tk_img)
    label_widget.image = tk_img


######


def apply_brightness(img: np.ndarray, value: float) -> np.ndarray:
    if abs(value) > 1: raise ValueError(f'Value {value} is outside of accepted range!')
    new_img = img + value
    new_img = np.clip(new_img, 0, 1)
    return new_img


def apply_contrast(img: np.ndarray, factor: int) -> np.ndarray:
    if factor < 0: raise ValueError(f'Factor {factor} is outside of accepted range!')
    contrast_img = (img - 0.5) * factor + 0.5
    # https://imagemagick.org/script/command-line-options.php#contrast-stretch explains it well in section "-brightness-contrast brightness"

    contrast_img = np.clip(contrast_img, 0, 1)
    return contrast_img


# https://pillow.readthedocs.io/en/stable/reference/ImageEnhance.html
# PIL also has an ImageEnhance module for brightness, saturation, sharpness etc
# update..I think we are good..


def apply_saturation(img: np.ndarray, factor: int) -> np.ndarray:
    if len(img.shape) == 2: return img
    if factor < 0: raise ValueError(f'Value {factor} is outside of accepted range!')
    avg_grey = np.mean(img, axis=2, keepdims=True)
    saturated_image = (img - avg_grey) * factor + avg_grey
    saturated_image = np.clip(saturated_image, 0, 1)
    return saturated_image


# https://numpy.org/devdocs/reference/generated/numpy.mean.html since every pixel is a line in the 3D array
# https://matplotlib.org/stable/tutorials/images.html


def apply_color_reduction(img: np.ndarray, n_values: int) -> np.ndarray:
    to_scale = img * 255
    intv = 255 / n_values
    reduced_img = (to_scale // intv) * intv
    reduced_img *= 1 / 255
    return reduced_img


def apply_invert(img: np.ndarray) -> np.ndarray:
    inverted_img = 1 - img
    inverted_img = np.clip(inverted_img, 0, 1)
    return inverted_img


def build_layout(root):  # my searchbar can't handle more documentation tabs tbh
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    content = tk.Frame(root)

    content.grid(column=0, row=0, sticky="nsew")

    content.columnconfigure(0, weight=1)

    content.rowconfigure(0, weight=1)
    content.rowconfigure(1, weight=0)
    '''had to drop the 60:40 after all, bc it wouldn't fit on smaller displays..
    #In case of resize, change sliders so that the picture updates and snaps back to the measurements of the given space. I didn't want to write a 
    "on window resize" listening event loop..'''

    # content.rowconfigure(0, weight=5, uniform="Bc_apparently_weight_isn't_enough")
    # content.rowconfigure(1, weight=5, uniform="Bc_apparently_weight_isn't_enough")
    # house for image_frame and super_frame..so ig this is mega_frame..ugh why doesn't always fit

    image_frame = tk.Frame(content, borderwidth=10, relief="sunken", bg="black")
    image_frame.grid(column=0, row=0, sticky="nsew", pady=5)

    display_label = tk.Label(image_frame, text="Image will be displayed here")
    display_label.grid(column=0, row=0, sticky="nsew")
    image_frame.columnconfigure(0, weight=1)
    image_frame.rowconfigure(0, weight=1)

    super_frame = tk.Frame(content, borderwidth=10, relief="sunken")  # check sketch
    super_frame.grid(column=0, row=1, sticky="nsew", )

    slider_frame = tk.Frame(super_frame, relief="flat")
    slider_frame.pack(fill="x", padx=20, pady=10)
    slider_frame.columnconfigure(1, weight=1)

    tk.Label(slider_frame, text="Reduction:").grid(row=0, column=0, sticky="se", pady=5)
    scale_reduction = tk.Scale(slider_frame, from_=1, to=256, resolution=1, orient="horizontal")
    scale_reduction.set(256)
    scale_reduction.grid(row=0, column=1, padx=5, sticky="ew")  # east to west..no split here

    tk.Label(slider_frame, text="Saturation:").grid(row=1, column=0, sticky="se", pady=5)
    scale_saturation = tk.Scale(slider_frame, from_=0.0, to=2.0, resolution=0.1,
                                orient="horizontal")  # changed to start in the middle-> can increase saturation and brightness etc
    scale_saturation.set(1.0)
    scale_saturation.grid(row=1, column=1, padx=5, sticky="ew")

    tk.Label(slider_frame, text="Contrast:").grid(row=2, column=0, sticky="se", pady=5)
    scale_contrast = tk.Scale(slider_frame, from_=0.0, to=2.0, resolution=0.1, orient="horizontal")
    scale_contrast.set(1.0)
    scale_contrast.grid(row=2, column=1, padx=5, sticky="ew")

    tk.Label(slider_frame, text="Brightness:").grid(row=3, column=0, sticky="se", pady=5)
    scale_brightness = tk.Scale(slider_frame, from_=-1.0, to=1.0, resolution=0.1, orient="horizontal")
    scale_brightness.set(0.0)
    scale_brightness.grid(row=3, column=1, padx=5, sticky="ew")

    tk.Label(slider_frame, text="Invert").grid(row=4, column=0, sticky="se", pady=5)
    invert_var = tk.BooleanVar(value=False)
    check_box = tk.Checkbutton(slider_frame, variable=invert_var)
    check_box.grid(row=4, column=1, padx=5, sticky="w")

    buttons_frame = tk.Frame(super_frame, relief="raised")
    buttons_frame.pack(fill="x")  # Istg it was capitalised in the documentation..
    # Found ittttttttt: https://www.tutorialspoint.com/python/tk_pack.htm
    # I knew it wasn't lack of sleep..

    buttons_frame.columnconfigure((0, 1, 2), weight=1)
    btn_undo = tk.Button(buttons_frame, text="Undo")
    btn_undo.grid(row=0, column=0, padx=2, sticky="nsew")
    btn_redo = tk.Button(buttons_frame, text="Redo")
    btn_redo.grid(row=0, column=1, padx=2, sticky="nsew")
    btn_save = tk.Button(buttons_frame, text="Save")
    btn_save.grid(row=0, column=2, padx=2, sticky="nsew")

    path_frame = tk.Frame(super_frame, relief="raised")
    path_frame.pack(fill="x")
    path_frame.columnconfigure((0, 1, 2), weight=1)
    path_frame.rowconfigure(0, weight=1)
    btn_load = tk.Button(path_frame, text="Load Image")
    btn_load.grid(column=0, row=0, padx=15, pady=5, sticky="nsew")
    btn_apply = tk.Button(path_frame, text="Apply changes")
    btn_apply.grid(column=2, row=0, padx=15, pady=5, sticky="nsew")

    return {
        "image_label": display_label,
        "slider_reduction": scale_reduction,
        "slider_saturation": scale_saturation,
        "slider_contrast": scale_contrast,
        "slider_brightness": scale_brightness,
        "check_invert": check_box,
        "invert_var": invert_var,
        "btn_undo": btn_undo,
        "btn_redo": btn_redo,
        "btn_save": btn_save,
        "btn_load": btn_load,
        "btn_apply": btn_apply
    }


# Marker

def main():
    root = tk.Tk()
    root.title("A little Photoshop window")  # for a lack of a better name
    root.geometry("800x600")
    ui = build_layout(root)
    img = None
    undo_stack = []  # instead of a last state, which is the last applied state, any state can be reversed, but not redid (eg after apply)
    redo_stack = []  # I personally liked the committing version more, but the testers, said they prefered this
    current = None
    preview = None
    reset = False

    ####

    def undo():
        nonlocal current, preview
        if not undo_stack:
            return
        redo_stack.append(current.copy())

        current = undo_stack.pop()
        reset_sliders()
        display_image(current, ui["image_label"])
        preview = current.copy()

        # nonlocal current, last, preview
        # cache = current
        # current = last
        # last = cache #this gives me pointer flashbacks
        # reset_sliders()
        # preview= current
        # display_image(current, ui["image_label"])

    def redo():
        nonlocal current, preview
        if not redo_stack:
            return
        undo_stack.append(current.copy())
        current = redo_stack.pop()
        display_image(current, ui["image_label"])
        preview = current.copy()

    def reset_sliders():  # It would be prettier to be able to not completely reset sliders, but save all states maybe
        nonlocal reset  # Tho resetting completely would mean less spamming the reset button..andddd less variables
        reset = True
        current_values['brightness'] = 0.0
        current_values['contrast'] = 1.0
        current_values['saturation'] = 1.0
        current_values['reduction'] = 256
        current_values['invert_var'] = False

        ui['slider_brightness'].set(0.0)
        ui['slider_contrast'].set(1.0)
        ui['slider_saturation'].set(1.0)
        ui['slider_reduction'].set(256)
        ui['invert_var'].set(False)
        reset = False

    def update_preview():  # only do after apply
        nonlocal current, preview
        if (current is None or reset):
            return
        img = current.copy()
        if current_values['brightness'] != 0.0:
            img = apply_brightness(img, current_values['brightness'])
        if current_values['contrast'] != 1.0:
            img = apply_contrast(img, current_values['contrast'])
        if current_values['saturation'] != 1.0:
            img = apply_saturation(img, current_values['saturation'])
        if current_values['reduction'] < 256:
            img = apply_color_reduction(img, current_values['reduction'])
        if current_values['invert_var']:
            img = apply_invert(img)

        preview = img
        display_image(img, ui["image_label"])

    def apply():  # bc of the update to undo/redo this now can be reversed..but also takes the locked in pic as new reference
        nonlocal current, preview
        if (preview is not None):
            undo_stack.append(current.copy())
            redo_stack.clear()

            current = preview.copy()
            reset_sliders()
            display_image(current, ui["image_label"])

    current_values = {
        'brightness': 0.0,
        'contrast': 1.0,
        'saturation': 1.0,
        'reduction': 256,
        'invert_var': False
        # reset after apply
    }

    # The update funcs for slidersssssssssss
    def update_brightness(val):
        current_values['brightness'] = float(val)
        update_preview()

    def update_contrast(val):
        current_values['contrast'] = float(val)
        update_preview()

    def update_saturation(val):
        current_values['saturation'] = float(val)
        update_preview()

    def update_reduction(val):
        current_values['reduction'] = int(val)
        update_preview()

    def toggle_invert():
        current_values['invert_var'] = ui['invert_var'].get()
        update_preview()

    # https://docs.python.org/3/library/dialog.html
    def browse_img():
        nonlocal img, current, preview
        filepath = filedialog.askopenfilename(title="Select an Image",
                                              filetypes=(("Image files", "*.jpg *.jpeg *.png *.bmp"),
                                                         ("All files", "*.*")))
        try:
            if filepath:
                try:
                    img = load_image(filepath)
                    current = img.copy();
                    preview = img.copy()
                    undo_stack.clear()
                    redo_stack.clear()
                    reset_sliders()
                    display_image(current, ui["image_label"])
                except ImportError:
                    messagebox.showerror("ImportError:" "An Error occurred trying to load the file")
        except FileNotFoundError:
            messagebox.showerror(
                "FileNotFoundError:" "File or Directory doesn't exist, can't be accessed or was interrupted")
            #####

    def save():
        '''
        I know I can just call the tk.filedialog.asksaveasfilename(**options)..
        well I didn't when I wrote the function, bc I only wrote the browse_img() later..It was very..manual before
        But this works and the little pop ups I wrote are cute..
        it saves to current directory tho, maybe choosing path would be better..

        Update: I seem to be the only one prefering this, so..fusion it is
        '''
        nonlocal current
        if current is None:
            messagebox.showwarning("Warning", "No image is currently loaded!")
            return
        ask = tk.messagebox.askquestion(title="Proceeding..", message="Do you want to save it to current directory")
        if (ask == "yes"):
            filename = tk.simpledialog.askstring("Filepath",
                                                 "Name your file, please use file-extension .png, .jpg or .jpeg!")
            if filename:
                try:
                    img_uint8 = (current * 255).astype(np.uint8)
                    img = Image.fromarray(img_uint8)
                except TypeError:
                    messagebox.showerror("TypeError:", "The format doesn't match the requirement.")
                    return
                try:
                    if (".png" not in filename and ".jpg" not in filename and ".jpeg" not in filename):
                        messagebox.showerror("Typeerror:", "Not supported extension used")
                        return
                    else:
                        img.save(filename)
                        tk.messagebox.showinfo(title="Save Details", message="Image saved successfully")
                except Exception as e:
                    messagebox.showerror("Error", f"An unexpected error occurred while saving {e}")
        elif (ask == "no"):
            file_name = filedialog.asksaveasfilename(
                title="Save as..",
                defaultextension=".png",
                filetypes=(
                    ("PNG Image", "*.png"),
                    ("JPEG Image", "*.jpg"),
                    ("Bitmap Image", "*.bmp"),
                    ("All files", "*.*")),
                confirmoverwrite=False)

            if (file_name):
                try:
                    img_uint8 = (current * 255).astype(np.uint8)
                    img = Image.fromarray(img_uint8)
                    img.save(file_name)
                    tk.messagebox.showinfo(title="Save Details", message="Image saved successfully")
                except Exception as e:
                    messagebox.showerror("Error", f"An unexpected error occurred while saving {e}")
            # hehe I like errorhandling  afterall

    #######Thaaaaaaaaa slidersssssssssssssssss
    ui['slider_brightness'].config(command=update_brightness)
    ui['slider_contrast'].config(command=update_contrast)
    ui['slider_saturation'].config(command=update_saturation)
    ui['slider_reduction'].config(command=update_reduction)

    ui['check_invert'].config(command=toggle_invert)  # use var

    ui['btn_load'].config(command=browse_img)
    ui['btn_redo'].config(command=redo)
    ui['btn_undo'].config(command=undo)
    ui['btn_save'].config(command=save)
    ui['btn_apply'].config(command=apply)

    tk.mainloop()


if __name__ == "__main__":
    main()