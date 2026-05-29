import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import static_ffmpeg
from deep_translator import GoogleTranslator
from tkinterdnd2 import DND_FILES, TkinterDnD

# تجهيز محرك FFmpeg
try:
    static_ffmpeg.add_paths()
except:
    pass

class VideoSubMaster:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Subtitle Translator Turbo")
        self.root.geometry("650x550")
        self.video_path = ""
        self.supported_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm')
        self.setup_ui()

        if len(sys.argv) > 1:
            self.root.after(500, lambda: self.process_video(sys.argv[1]))

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.drop_label = tk.Label(
            main_frame, text="اسحب الفيديو أو المجلد هنا\nالترجمة الآن تعمل بنظام التوازي الفائق", 
            padx=20, pady=40, bg="#1a252f", fg="white",
            font=("Segoe UI", 12, "bold"), relief="flat"
        )
        self.drop_label.pack(fill=tk.X, pady=10)
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.handle_drop)

        self.info_label = ttk.Label(main_frame, text="بانتظار ملف...", font=("Segoe UI", 10, "italic"))
        self.info_label.pack(pady=5)

        self.tree = ttk.Treeview(main_frame, columns=("ID", "Lang", "Codec"), show='headings', height=6)
        for col in ("ID", "Lang", "Codec"): self.tree.heading(col, text=col)
        self.tree.column("ID", width=50, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, pady=10)

        self.action_btn = ttk.Button(main_frame, text="بدء الترجمة النفاثة للعربية", command=self.start_workflow, state="disabled")
        self.action_btn.pack(pady=10, fill=tk.X)

        self.status_var = tk.StringVar(value="جاهز")
        self.status_bar = tk.Label(main_frame, textvariable=self.status_var, fg="#2980b9", font=("Segoe UI", 10, "bold"))
        self.status_bar.pack(pady=5)

    def handle_drop(self, event):
        path = event.data.strip().strip('{}').strip('"')
        self.process_video(path)

    def process_video(self, path):
        target = ""
        if os.path.isdir(path):
            for f in os.listdir(path):
                if f.lower().endswith(self.supported_extensions):
                    target = os.path.join(path, f); break
        elif path.lower().endswith(self.supported_extensions):
            target = path
        
        if target:
            self.video_path = target
            self.info_label.config(text=f"الفيديو المكتشف: {os.path.basename(target)}", foreground="#27ae60")
            self.scan_subtitles(target)
        else:
            messagebox.showwarning("خطأ", "لم يتم العثور على فيديو")

    def scan_subtitles(self, path):
        for i in self.tree.get_children(): self.tree.delete(i)
        try:
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path]
            data = json.loads(subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8').stdout)
            found = False
            for s in data.get('streams', []):
                if s.get('codec_type') == 'subtitle':
                    self.tree.insert("", tk.END, values=(s.get('index'), s.get('tags',{}).get('language','unk'), s.get('codec_name')))
                    found = True
            if found:
                self.action_btn.config(state="normal")
                self.tree.selection_set(self.tree.get_children()[0])
        except: self.status_var.set("خطأ في فحص الملف")

    def start_workflow(self):
        sel = self.tree.selection()
        if not sel: return
        self.action_btn.config(state="disabled")
        threading.Thread(target=self.run_process, args=(self.tree.item(sel[0])['values'],), daemon=True).start()

    def run_process(self, sub_info):
        try:
            self.status_var.set("جاري الاستخراج...")
            temp_sub = os.path.splitext(self.video_path)[0] + "_TEMP.srt"
            cmd = ['ffmpeg', '-i', self.video_path, '-map', f'0:{sub_info[0]}', temp_sub, '-y']
            subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            
            self.status_var.set("جاري الترجمة السريعة (توازي)...")
            if self.translate_file_turbo(temp_sub):
                self.status_var.set("تم بنجاح! سيتم الإغلاق...")
                self.root.after(1000, self.root.quit) # إغلاق البرنامج
            
            if os.path.exists(temp_sub): os.remove(temp_sub)
        except Exception as e:
            self.status_var.set(f"فشل: {e}")
            self.action_btn.config(state="normal")

    def translate_chunk(self, chunk):
        """دالة فرعية لترجمة مجموعة واحدة"""
        try:
            translator = GoogleTranslator(source='auto', target='ar')
            combined = " \n ### \n ".join(chunk)
            translated = translator.translate(combined)
            return translated.split("###")
        except:
            return chunk # في حال الفشل نعود بالأصل

    def translate_file_turbo(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            to_translate = []
            line_map = []
            for i, line in enumerate(lines):
                clean = line.strip()
                if clean and not clean.isdigit() and "-->" not in clean:
                    to_translate.append(clean)
                    line_map.append(i)

            if not to_translate: return False

            # تقسيم الأسطر لمجموعات صغيرة (30 سطر لكل طلب لزيادة السرعة والثبات)
            chunk_size = 30
            chunks = [to_translate[i:i + chunk_size] for i in range(0, len(to_translate), chunk_size)]
            
            # استخدام ThreadPoolExecutor لتشغيل الترجمة بالتوازي (10 خيوط عمل معاً)
            all_translated_results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(self.translate_chunk, chunks))
            
            # تجميع النتائج
            flat_results = [item for sublist in results for item in sublist]

            # دمج النتائج في الملف
            for idx, text in enumerate(flat_results):
                if idx < len(line_map):
                    lines[line_map[idx]] = text.strip() + "\n"

            final_output = os.path.splitext(self.video_path)[0] + ".ar.srt"
            with open(final_output, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = VideoSubMaster(root)
    root.mainloop()