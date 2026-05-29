import os
import sys
import re
import time
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

# ─────────────────────────────────────────────
#  helpers
# ─────────────────────────────────────────────

def extract_movie_info(filename):
    m = re.search(r'[.\s_]((19|20)\d{2})[.\s_]', filename)
    if m:
        year = m.group(1)
        raw  = filename[:m.start()]
        return re.sub(r'[._-]', ' ', raw).strip(), year
    return None, None

def get_clean_words(text):
    return set(re.sub(r'[._-]', ' ', text.lower()).split())

# ─────────────────────────────────────────────
#  OMDb — جلب سنة الإصدار الحقيقية
# ─────────────────────────────────────────────
_year_cache = {}

def fetch_year_from_omdb(title):
    # تحميل المكتبات هنا فقط عند الحاجة لعدم تبطيء فتح البرنامج
    import urllib.request
    import urllib.parse
    import json

    if title in _year_cache:
        return _year_cache[title]

    try:
        query = urllib.parse.urlencode({"t": title, "type": "series"})
        url   = f"http://www.omdbapi.com/?{query}&apikey=trilogy"
        req   = urllib.request.Request(url, headers={"User-Agent": "SRT-Renamer/3.1"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        if data.get("Response") == "True":
            year = data.get("Year", "")[:4]
            if re.match(r'(19|20)\d{2}', year):
                _year_cache[title] = year
                return year
    except Exception:
        pass

    try:
        query = urllib.parse.urlencode({"query": title})
        url   = f"https://api.themoviedb.org/3/search/tv?{query}&api_key=2696829a81b1b5827d515571ef8d8289"
        req   = urllib.request.Request(url, headers={"User-Agent": "SRT-Renamer/3.1"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        if results:
            date = results[0].get("first_air_date", "")
            year = date[:4]
            if re.match(r'(19|20)\d{2}', year):
                _year_cache[title] = year
                return year
    except Exception:
        pass

    _year_cache[title] = None
    return None

# ─────────────────────────────────────────────
#  بناء SubSource slug + URL
# ─────────────────────────────────────────────

def build_slug(name):
    s = name.lower()
    s = re.sub(r"'s\b", 's', s)
    s = re.sub(r"'", '', s)
    s = s.replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return re.sub(r'-+', '-', s).strip('-')

def build_subsource_url(video_file, log=None):
    series_match = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)

    if series_match:
        season_num  = int(series_match.group(1))
        raw_name    = video_file[:series_match.start()]
        
        year_m = re.search(r'\b((?:19|20)\d{2})\b', raw_name)
        year   = year_m.group(1) if year_m else None
        
        if year:
            raw_name = raw_name.replace(year, '')
            
        series_name = re.sub(r'[._-]', ' ', raw_name).strip()

        if season_num > 1:
            year = None
            if log: log(f"   ⚠️  الموسم ({season_num}) أكبر من 1، سيتم تجاهل سنة الإصدار")
        else:
            if not year:
                if log: log(f"   🔎 جاري البحث عن سنة إصدار «{series_name}»...")
                year = fetch_year_from_omdb(series_name)
                if year and log:
                    log(f"   📅 سنة الإصدار: {year}")
                else:
                    year = time.strftime("%Y")
                    if log: log(f"   ⚠️  تم استخدام السنة الحالية ({year})")

        slug = build_slug(series_name)
        if year: slug = f"{slug}-{year}"

        direct_url   = f"https://subsource.net/subtitles/{slug}/season-{season_num}"
        fallback_url = f"https://subsource.net/search?q=" + series_name.replace(' ', '+')
        return direct_url, fallback_url, series_name, season_num, year

    else:
        movie_name, year = extract_movie_info(video_file)
        if movie_name:
            if not year: year = time.strftime("%Y")
            slug = build_slug(movie_name)
            if year: slug = f"{slug}-{year}"
            direct_url   = f"https://subsource.net/subtitles/{slug}"
            fallback_url = (f"https://subsource.net/search?q=" + (movie_name + (f"+{year}" if year else "")).replace(' ', '+'))
            return direct_url, fallback_url, movie_name, None, year

    return None, None, None, None, None

# ─────────────────────────────────────────────
#  ZIP helpers 
# ─────────────────────────────────────────────

def get_zip_snapshot(downloads_path):
    zips = {}
    try:
        with os.scandir(downloads_path) as it:
            for entry in it:
                if entry.name.lower().endswith('.zip') and entry.is_file():
                    zips[entry.path] = entry.stat().st_mtime
    except Exception:
        pass
    return zips

def find_matching_zip(video_file, series_match, zip_snapshot):
    if series_match:
        raw_name    = video_file[:series_match.start()]
        series_name = re.sub(r'[._-]', ' ', raw_name).strip()
        vw = get_clean_words(f"{series_name} season {int(series_match.group(1))}")
    else:
        mn, yr = extract_movie_info(video_file)
        if not mn: return None
        vw = get_clean_words(f"{mn} {yr}" if yr else mn)

    best, best_score = None, 0
    sorted_zips = sorted(zip_snapshot.items(), key=lambda x: x[1], reverse=True)

    for path, _ in sorted_zips:
        filename = os.path.basename(path)
        zw = get_clean_words(os.path.splitext(filename)[0])
        if vw and zw:
            score = len(vw & zw) / len(vw)
            if score > best_score:
                best_score, best = score, path
                
    return best if best_score >= 0.5 else None

def extract_srt_from_zip(zip_path, target_dir):
    import zipfile
    import shutil
    extracted = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if name.lower().endswith('.srt'):
                    fname = os.path.basename(name)
                    if fname:
                        dest = os.path.join(target_dir, fname)
                        with zf.open(name) as src, open(dest, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        extracted.append(fname)
    except Exception:
        pass
    return extracted

def wait_for_new_zip(downloads_path, snapshot_before, timeout=300, poll=0.8, cancel_event=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_event and cancel_event.is_set():
            return None
            
        current = get_zip_snapshot(downloads_path)
        new_zips = [path for path, mtime in current.items() 
                    if path not in snapshot_before or mtime > snapshot_before[path]]
                    
        if new_zips:
            completed = []
            for z in new_zips:
                base = os.path.splitext(z)[0]
                if not any(os.path.exists(base + ext) for ext in ('.crdownload', '.part', '.tmp')):
                    completed.append(z)
                    
            if completed:
                time.sleep(1)
                return completed[0]
                
        time.sleep(poll)
    return None

# ─────────────────────────────────────────────
#  rename
# ─────────────────────────────────────────────

def do_rename(video_file, base_name, series_match, directory, log):
    count = 0
    with os.scandir(directory) as it:
        files = [f.name for f in it if f.is_file() and f.name.lower().endswith('.srt')]
        
    if series_match:
        s, e = series_match.groups()
        pattern = re.compile(rf'S{s}E{e}', re.IGNORECASE)
        for f in files:
            if pattern.search(f):
                new_f = f"{base_name}{os.path.splitext(f)[1]}"
                if f == new_f: continue
                try:
                    dest = os.path.join(directory, new_f)
                    if os.path.exists(dest): os.remove(dest)
                    os.rename(os.path.join(directory, f), dest)
                    count += 1
                    log(f"✏️  تمت التسمية: {new_f}")
                except Exception:
                    pass
    else:
        mn, yr = extract_movie_info(video_file)
        if mn and yr:
            mn_words = get_clean_words(mn)
            for f in files:
                sn, sy = extract_movie_info(f)
                if sy == yr and sn:
                    sn_words = get_clean_words(sn)
                    if sn_words and len(mn_words & sn_words) / max(len(mn_words), len(sn_words)) >= 0.6:
                        new_f = f"{base_name}{os.path.splitext(f)[1]}"
                        if f == new_f: continue
                        try:
                            dest = os.path.join(directory, new_f)
                            if os.path.exists(dest): os.remove(dest)
                            os.rename(os.path.join(directory, f), dest)
                            count += 1
                            log(f"✏️  تمت التسمية: {new_f}")
                        except Exception:
                            pass
    return count

# ─────────────────────────────────────────────
#  معالجة ملف فيديو واحد
# ─────────────────────────────────────────────

def process_one(video_file, directory, downloads_path, log, set_status, cancel_event):
    import webbrowser # استدعاء كسول
    base_name    = os.path.splitext(video_file)[0]
    series_match = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)

    has_srt = False
    with os.scandir(directory) as it:
        srt_files = [f.name for f in it if f.is_file() and f.name.lower().endswith('.srt')]

    if series_match:
        s, e = series_match.groups()
        pattern = re.compile(rf'S{s}E{e}', re.IGNORECASE)
        has_srt = any(pattern.search(f) for f in srt_files)
    else:
        mn, yr = extract_movie_info(video_file)
        if mn and yr:
            mn_words = get_clean_words(mn)
            for f in srt_files:
                sn, sy = extract_movie_info(f)
                if sy == yr and sn:
                    sn_words = get_clean_words(sn)
                    if sn_words and len(mn_words & sn_words) / max(len(mn_words), len(sn_words)) >= 0.6:
                        has_srt = True
                        break

    if has_srt:
        log(f"✅ SRT موجود مسبقاً")
        return do_rename(video_file, base_name, series_match, directory, log)

    current_zips = get_zip_snapshot(downloads_path)
    matched_path = find_matching_zip(video_file, series_match, current_zips)
    
    if matched_path:
        log(f"📦 ZIP موجود في Downloads: {os.path.basename(matched_path)}")
        extracted = extract_srt_from_zip(matched_path, directory)
        if extracted: log(f"   استخرجت: {', '.join(extracted)}")
        return do_rename(video_file, base_name, series_match, directory, log)

    direct_url, fallback_url, name, season_num, year = build_subsource_url(video_file, log=log)
    if not direct_url:
        log(f"❌ تعذّر بناء الرابط")
        return 0

    label = name + (f" — Season {season_num}" if season_num else f" ({year})" if year else "")
    log(f"🌐 فتح SubSource: {label}")
    set_status(f"⏳ انتظر تحميل ترجمة:\n{label}")

    snapshot = get_zip_snapshot(downloads_path)
    webbrowser.open(direct_url)

    new_zip_path = wait_for_new_zip(downloads_path, snapshot, timeout=120, cancel_event=cancel_event)

    if cancel_event and cancel_event.is_set():
        return 0

    if not new_zip_path:
        log(f"⚠️  انتهى الوقت — فتح صفحة البحث كبديل")
        snapshot2 = get_zip_snapshot(downloads_path)
        webbrowser.open(fallback_url)
        new_zip_path = wait_for_new_zip(downloads_path, snapshot2, timeout=120, cancel_event=cancel_event)
        if not new_zip_path:
            log(f"⏰ لم يتم التحميل — تخطي")
            return 0

    log(f"📦 ZIP جديد: {os.path.basename(new_zip_path)}")
    extracted = extract_srt_from_zip(new_zip_path, directory)
    if extracted:
        log(f"   استخرجت: {', '.join(extracted)}")
    else:
        log(f"⚠️  لا يوجد SRT داخل الـ ZIP")
        return 0

    return do_rename(video_file, base_name, series_match, directory, log)

# ─────────────────────────────────────────────
#  المشغّل الرئيسي
# ─────────────────────────────────────────────

def run_all(directory, result_label, root, log_widget, cancel_event):
    def log(msg):
        if log_widget:
            log_widget.config(state='normal')
            log_widget.insert('end', msg + '\n')
            log_widget.see('end')
            log_widget.config(state='disabled')
        if root: root.update_idletasks()

    def set_status(msg):
        result_label.config(text=msg, fg='#3498db')
        if root: root.update_idletasks()

    downloads_path = str(Path.home() / 'Downloads')
    if not os.path.exists(downloads_path):
        log("❌ مجلد Downloads غير موجود")
        result_label.config(text="خطأ: Downloads غير موجود", fg='#e74c3c')
        return

    with os.scandir(directory) as it:
        video_files = [f.name for f in it if f.is_file() and f.name.lower().endswith(('.mkv', '.mp4', '.avi'))]
        
    if not video_files:
        result_label.config(text="لا توجد ملفات فيديو", fg='#f1c40f')
        return

    log(f"🎬 {len(video_files)} ملف فيديو")
    total = 0

    for i, vf in enumerate(video_files, 1):
        if cancel_event.is_set(): break
        log(f"\n── [{i}/{len(video_files)}] {vf}")
        total += process_one(vf, directory, downloads_path, log, set_status, cancel_event)

    if cancel_event.is_set():
        result_label.config(text=f"تم الإيقاف\nتمت تسمية {total} ملف", fg='#f1c40f')
    elif total > 0:
        result_label.config(text=f"تم بنجاح! ✅\nتمت تسمية {total} ملف", fg='#2ecc71')
    else:
        result_label.config(text="لم يتم تسمية أي ملف", fg='#f1c40f')

# ─────────────────────────────────────────────
#  واجهة المستخدم (يتم تحميلها أولاً)
# ─────────────────────────────────────────────

def center_window(root, w, h):
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

if __name__ == '__main__':
    passed_directory = sys.argv[1] if len(sys.argv) > 1 else None
    cancel_event     = threading.Event()

    root = tk.Tk()
    root.title("Hassan's Smart SRT Renamer")
    root.configure(bg='#1a1a1a')
    root.resizable(False, False)
    center_window(root, 580, 520)
    # ← اظهر النافذة فوراً قبل أي شيء تاني
    root.update()

    tk.Label(root, text="SRT Smart Auto Renamer", font=('Segoe UI', 16, 'bold'), bg='#1a1a1a', fg='white').pack(pady=(15, 2))
    tk.Label(root, text="يفتح SubSource مباشرةً • حمّل الترجمة • يكمل وحده", font=('Segoe UI', 9), bg='#1a1a1a', fg='#7f8c8d').pack()

    btn_frame = tk.Frame(root, bg='#1a1a1a')
    btn_frame.pack(pady=12)

    start_btn = tk.Button(btn_frame, text='📂 Select Folder & Run', height=2, width=22, bg='#2980b9', fg='white', font=('Segoe UI', 11, 'bold'), relief='flat', cursor='hand2')
    start_btn.pack(side=tk.LEFT, padx=5)

    stop_btn = tk.Button(btn_frame, text='⏹ إيقاف', height=2, width=10, bg='#c0392b', fg='white', font=('Segoe UI', 10, 'bold'), relief='flat', cursor='hand2', state='disabled')
    stop_btn.pack(side=tk.LEFT, padx=5)

    result_label = tk.Label(root, text='اختر مجلد للبدء...', font=('Segoe UI', 12, 'bold'), bg='#1a1a1a', fg='#7f8c8d', justify='center')
    result_label.pack(pady=6, fill=tk.X)

    frame = tk.Frame(root, bg='#1a1a1a')
    frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
    sb = tk.Scrollbar(frame)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    log_widget = tk.Text(frame, height=14, bg='#111111', fg='#aaaaaa', font=('Consolas', 9), relief='flat', state='disabled', wrap='word', yscrollcommand=sb.set)
    log_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.config(command=log_widget.yview)

    def start_run(directory=None):
        d = directory or filedialog.askdirectory()
        if not d: return
        cancel_event.clear()
        result_label.config(text='جاري الفحص السريع...', fg='white')
        log_widget.config(state='normal')
        log_widget.delete('1.0', 'end')
        log_widget.config(state='disabled')
        start_btn.config(state='disabled')
        stop_btn.config(state='normal')

        def thread_target():
            run_all(d, result_label, root, log_widget, cancel_event)
            if not cancel_event.is_set():
                root.after(0, lambda: result_label.config(text=result_label.cget("text") + "\nيتم الإغلاق...", fg='#3498db'))
                root.after(800, root.destroy)
            else:
                root.after(0, lambda: (start_btn.config(state='normal'), stop_btn.config(state='disabled')))

        threading.Thread(target=thread_target, daemon=True).start()

    def stop_run():
        cancel_event.set()
        result_label.config(text='جاري الإيقاف...', fg='#f1c40f')
        stop_btn.config(state='disabled')

    start_btn.config(command=start_run)
    stop_btn.config(command=stop_run)

    if passed_directory:
        result_label.config(text='جاري العمل على المجلد المسحوب...', fg='white')
        root.after(300, lambda: start_run(passed_directory))

    # mainloop
    root.mainloop()