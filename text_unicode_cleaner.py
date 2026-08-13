#!/usr/bin/env python3
"""
Text / XML / DOCX Inspector & Cleaner

Features
--------
- TXT / XML / DOCX
- Detects invisible/suspicious Unicode whitespace and control characters
- Reports line/position/code point/name/context
- Encoding detection for UTF-8, Latin-1 and CP1251
- Converts TXT/XML between UTF-8, Latin-1 and CP1251
- Conservative whitespace cleanup
- DOCX:
    * scans WordprocessingML text
    * removes selected invisible characters
    * removes text/background shading (<w:shd>)
    * preserves highlighting (<w:highlight>)
    * scans all relevant XML parts inside the DOCX
- Single file or folder/batch mode
- Produces a CSV report

Dependencies:
    pip install charset-normalizer

Python 3.9+ recommended.
"""

import csv
import io
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from charset_normalizer import from_bytes as cn_from_bytes
except ImportError:
    cn_from_bytes = None

from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# Character definitions
# ---------------------------------------------------------------------------

CHAR_INFO = {
    0x00A0: ("NO-BREAK SPACE", "space", True),
    0x1680: ("OGHAM SPACE MARK", "space", True),
    0x180E: ("MONGOLIAN VOWEL SEPARATOR", "format", True),
    0x2000: ("EN QUAD", "space", True),
    0x2001: ("EM QUAD", "space", True),
    0x2002: ("EN SPACE", "space", True),
    0x2003: ("EM SPACE", "space", True),
    0x2004: ("THREE-PER-EM SPACE", "space", True),
    0x2005: ("FOUR-PER-EM SPACE", "space", True),
    0x2006: ("SIX-PER-EM SPACE", "space", True),
    0x2007: ("FIGURE SPACE", "space", True),
    0x2008: ("PUNCTUATION SPACE", "space", True),
    0x2009: ("THIN SPACE", "space", True),
    0x200A: ("HAIR SPACE", "space", True),
    0x200B: ("ZERO WIDTH SPACE", "zero-width", True),
    0x200C: ("ZERO WIDTH NON-JOINER", "format", False),
    0x200D: ("ZERO WIDTH JOINER", "format", False),
    0x200E: ("LEFT-TO-RIGHT MARK", "directional", False),
    0x200F: ("RIGHT-TO-LEFT MARK", "directional", False),
    0x2028: ("LINE SEPARATOR", "line", False),
    0x2029: ("PARAGRAPH SEPARATOR", "line", False),
    0x202A: ("LEFT-TO-RIGHT EMBEDDING", "directional", False),
    0x202B: ("RIGHT-TO-LEFT EMBEDDING", "directional", False),
    0x202C: ("POP DIRECTIONAL FORMATTING", "directional", False),
    0x202D: ("LEFT-TO-RIGHT OVERRIDE", "directional", False),
    0x202E: ("RIGHT-TO-LEFT OVERRIDE", "directional", False),
    0x202F: ("NARROW NO-BREAK SPACE", "space", True),
    0x205F: ("MEDIUM MATHEMATICAL SPACE", "space", True),
    0x2060: ("WORD JOINER", "zero-width", True),
    0x2061: ("FUNCTION APPLICATION", "format", False),
    0x2062: ("INVISIBLE TIMES", "format", False),
    0x2063: ("INVISIBLE SEPARATOR", "format", False),
    0x2064: ("INVISIBLE PLUS", "format", False),
    0x2066: ("LEFT-TO-RIGHT ISOLATE", "directional", False),
    0x2067: ("RIGHT-TO-LEFT ISOLATE", "directional", False),
    0x2068: ("FIRST STRONG ISOLATE", "directional", False),
    0x2069: ("POP DIRECTIONAL ISOLATE", "directional", False),
    0x206A: ("INHIBIT SYMMETRIC SWAPPING", "format", False),
    0x206B: ("ACTIVATE SYMMETRIC SWAPPING", "format", False),
    0x206C: ("INHIBIT ARABIC FORM SHAPING", "format", False),
    0x206D: ("ACTIVATE ARABIC FORM SHAPING", "format", False),
    0x206E: ("NATIONAL DIGIT SHAPES", "format", False),
    0x206F: ("NOMINAL DIGIT SHAPES", "format", False),
    0x3000: ("IDEOGRAPHIC SPACE", "space", True),
    0xFEFF: ("ZERO WIDTH NO-BREAK SPACE / BOM", "zero-width", True),
}

