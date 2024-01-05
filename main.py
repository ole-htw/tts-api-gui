import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from openai import OpenAI
import json
from datetime import datetime
import subprocess
import threading
import sys
import os
from pydub import AudioSegment
CONFIG_FILE = 'config.json'


class CustomText(tk.Text):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, undo=True, **kwargs)
        self.app = None
        self.bind("<<Modified>>", self._on_change)
        self.bind("<Control-z>", self.undo_action)

    def undo_action(self, event=None):
        try:
            self.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def set_app(self, app):
        self.app = app

    def _on_change(self, event=None):
        if self.edit_modified():
            if self.app:
                self.app.check_buttons_state()
                self.app.reset_convert_button_style()
                self.app.update_status_bar()
            self.edit_modified(False)

class TextToSpeechApp:
    def __init__(self, root):
        self.root = root
        self.client = None
        self.api_key = ""
        self.save_path = os.getcwd()
        self.voice = "alloy"
        self.last_saved_file = None
        self.converting = False
        self.load_settings()
        self.tts_method = 'openai'
        self.coqui_speaker_path = ''
        style = ttk.Style()
        style.theme_use('clam')
        self.main_frame = ttk.Frame(root)
        self.main_frame.pack(padx=10, pady=10, fill='both', expand=True)
        self.status_bar = ttk.Label(self.main_frame, text="", relief=tk.SUNKEN, anchor="e")
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.text_entry = CustomText(self.main_frame, font=("TkDefaultFont", 11), bd=2, relief="groove")
        self.text_entry.pack(fill='both', expand=True)
        self.text_entry.set_app(self)
        self.buttons_frame = ttk.Frame(self.main_frame)
        self.buttons_frame.pack(pady=10)
        self.convert_button = ttk.Button(self.buttons_frame, text="convert", command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT, padx=5)
        self.play_button = ttk.Button(self.buttons_frame, text="play", command=self.play_last_saved_audio, state='disabled')
        self.play_button.pack(side=tk.LEFT, padx=5)
        self.reset_button = ttk.Button(self.buttons_frame, text="reset", command=self.reset_text_field)
        self.reset_button.pack(side=tk.LEFT, padx=5)
        self.settings_button = ttk.Button(self.buttons_frame, text="⚙️", command=self.open_settings)
        self.settings_button.pack(side=tk.LEFT, padx=5)
        self.check_buttons_state()
        self.update_status_bar()
        self.keep_parts = False
        self.lock = threading.Lock()
        self.part_file_paths = []

    def reset_text_field(self):
        self.text_entry.delete('1.0', tk.END)

    def check_buttons_state(self):
        if self.text_entry.get("1.0", "end-1c").strip():
            self.convert_button["state"] = "normal"
            self.reset_button["state"] = "normal"
        else:
            self.convert_button["state"] = "disabled"
            self.reset_button["state"] = "disabled"

    def reset_convert_button_style(self):
        self.convert_button.config(style="")
        self.convert_button["state"] = "normal"

    def on_text_change(self, event=None):
        self.convert_button.config(style="TButton")

        self.text_entry.unbind("<<TextModified>>")



    def after_conversion(self):
        self.convert_button["state"] = "normal"
        self.convert_button["state"] = "disabled"

    def open_settings(self):
        self.settings_window = tk.Toplevel(self.main_frame)
        self.settings_window.title("settings")
        self.settings_window.grab_set()
        ttk.Label(self.settings_window, text="API-Key:").pack(padx=10, pady=5)
        self.api_key_entry = ttk.Entry(self.settings_window, font=("TkDefaultFont", 12), width=60)
        self.api_key_entry.pack(padx=10, pady=5)
        self.api_key_entry.insert(0, self.api_key)
        self.voice_var = tk.StringVar(self.settings_window)
        self.voice_var.set(self.voice)
        ttk.Label(self.settings_window, text="voice:").pack(padx=10, pady=5)
        voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        self.voice_menu = ttk.Combobox(self.settings_window, textvariable=self.voice_var, values=voices,state="readonly")
        self.voice_menu.pack(padx=10, pady=5)
        ttk.Label(self.settings_window, text="location:").pack(padx=10, pady=5)
        self.save_path_frame = ttk.Frame(self.settings_window)
        self.save_path_frame.pack(padx=10, pady=5, fill='x')
        self.save_path_entry = ttk.Entry(self.save_path_frame, font=("TkDefaultFont", 11))
        self.save_path_entry.pack(side=tk.LEFT, fill='x', expand=True)
        self.save_path_entry.insert(0, self.save_path)
        ttk.Button(self.save_path_frame, text="choose", command=self.choose_save_path).pack(side=tk.LEFT, padx=5)
        ttk.Label(self.settings_window, text="price per 1000 characters ($):").pack(padx=10, pady=5)
        self.price_entry = ttk.Entry(self.settings_window, font=("TkDefaultFont", 11))
        self.price_entry.pack(padx=10, pady=5)
        self.price_entry.insert(0, str(self.price_per_thousand_chars))
        self.keep_parts_var = tk.BooleanVar(value=self.keep_parts)
        ttk.Checkbutton(self.settings_window, text="keep part files", variable=self.keep_parts_var).pack(padx=10,pady=5)
        ttk.Button(self.settings_window, text="save", command=self.save_settings).pack(padx=10, pady=5)

    def update_status_bar(self):
        text = self.text_entry.get("1.0", "end-1c")
        words = len(text.split())
        characters = len(text)
        price = (characters / 1000) * self.price_per_thousand_chars
        status_text = f"words: {words}, characters: {characters}, price: ${price:.2f}"
        self.status_bar.config(text=status_text)

    def choose_save_path(self):
        self.settings_window.grab_release()
        self.save_path = filedialog.askdirectory(parent=self.settings_window)
        if not self.save_path:
            self.save_path = os.getcwd()
        self.save_path_entry.delete(0, tk.END)
        self.save_path_entry.insert(0, self.save_path)
        self.settings_window.grab_set()

    def save_settings(self):
        self.api_key = self.api_key_entry.get()
        self.voice = self.voice_var.get()
        self.client = OpenAI(api_key=self.api_key)
        self.price_per_thousand_chars = float(self.price_entry.get())
        self.keep_parts = self.keep_parts_var.get()
        self.save_config_to_file()
        self.settings_window.destroy()


    def save_config_to_file(self):
        config_data = {
            'api_key': self.api_key,
            'voice': self.voice,
            'save_path': self.save_path,
            'price_per_thousand_chars': self.price_per_thousand_chars,
            'keep_parts': self.keep_parts,
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f)

    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
                self.api_key = config_data.get('api_key', '')
                self.voice = config_data.get('voice', 'alloy')
                self.save_path = config_data.get('save_path', os.getcwd())
                if self.api_key:
                    self.client = OpenAI(api_key=self.api_key)
                self.price_per_thousand_chars = config_data.get('price_per_thousand_chars', 0.015)
                self.keep_parts = config_data.get('keep_parts', False)
        else:
            self.price_per_thousand_chars = 0.015

    def finish_conversion(self):
        if None in self.audio_segments:
            messagebox.showwarning("Fehler", "Einige Teile konnten nicht konvertiert werden.")
        else:
            final_audio = sum(self.audio_segments)
            final_audio_path = os.path.join(self.save_path, f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3")
            final_audio.export(final_audio_path, format="mp3", bitrate="320k")
            self.last_saved_file = final_audio_path
            if not self.keep_parts:
                for file_path in self.part_file_paths:
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        pass
                self.part_file_paths.clear()

        self.converting = False
        self.convert_button["state"] = "normal"
        self.play_button["state"] = "normal"
        self.reset_button["state"] = "normal"

    def convert_part(self, text, index):
        try:
            audio_path = self.text_to_speech(text, index)
            if audio_path:
                with self.lock:  # Stellen Sie sicher, dass dieser Abschnitt threadsicher ist
                    self.part_file_paths.append(audio_path)  # Speichern des Pfades
                self.audio_segments[index] = AudioSegment.from_mp3(audio_path)
            else:
                self.audio_segments[index] = AudioSegment.silent(duration=1000)
        except Exception as e:
            messagebox.showwarning("Fehler", f"Fehler beim Konvertieren des Teils {index}: {e}")
            self.audio_segments[index] = AudioSegment.silent(duration=1000)

    def start_conversion(self):
        self.converting = True
        self.convert_button["state"] = "disabled"
        self.play_button["state"] = "disabled"
        self.reset_button["state"] = "disabled"


        if self.tts_method == "coqui":
            file_path = self.text_to_speech(self.text_entry.get("1.0", "end-1c"), 0)
            if file_path:
                self.last_saved_file = file_path
            self.after_conversion()

        else:
            text_parts = self.split_text(self.text_entry.get("1.0", "end-1c"))
            self.threads = []
            self.audio_segments = [None] * len(text_parts)
            for i, part in enumerate(text_parts):
                thread = threading.Thread(target=self.convert_part, args=(part, i))
                thread.start()
                self.threads.append(thread)
            valid_audio_segments = [seg for seg in self.audio_segments if isinstance(seg, AudioSegment)]
            part_files = [seg for seg in self.audio_segments if isinstance(seg, str)]
            if valid_audio_segments:
                final_audio = sum(valid_audio_segments)
                final_audio_path = os.path.join(self.save_path, f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3")
                final_audio.export(final_audio_path, format="mp3", bitrate="320k")
                self.last_saved_file = final_audio_path
                if not self.keep_parts:
                    for file_path in self.part_file_paths:
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            messagebox.showwarning("Fehler", f"Fehler beim Löschen der Datei {file_path}: {e}")
                            print(f"Fehler beim Löschen der Datei {file_path}: {e}")
            else:
                pass
        self.converting = False


    def split_text(self, text):
        max_length = 4000
        parts = []
        while text:
            if len(text) <= max_length:
                parts.append(text)
                break
            else:
                split_index = text.rfind('\n', 0, max_length)
                if split_index == -1:
                    split_index = text.rfind(' ', 0, max_length)
                part = text[:split_index]
                parts.append(part)
                text = text[split_index:].lstrip()
        return parts

    def text_to_speech(self, text, part_index):
            try:
                response = self.client.audio.speech.create(
                    model="tts-1",
                    voice=self.voice,
                    input=text
                )

                if not response or not response.content:
                    messagebox.showwarning("Fehler", "Keine gültige Antwort von der OpenAI API erhalten.")
                    return None

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"output_{timestamp}_{part_index}.mp3"
                file_path = os.path.join(self.save_path, file_name)

                with open(file_path, 'wb') as file:
                    file.write(response.content)
                return file_path

            except Exception as e:
                messagebox.showwarning("Fehler", f"Fehler bei der OpenAI Text-zu-Sprache-Umwandlung: ,{e}")
                print("Fehler bei der OpenAI Text-zu-Sprache-Umwandlung:", e)
                return None

    def get_conversion_steps(self, text):
        return text.split('.')

    def perform_conversion_step(self, step):
        pass

    def play_last_saved_audio(self):
        if self.last_saved_file and os.path.exists(self.last_saved_file):
            if sys.platform == 'win32':
                os.startfile(self.last_saved_file)
            elif sys.platform == 'darwin':
                subprocess.call(['open', self.last_saved_file])
            else:
                subprocess.call(['xdg-open', self.last_saved_file])


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Text-zu-Sprache Konverter")
    app = TextToSpeechApp(root)
    root.geometry("800x600")
    root.mainloop()