# C0 controls except tab/LF/CR are suspicious.
CONTROL_NAMES = {
    0x00: "NULL",
    0x01: "START OF HEADING",
    0x02: "START OF TEXT",
    0x03: "END OF TEXT",
    0x04: "END OF TRANSMISSION",
    0x05: "ENQUIRY",
    0x06: "ACKNOWLEDGE",
    0x07: "BELL",
    0x08: "BACKSPACE",
    0x0B: "VERTICAL TAB",
    0x0C: "FORM FEED",
    0x0E: "SHIFT OUT",
    0x0F: "SHIFT IN",
    0x10: "DATA LINK ESCAPE",
    0x11: "DEVICE CONTROL 1",
    0x12: "DEVICE CONTROL 2",
    0x13: "DEVICE CONTROL 3",
    0x14: "DEVICE CONTROL 4",
    0x15: "NEGATIVE ACKNOWLEDGE",
    0x16: "SYNCHRONOUS IDLE",
    0x17: "END OF TRANSMISSION BLOCK",
    0x18: "CANCEL",
    0x19: "END OF MEDIUM",
    0x1A: "SUBSTITUTE",
    0x1B: "ESCAPE",
    0x1C: "FILE SEPARATOR",
    0x1D: "GROUP SEPARATOR",
    0x1E: "RECORD SEPARATOR",
    0x1F: "UNIT SEPARATOR",
    0x7F: "DELETE",
}

ENCODINGS = {
    "UTF-8": "utf-8",
    "Latin-1 (ISO-8859-1)": "latin-1",
    "CP1251 (Windows Cyrillic)": "cp1251",
}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"


@dataclass
class Finding:
    file: str
    part: str
    line: int
    column: int
    code: str
    name: str
    category: str
    character: str
    context: str


def char_description(ch: str, report_controls=True):
    cp = ord(ch)

    if cp in CHAR_INFO:
        name, category, auto_remove = CHAR_INFO[cp]
        return name, category, auto_remove

    if cp in CONTROL_NAMES:
        return CONTROL_NAMES[cp], "control", True

    # Unicode category Cc / Cf
    import unicodedata
    cat = unicodedata.category(ch)
    if report_controls and cat in ("Cc", "Cf"):
        name = unicodedata.name(ch, f"CONTROL/FORMAT U+{cp:04X}")
        return name, "control/format", False

    return None


def visible_repr(ch: str):
    cp = ord(ch)
    mapping = {
        0x09: r"\t",
        0x0A: r"\n",
        0x0D: r"\r",
        0x00A0: "<NBSP>",
        0x200B: "<ZWSP>",
        0x200C: "<ZWNJ>",
        0x200D: "<ZWJ>",
        0x2060: "<WORD-JOINER>",
        0xFEFF: "<FEFF>",
    }
    return mapping.get(cp, f"<U+{cp:04X}>")


def make_context(text, index, radius=35):
    start = max(0, index - radius)
    end = min(len(text), index + radius + 1)
    result = []
    for ch in text[start:end]:
        if ch == "\n":
            result.append("\\n")
        elif ch == "\r":
            result.append("\\r")
        elif ch == "\t":
            result.append("\\t")
        elif char_description(ch):
            result.append(visible_repr(ch))
        else:
            result.append(ch)
    return "".join(result)


def scan_text(text, file_name, part="", base_line=1):
    findings = []
    line = base_line
    col = 1

    for i, ch in enumerate(text):
        info = char_description(ch)
        if info:
            name, category, _ = info
            findings.append(
                Finding(
                    file=file_name,
                    part=part,
                    line=line,
                    column=col,
                    code=f"U+{ord(ch):04X}",
                    name=name,
                    category=category,
                    character=visible_repr(ch),
                    context=make_context(text, i),
                )
            )

        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1

    return findings


def clean_text(text, remove_spaces=True, remove_zero_width=True,
               remove_controls=True, normalize_nbsp=True):
    out = []
    changed = 0

    for ch in text:
        info = char_description(ch)

        if not info:
            out.append(ch)
            continue

        name, category, auto_remove = info
        cp = ord(ch)

        # Keep normal line/tab whitespace.
        if cp in (0x09, 0x0A, 0x0D):
            out.append(ch)
            continue

        if category == "space":
            if normalize_nbsp:
                out.append(" ")
                changed += 1
            elif not remove_spaces:
                out.append(ch)
            else:
                # If removal was explicitly requested, remove; otherwise keep.
                if remove_spaces:
                    changed += 1
                else:
                    out.append(ch)
            continue

        if category in ("zero-width",):
            if remove_zero_width:
                changed += 1
            else:
                out.append(ch)
            continue

        if category in ("control", "control/format"):
            if remove_controls and auto_remove:
                changed += 1
            else:
                out.append(ch)
            continue

        # Directional and joiner marks are kept by default.
        out.append(ch)

    return "".join(out), changed


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def utf8_bom(data):
    return data.startswith(b"\xef\xbb\xbf")


def decode_bytes(data, requested="Auto"):
    candidates = []

    if requested != "Auto":
        enc = ENCODINGS[requested]
        try:
            return data.decode(enc), enc, "manual"
        except UnicodeDecodeError as e:
            raise ValueError(
                f"Cannot decode file as {requested}: {e}"
            ) from e

    if utf8_bom(data):
        try:
            return data.decode("utf-8-sig"), "utf-8-sig", "BOM"
        except UnicodeDecodeError:
            pass

    # Strict UTF-8 first.
    try:
        return data.decode("utf-8"), "utf-8", "strict UTF-8"
    except UnicodeDecodeError:
        pass

    # charset-normalizer is better than guessing blindly.
    if cn_from_bytes:
        try:
            matches = cn_from_bytes(data)
            best = matches.best()
            if best:
                enc = best.encoding
                if enc:
                    try:
                        return data.decode(enc), enc, "charset-normalizer"
                    except Exception:
                        pass
        except Exception:
            pass

    # Latin-1 always decodes, so it must be last.
    try:
        return data.decode("cp1251"), "cp1251", "fallback CP1251"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1", "fallback Latin-1"


def encode_text(text, target_label):
    enc = ENCODINGS[target_label]
    try:
        return text.encode(enc)
    except UnicodeEncodeError as e:
        chars = sorted({f"U+{ord(ch):04X}" for ch in e.object[e.start:e.end]})
        raise ValueError(
            f"Target encoding {target_label} cannot represent: "
            + ", ".join(chars)
        ) from e


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def is_word_xml_part(name):
    low = name.lower()
    return (
        low.startswith("word/")
        and low.endswith(".xml")
        and not low.endswith("websettings.xml")
        and not low.endswith("settings.xml")
        and not low.endswith("fonttable.xml")
        and not low.endswith("styles.xml")
    )


def scan_docx_bytes(data, file_name, remove_shading=False,
                    clean=False, options=None):
    findings = []
    shading_count = 0
    changed_chars = 0
    output_parts = {}

    with zipfile.ZipFile(io.BytesIO(data), "r") as zin:
        names = zin.namelist()

        for name in names:
            raw = zin.read(name)

            if not is_word_xml_part(name):
                output_parts[name] = raw
                continue

            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                output_parts[name] = raw
                continue

            # Scan / clean all w:t text nodes.
            for elem in root.iter(f"{W}t"):
                if elem.text:
                    findings.extend(
                        scan_text(
                            elem.text,
                            file_name,
                            part=name,
                        )
                    )
                    if clean:
                        new_text, changed = clean_text(
                            elem.text,
                            remove_spaces=options["remove_spaces"],
                            remove_zero_width=options["remove_zero_width"],
                            remove_controls=options["remove_controls"],
                            normalize_nbsp=options["normalize_nbsp"],
                        )
                        elem.text = new_text
                        changed_chars += changed

                # Tail text is uncommon in Word XML, but inspect it too.
                if elem.tail:
                    findings.extend(
                        scan_text(elem.tail, file_name, part=name)
                    )
                    if clean:
                        new_tail, changed = clean_text(
                            elem.tail,
                            remove_spaces=options["remove_spaces"],
                            remove_zero_width=options["remove_zero_width"],
                            remove_controls=options["remove_controls"],
                            normalize_nbsp=options["normalize_nbsp"],
                        )
                        elem.tail = new_tail
                        changed_chars += changed

            # Text/background shading: w:shd.
            shds = list(root.iter(f"{W}shd"))
            shading_count += len(shds)

            if clean and remove_shading:
                parent_map = {child: parent for parent in root.iter()
                              for child in parent}
                for shd in shds:
                    parent = parent_map.get(shd)
                    if parent is not None:
                        parent.remove(shd)

            if clean:
                out = ET.tostring(
                    root,
                    encoding="utf-8",
                    xml_declaration=True,
                )
                output_parts[name] = out
            else:
                output_parts[name] = raw

        # Rebuild only if requested.
        if clean:
            outbuf = io.BytesIO()
            with zipfile.ZipFile(
                outbuf, "w", compression=zipfile.ZIP_DEFLATED
            ) as zout:
                for name in names:
                    zout.writestr(name, output_parts[name])
            return (
                outbuf.getvalue(),
                findings,
                shading_count,
                changed_chars,
            )

        return data, findings, shading_count, changed_chars


# ---------------------------------------------------------------------------
# Plain text / XML
# ---------------------------------------------------------------------------

def process_text_file(path, encoding_choice, clean, options):
    raw = path.read_bytes()
    text, detected, method = decode_bytes(raw, encoding_choice)

    findings = scan_text(text, path.name)

    if clean:
        new_text, changed = clean_text(
            text,
            remove_spaces=options["remove_spaces"],
            remove_zero_width=options["remove_zero_width"],
            remove_controls=options["remove_controls"],
            normalize_nbsp=options["normalize_nbsp"],
        )
        return raw, new_text, detected, method, findings, changed

    return raw, text, detected, method, findings, 0


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Text / XML / DOCX Inspector & Cleaner")
        self.geometry("1250x760")
        self.minsize(950, 600)

        self.path_var = tk.StringVar()
        self.target_encoding = tk.StringVar(value="UTF-8")
        self.source_encoding = tk.StringVar(value="Auto")
        self.status_var = tk.StringVar(value="Ready.")

        self.remove_spaces = tk.BooleanVar(value=False)
        self.remove_zero_width = tk.BooleanVar(value=True)
        self.remove_controls = tk.BooleanVar(value=True)
        self.normalize_nbsp = tk.BooleanVar(value=True)
        self.remove_shading = tk.BooleanVar(value=True)

        self.last_findings = []
        self.last_summary = {}

        self.build_ui()

    def build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="File / folder:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(
            top, textvariable=self.path_var, width=90
        ).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(
            top, text="File...", command=self.choose_file
        ).grid(row=0, column=2, padx=3)
        ttk.Button(
            top, text="Folder...", command=self.choose_folder
        ).grid(row=0, column=3, padx=3)

        top.columnconfigure(1, weight=1)

        enc = ttk.LabelFrame(self, text="Encoding", padding=8)
        enc.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(enc, text="Source:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            enc,
            textvariable=self.source_encoding,
            values=["Auto"] + list(ENCODINGS.keys()),
            state="readonly",
            width=28,
        ).grid(row=0, column=1, padx=6)

        ttk.Label(enc, text="Target:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            enc,
            textvariable=self.target_encoding,
            values=list(ENCODINGS.keys()),
            state="readonly",
            width=28,
        ).grid(row=0, column=3, padx=6)

        opts = ttk.LabelFrame(self, text="Cleaning options", padding=8)
        opts.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Checkbutton(
            opts, text="Remove / normalize Unicode spaces",
            variable=self.remove_spaces
        ).grid(row=0, column=0, sticky="w", padx=4)

        ttk.Checkbutton(
            opts, text="Remove zero-width characters",
            variable=self.remove_zero_width
        ).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Checkbutton(
            opts, text="Remove suspicious controls",
            variable=self.remove_controls
        ).grid(row=0, column=2, sticky="w", padx=4)

        ttk.Checkbutton(
            opts, text="NBSP / Unicode spaces → normal space",
            variable=self.normalize_nbsp
        ).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Checkbutton(
            opts, text="DOCX: remove text/background shading",
            variable=self.remove_shading
        ).grid(row=1, column=0, sticky="w", padx=4, pady=(5, 0))

        ttk.Label(
            opts,
            text="Highlight is NOT removed.",
        ).grid(row=1, column=1, columnspan=2, sticky="w", padx=4)

        buttons = ttk.Frame(self, padding=(10, 0, 10, 8))
        buttons.pack(fill="x")

        ttk.Button(
            buttons, text="SCAN", command=self.scan
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            buttons, text="CLEAN & SAVE AS...", command=self.clean_save
        ).pack(side="left", padx=5)

        ttk.Button(
            buttons, text="SAVE REPORT CSV...", command=self.save_report
        ).pack(side="left", padx=5)

        ttk.Button(
            buttons, text="Clear", command=self.clear
        ).pack(side="right")

        frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        frame.pack(fill="both", expand=True)

        columns = (
            "file", "part", "line", "column", "code",
            "name", "category", "char", "context"
        )

        self.tree = ttk.Treeview(frame, columns=columns, show="headings")

        headings = {
            "file": "File",
            "part": "DOCX/XML part",
            "line": "Line",
            "column": "Column",
            "code": "Code",
            "name": "Unicode name",
            "category": "Category",
            "char": "Character",
            "context": "Context",
        }

        widths = {
            "file": 130,
            "part": 190,
            "line": 60,
            "column": 65,
            "code": 75,
            "name": 260,
            "category": 100,
            "char": 100,
            "context": 420,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")

        vsb = ttk.Scrollbar(
            frame, orient="vertical", command=self.tree.yview
        )
        hsb = ttk.Scrollbar(
            frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        status = ttk.Label(
            self,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=4,
        )
        status.pack(fill="x", side="bottom")

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Select file",
            filetypes=[
                ("Supported", "*.txt *.xml *.docx"),
                ("Text", "*.txt"),
                ("XML", "*.xml"),
                ("Word", "*.docx"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.path_var.set(path)

    def choose_folder(self):
        path = filedialog.askdirectory(title="Select folder")
        if path:
            self.path_var.set(path)

    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.last_findings = []
        self.last_summary = {}
        self.status_var.set("Ready.")

    def options(self):
        return {
            "remove_spaces": self.remove_spaces.get(),
            "remove_zero_width": self.remove_zero_width.get(),
            "remove_controls": self.remove_controls.get(),
            "normalize_nbsp": self.normalize_nbsp.get(),
        }

    def iter_files(self):
        p = Path(self.path_var.get().strip().strip('"'))

        if not p.exists():
            raise FileNotFoundError(str(p))

        if p.is_file():
            if p.suffix.lower() not in (".txt", ".xml", ".docx"):
                raise ValueError("Supported files are .txt, .xml and .docx")
            return [p]

        files = []
        for ext in ("*.txt", "*.xml", "*.docx"):
            files.extend(p.rglob(ext))
        return sorted(files)

    def display_findings(self, findings):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for f in findings:
            self.tree.insert(
                "",
                "end",
                values=(
                    f.file,
                    f.part,
                    f.line,
                    f.column,
                    f.code,
                    f.name,
                    f.category,
                    f.character,
                    f.context,
                ),
            )

    def scan(self):
        try:
            files = self.iter_files()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        all_findings = []
        summaries = []

        for path in files:
            try:
                if path.suffix.lower() == ".docx":
                    raw = path.read_bytes()
                    _, findings, shading, changed = scan_docx_bytes(
                        raw,
                        path.name,
                        remove_shading=False,
                        clean=False,
                        options=self.options(),
                    )
                    all_findings.extend(findings)
                    summaries.append(
                        f"{path.name}: {len(findings)} suspicious characters; "
                        f"{shading} shaded text elements"
                    )
                else:
                    _, _, detected, method, findings, _ = process_text_file(
                        path,
                        self.source_encoding.get(),
                        False,
                        self.options(),
                    )
                    all_findings.extend(findings)
                    summaries.append(
                        f"{path.name}: {len(findings)} suspicious characters; "
                        f"encoding={detected} ({method})"
                    )
            except Exception as e:
                summaries.append(f"{path.name}: ERROR: {e}")

        self.last_findings = all_findings
        self.last_summary = {"files": files, "details": summaries}

        self.display_findings(all_findings)

        messagebox.showinfo(
            "Scan complete",
            f"Files scanned: {len(files)}\n"
            f"Suspicious characters: {len(all_findings)}\n\n"
            + "\n".join(summaries[:15])
            + ("\n..." if len(summaries) > 15 else "")
        )

        self.status_var.set(
            f"Scanned {len(files)} file(s): "
            f"{len(all_findings)} suspicious character(s)."
        )

    def clean_save(self):
        try:
            files = self.iter_files()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        if len(files) == 1:
            dest = filedialog.asksaveasfilename(
                title="Save cleaned file",
                initialfile=files[0].stem + "_cleaned" + files[0].suffix,
                defaultextension=files[0].suffix,
                filetypes=[
                    ("Supported", "*.txt *.xml *.docx"),
                    ("All files", "*.*"),
                ],
            )
            if not dest:
                return

            destinations = [(files[0], Path(dest))]
        else:
            dest_dir = filedialog.askdirectory(
                title="Select destination folder"
            )
            if not dest_dir:
                return

            dest_dir = Path(dest_dir)
            destinations = [
                (p, dest_dir / (p.stem + "_cleaned" + p.suffix))
                for p in files
            ]

        options = self.options()
        total_findings = 0
        total_changes = 0
        total_shading = 0
        errors = []

        for src, dest in destinations:
            try:
                raw = src.read_bytes()

                if src.suffix.lower() == ".docx":
                    cleaned, findings, shading, changes = scan_docx_bytes(
                        raw,
                        src.name,
                        remove_shading=self.remove_shading.get(),
                        clean=True,
                        options=options,
                    )

                    # Validate the generated DOCX before writing.
                    with zipfile.ZipFile(io.BytesIO(cleaned), "r") as z:
                        bad = z.testzip()
                        if bad:
                            raise ValueError(
                                f"Generated DOCX contains corrupt ZIP member: {bad}"
                            )

                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(cleaned)

                    total_findings += len(findings)
                    total_changes += changes
                    total_shading += shading

                else:
                    raw, text, detected, method, findings, changes = (
                        process_text_file(
                            src,
                            self.source_encoding.get(),
                            True,
                            options,
                        )
                    )

                    # Target encoding is always applied for text/XML.
                    encoded = encode_text(
                        text,
                        self.target_encoding.get(),
                    )

                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(encoded)

                    total_findings += len(findings)
                    total_changes += changes

            except Exception as e:
                errors.append(f"{src}: {e}")

        msg = (
            f"Cleaned files: {len(destinations) - len(errors)}\n"
            f"Suspicious characters found: {total_findings}\n"
            f"Characters changed/removed: {total_changes}\n"
            f"DOCX shading elements found: {total_shading}\n"
            f"Highlighting was preserved."
        )

        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:10])

        messagebox.showinfo("Cleaning complete", msg)

        self.status_var.set(
            f"Finished: {len(destinations) - len(errors)} file(s) saved."
        )

    def save_report(self):
        if not self.last_findings:
            messagebox.showinfo(
                "No report",
                "Run Scan first. There are no findings to export."
            )
            return

        dest = filedialog.asksaveasfilename(
            title="Save CSV report",
            defaultextension=".csv",
            initialfile="unicode_whitespace_report.csv",
            filetypes=[("CSV", "*.csv")],
        )

        if not dest:
            return

        try:
            with open(dest, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "File",
                    "DOCX/XML part",
                    "Line",
                    "Column",
                    "Code",
                    "Unicode name",
                    "Category",
                    "Character",
                    "Context",
                ])

                for x in self.last_findings:
                    writer.writerow([
                        x.file,
                        x.part,
                        x.line,
                        x.column,
                        x.code,
                        x.name,
                        x.category,
                        x.character,
                        x.context,
                    ])

            messagebox.showinfo(
                "Report saved",
                f"CSV report saved to:\n{dest}"
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
