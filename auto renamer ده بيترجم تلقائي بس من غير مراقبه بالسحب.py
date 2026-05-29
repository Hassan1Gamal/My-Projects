# ─────────────────────────────────────────────
#  Auto Subs — v9  (by Hassan) - Fixed Options & Diagnostics
# ─────────────────────────────────────────────

import os, re, sys, zipfile, shutil, time, io, threading, base64, json, sqlite3, logging
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime
import subprocess

# ─────────────────────────────────────────────
#  إخفاء الكونسول في ويندوز فوراً
# ─────────────────────────────────────────────
if sys.platform == "win32":
    try:
        import ctypes
        # لو شغال كـ .py عادي يخفي الكونسول
        # لو شغال كـ .exe (PyInstaller) الـ spec هو اللي بيتحكم (windowed mode)
        if not getattr(sys, 'frozen', False):
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
#  المكتبات الاختيارية ومتابعة أخطاء الاستيراد
# ─────────────────────────────────────────────
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

try:
    import rarfile
    RAR_AVAILABLE = True
except ImportError:
    RAR_AVAILABLE = False

# فحص تفصيلي لمكتبة تشغيل المتصفح لبيان سبب المشكلة
UC_AVAILABLE = False
UC_IMPORT_ERROR = None
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    UC_AVAILABLE = True
except Exception as e:
    UC_AVAILABLE = False
    UC_IMPORT_ERROR = str(e)

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw, ImageFont
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

# ─────────────────────────────────────────────
#  المسارات
# ─────────────────────────────────────────────
APP_NAME  = 'AutoSubs'
APP_DIR   = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), APP_NAME)
DB_PATH   = os.path.join(APP_DIR, 'stats.db')
CFG_PATH  = os.path.join(APP_DIR, 'config.json')
LOG_PATH  = os.path.join(APP_DIR, 'app.log')
ICON_PATH = os.path.join(APP_DIR, 'icon.png')
os.makedirs(APP_DIR, exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

# ─────────────────────────────────────────────
#  قاعدة البيانات
# ─────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        media_type TEXT,
        series_name TEXT,
        season INTEGER,
        episode INTEGER,
        status TEXT,
        timestamp TEXT
    )''')
    con.commit(); con.close()

def db_log(filename, media_type, series_name=None, season=None, episode=None, status='success'):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute('''INSERT INTO downloads
            (filename,media_type,series_name,season,episode,status,timestamp)
            VALUES (?,?,?,?,?,?,?)''',
            (filename, media_type, series_name, season, episode, status,
             datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        con.commit(); con.close()
    except Exception as e:
        logging.error(f'db_log: {e}')

def db_get_stats():
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        movies     = cur.execute("SELECT COUNT(*) FROM downloads WHERE media_type='movie' AND status='success'").fetchone()[0]
        series_cnt = cur.execute("SELECT COUNT(DISTINCT series_name) FROM downloads WHERE media_type='episode' AND status='success'").fetchone()[0]
        episodes   = cur.execute("SELECT COUNT(*) FROM downloads WHERE media_type='episode' AND status='success'").fetchone()[0]
        failed     = cur.execute("SELECT COUNT(*) FROM downloads WHERE status='failed'").fetchone()[0]
        top_series = cur.execute("""SELECT series_name, COUNT(*) c FROM downloads
            WHERE media_type='episode' AND status='success' AND series_name IS NOT NULL
            GROUP BY series_name ORDER BY c DESC LIMIT 1""").fetchone()
        this_month = cur.execute("""SELECT COUNT(*) FROM downloads WHERE status='success'
            AND timestamp >= date('now','start of month')""").fetchone()[0]
        failed_files = cur.execute("""SELECT filename, timestamp FROM downloads
            WHERE status='failed' ORDER BY timestamp DESC LIMIT 20""").fetchall()
        con.close()
        return {'movies':movies,'series':series_cnt,'episodes':episodes,
                'failed':failed,'top_series':top_series,'this_month':this_month,
                'failed_files':failed_files}
    except Exception as e:
        logging.error(f'db_get_stats: {e}')
        return {'movies':0,'series':0,'episodes':0,'failed':0,
                'top_series':None,'this_month':0,'failed_files':[]}

# ─────────────────────────────────────────────
#  الإعدادات
# ─────────────────────────────────────────────
DEFAULT_CONFIG = {
    'watch_folder': os.path.join(os.path.expanduser('~'), 'Downloads'),
    'auto_watch': True,
    'start_with_windows': True,
    'notifications': True,
    'scan_existing_archives': True,
}

def load_config():
    try:
        if os.path.exists(CFG_PATH):
            with open(CFG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg: cfg[k] = v
            return cfg
    except: pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CFG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────
#  Startup
# ─────────────────────────────────────────────
def get_exe_or_pythonw():
    if getattr(sys, 'frozen', False):
        return sys.executable
    py = sys.executable
    pw = os.path.join(os.path.dirname(py), 'pythonw.exe')
    return pw if os.path.exists(pw) else py

def get_pythonw():
    return get_exe_or_pythonw()

def set_startup(enable: bool):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r'Software\Microsoft\Windows\CurrentVersion\Run',
                             0, winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
                val = f'"{exe_path}" --tray'
            else:
                vbs_path = os.path.join(APP_DIR, 'AutoSubs.vbs')
                if not os.path.exists(vbs_path):
                    vbs_path = create_vbs_launcher()
                val = f'wscript.exe "{vbs_path}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, val)
            logging.info(f'Startup registered: {val}')
        else:
            try: winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError: pass
            logging.info('Startup removed')
        winreg.CloseKey(key)
    except Exception as e:
        logging.error(f'set_startup: {e}')

def create_vbs_launcher():
    vbs_path = os.path.join(APP_DIR, 'AutoSubs.vbs')
    exe = get_pythonw()
    script = os.path.abspath(__file__)
    content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run Chr(34) & "{exe}" & Chr(34) & " " & Chr(34) & "{script}" & Chr(34) & " --tray", 0, False
'''
    with open(vbs_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return vbs_path

# ─────────────────────────────────────────────
#  الأيقونة
# ─────────────────────────────────────────────
def create_tray_image(size=64):
    img = Image.new('RGBA', (size, size), (0,0,0,0))
    d   = ImageDraw.Draw(img)
    s = size
    d.rounded_rectangle([3, 14, s-3, s-6], radius=6, fill=(0,0,0,80))
    d.rounded_rectangle([2, 13, s-4, s-7], radius=6, fill='#E67E22')
    d.polygon([(2, 13), (22, 13), (27, 8), (2, 8)], fill='#F39C12')
    d.rounded_rectangle([6, 18, s-8, s-12], radius=4, fill='#F0A500', outline='#E67E22', width=0)
    try:
        font = ImageFont.truetype("arialbd.ttf", int(s*0.30))
    except:
        font = ImageFont.load_default()
    text = 'AS'
    bbox = d.textbbox((0,0), text, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    tx = (s - tw) // 2 - 1
    ty = (s - th) // 2 + 4
    d.text((tx+1, ty+1), text, font=font, fill=(0,0,0,120))
    d.text((tx, ty), text, font=font, fill='white')
    return img

def save_icon():
    img = create_tray_image(256)
    img.save(ICON_PATH)
    return ICON_PATH

# ─────────────────────────────────────────────
#  الإشعارات
# ─────────────────────────────────────────────
def send_notification(event_type: str, details: dict):
    cfg = load_config()
    if not cfg.get('notifications', True):
        return

    if event_type == 'done_movie':
        title = '🎬 Auto Subs — فيلم جاهز!'
        movie = details.get('name', 'فيلم')
        year  = details.get('year', '')
        msg   = f'تم تحميل ترجمة:\n{movie} {f"({year})" if year else ""}'
    elif event_type == 'done_episode':
        title = '📺 Auto Subs — حلقة جاهزة!'
        series  = details.get('series', 'مسلسل')
        season  = details.get('season', '')
        episode = details.get('episode', '')
        msg = f'{series}\nالموسم {season} — الحلقة {episode}'
    elif event_type == 'done_multi':
        title = '✅ Auto Subs — اكتمل!'
        count = details.get('count', 0)
        name  = details.get('name', '')
        msg   = f'تم تحميل {count} ترجمة' + (f'\n{name}' if name else '')
    elif event_type == 'archive_found':
        title = 'Auto Subs - تم فك الضغط'
        count  = details.get('count', 0)
        videos = details.get('videos', [])
        if videos:
            names = ', '.join(os.path.splitext(v)[0] for v in videos[:2])
            if len(videos) > 2: names += f' (+{len(videos)-2})'
            msg = f'تم تسمية {count} ترجمة: {names}'
        else:
            fname = details.get('file', '')
            msg = f'تم فك ضغط {count} ترجمة'
    elif event_type == 'failed':
        title = '⚠️ Auto Subs — لم تُوجد ترجمة'
        name = details.get('name', 'الملف')
        msg  = f'لا توجد ترجمة ملاءمة لـ:\n{name}'
    elif event_type == 'found':
        title = '🔍 Auto Subs — جاري البحث'
        name = details.get('name', '')
        msg  = f'يبحث عن ترجمة:\n{name}'
    else:
        title = 'Auto Subs'
        msg   = details.get('msg', '')

    _fire_notification(title, msg)

def _fire_notification(title, msg, play_sound=False):
    import re as _re
    def _clean(text):
        return _re.sub(r'[^\u0000-\u04FF\u0600-\u06FF\s\-\(\)\.\,\/\\\:]', '', text).replace('\n', ' ').strip()
    try:
        if sys.platform != 'win32':
            return
        clean_title = _clean(title)
        clean_msg   = _clean(msg)
        if TRAY_AVAILABLE and _tray_icon is not None:
            _tray_icon.notify(clean_msg, clean_title)
    except Exception as e:
        logging.error(f'notification error: {e}')

def register_context_menu():
    try:
        import winreg
        if getattr(sys, 'frozen', False):
            cmd = f'"{sys.executable}" "%1"'
        else:
            exe = get_pythonw()
            script = os.path.abspath(__file__)
            cmd = f'"{exe}" "{script}" "%1"'
        for base in [r'*\shell', r'Directory\shell']:
            shell_path   = rf'{base}\AutoSubs'
            command_path = rf'{base}\AutoSubs\command'
            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, shell_path)
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, '🎬 Auto Subs — تحميل ترجمة')
            winreg.SetValueEx(key, 'MultiSelectModel', 0, winreg.REG_SZ, 'Player')
            winreg.CloseKey(key)
            key2 = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_path)
            winreg.SetValueEx(key2, '', 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key2)
        return True
    except Exception as e:
        logging.error(f'register_context_menu: {e}')
        return False

def unregister_context_menu():
    try:
        import winreg
        for base in [r'*\shell', r'Directory\shell']:
            try:
                winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, rf'{base}\AutoSubs\command')
                winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, rf'{base}\AutoSubs')
            except: pass
    except Exception as e:
        logging.error(f'unregister_context_menu: {e}')

# ─────────────────────────────────────────────
#  Chrome Singleton (نسخة مدمجة مع الكود الشغال لديك)
# ─────────────────────────────────────────────
_driver      = None
_driver_lock = threading.Lock()

def kill_orphaned_chromes():
    if sys.platform == "win32":
        try:
            subprocess.run("taskkill /f /im chromedriver.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass

def get_driver(log=None):
    global _driver
    with _driver_lock:
        if _driver is None and UC_AVAILABLE:
            if log: log('   ⏳ جاري تهيئة متصفح Chrome وتطهير العمليات العالقة...')
            kill_orphaned_chromes()
            
            try:
                opts = uc.ChromeOptions()
                opts.add_argument('--window-size=900,600')
                opts.add_argument('--window-position=2000,0')
                opts.add_argument('--lang=en-US')
                opts.add_argument('--no-sandbox')
                opts.add_argument('--disable-dev-shm-usage')
                opts.add_argument('--disable-blink-features=AutomationControlled')
                
                # إعدادات التشغيل المطابقة لنسختك الشغالة
                _driver = uc.Chrome(options=opts, version_main=148, use_subprocess=True)
                _driver.set_page_load_timeout(40)
                
                # إخفاء نافذة الكروم فوراً
                try:
                    import ctypes
                    hwnd = ctypes.windll.user32.FindWindowW(None, _driver.title or 'Chrome')
                    if hwnd:
                        ctypes.windll.user32.ShowWindow(hwnd, 0)
                except Exception:
                    pass
                
                if log: log('   ✅ تم تشغيل متصفح Chrome بنجاح.')
            except Exception as e:
                if log: log(f'   ❌ فشل بدء تشغيل المتصفح: {str(e)[:120]}')
                _driver = None
        return _driver

def quit_driver():
    global _driver
    with _driver_lock:
        if _driver:
            try: _driver.quit()
            except: pass
            _driver = None

# ─────────────────────────────────────────────
#  Helpers & URLs (تمت المزامنة مع النسخة الشغالة)
# ─────────────────────────────────────────────
VALID_SUB_EXTS   = ('.srt', '.ass', '.vtt', '.sub', '.idx')
VALID_VIDEO_EXTS = ('.mkv', '.mp4', '.avi')
CURRENT_YEAR     = 2026

def extract_movie_info(filename):
    m = re.search(r'[.\s_]((19|20)\d{2})[.\s_]', filename)
    if m:
        raw = filename[:m.start()]
        return re.sub(r'[._-]', ' ', raw).strip(), m.group(1)
    return None, None

def get_clean_words(text):
    return set(re.sub(r'[._-]', ' ', text.lower()).split())

_year_cache = {}
_http = requests.Session()
_http.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'

def fetch_year(title):
    if title in _year_cache: return _year_cache[title]
    for params, url in [({'t': title, 'type': 'series', 'apikey': 'trilogy'}, 'http://www.omdbapi.com/')]:
        try:
            d = _http.get(url, params=params, timeout=6).json()
            if d.get('Response') == 'True' and re.match(r'(19|20)\d{2}', d.get('Year', '')[:4]):
                y = d['Year'][:4]; _year_cache[title] = y; return y
        except: pass
    try:
        d = _http.get('https://api.themoviedb.org/3/search/tv', params={'query': title, 'api_key': '2696829a81b1b5827d515571ef8d8289'}, timeout=6).json()
        if d.get('results') and re.match(r'(19|20)\d{2}', d['results'][0].get('first_air_date', '')[:4]):
            y = d['results'][0]['first_air_date'][:4]; _year_cache[title] = y; return y
    except: pass
    _year_cache[title] = None; return None

def build_slug(name):
    s = re.sub(r"'s\b", 's', name.lower())
    s = re.sub(r"'", '', s).replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return re.sub(r'-+', '-', s).strip('-')

def build_urls(video_file, log=None, force_year=None):
    sm = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)
    if sm:
        season_num  = int(sm.group(1))
        raw         = video_file[:sm.start()]
        series_name = re.sub(r'[._-]', ' ', raw).strip()
        year_m      = re.search(r'((?:19|20)\d{2})', raw)
        year        = force_year or (year_m.group(1) if year_m else None)
        slug = build_slug(series_name)

        if season_num == 1: 
            if not year: 
                year = fetch_year(series_name) or str(CURRENT_YEAR) 
            if year and not year_m: slug = f'{slug}-{year}' 
        season_url = f'https://subsource.net/subtitles/{slug}/season-{season_num}'
        search_url = f'https://subsource.net/search?q={series_name.replace(" ","+")}'
        return season_url, search_url, series_name, season_num, year, sm
    else:
        mn, yr = extract_movie_info(video_file)
        if mn:
            slug = build_slug(mn)
            if yr: slug = f'{slug}-{yr}'
            movie_url  = f'https://subsource.net/subtitles/{slug}'
            search_url = f'https://subsource.net/search?q={mn.replace(" ","+")}{"+" + yr if yr else ""}'
            return movie_url, search_url, mn, None, yr, None
    return None, None, None, None, None, None

# ─────────────────────────────────────────────
#  فك الضغط
# ─────────────────────────────────────────────
def extract_archive_bytes(file_bytes, directory, log=None):
    extracted = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(VALID_SUB_EXTS):
                    fname = os.path.basename(name)
                    if fname:
                        dest = os.path.join(directory, fname)
                        with zf.open(name) as src, open(dest, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        extracted.append(fname)
            return extracted
    except zipfile.BadZipFile:
        pass
    except Exception as e:
        if log: log(f'   ❌ خطأ ZIP: {e}')
        return []
    if RAR_AVAILABLE:
        try:
            with rarfile.RarFile(io.BytesIO(file_bytes)) as rf:
                for name in rf.namelist():
                    if name.lower().endswith(VALID_SUB_EXTS):
                        fname = os.path.basename(name)
                        if fname:
                            dest = os.path.join(directory, fname)
                            with rf.open(name) as src, open(dest, 'wb') as dst:
                                shutil.copyfileobj(src, dst)
                            extracted.append(fname)
                return extracted
        except Exception as e:
            if log: log(f'   ❌ خطأ RAR: {e}')
    return []

def extract_archive_file(archive_path, directory, log=None):
    try:
        with open(archive_path, 'rb') as f:
            data = f.read()
        return extract_archive_bytes(data, directory, log)
    except Exception as e:
        if log: log(f'   ❌ خطأ قراءة الأرشيف: {e}')
        return []

# ─────────────────────────────────────────────
#  فحص الأرشيفات الموجودة
# ─────────────────────────────────────────────
ARCHIVE_EXTS = ('.zip', '.rar', '.7z')

def looks_like_subtitle_archive(archive_path):
    try:
        with zipfile.ZipFile(archive_path) as zf:
            return any(n.lower().endswith(VALID_SUB_EXTS) for n in zf.namelist())
    except:
        pass
    if RAR_AVAILABLE:
        try:
            with rarfile.RarFile(archive_path) as rf:
                return any(n.lower().endswith(VALID_SUB_EXTS) for n in rf.namelist())
        except:
            pass
    return False

def find_best_video_for_subtitle(sub_file, video_files):
    sub_base = os.path.splitext(sub_file)[0].lower()
    sm = re.search(r's(\d+)e(\d+)', sub_base, re.IGNORECASE)
    if sm:
        for vf in video_files:
            vm = re.search(r'S(\d+)E(\d+)', vf, re.IGNORECASE)
            if vm and vm.group(1) == sm.group(1) and vm.group(2) == sm.group(2):
                return vf

    sub_words = get_clean_words(sub_base)
    best_score = 0; best_vf = None
    for vf in video_files:
        vf_words = get_clean_words(os.path.splitext(vf)[0])
        if not vf_words: continue
        score = len(sub_words & vf_words) / max(len(sub_words | vf_words), 1)
        if score > best_score:
            best_score = score; best_vf = vf
    if best_score >= 0.4:
        return best_vf
    return None

def scan_downloads_for_archives(folder, log=None, progress_cb=None):
    if not os.path.isdir(folder):
        return 0
    total_renamed = 0
    for root, dirs, files in os.walk(folder):
        archive_files = [f for f in files if f.lower().endswith(ARCHIVE_EXTS)]
        video_files   = [f for f in files if f.lower().endswith(VALID_VIDEO_EXTS)]

        for archive_name in archive_files:
            archive_path = os.path.join(root, archive_name)
            if log: log(f'\n📦 فحص: {archive_name}')

            if not looks_like_subtitle_archive(archive_path):
                if log: log('   ⏭️  ليس أرشيف ترجمات')
                continue

            extracted = extract_archive_file(archive_path, root, log)
            if not extracted:
                if log: log('   ❌ لا شيء في الأرشيف أو خطأ')
                continue

            if log: log(f'   ✅ استُخرج: {", ".join(extracted)}')

            renamed = 0
            for sub_file in extracted:
                sub_path = os.path.join(root, sub_file)
                best_vid = find_best_video_for_subtitle(sub_file, video_files)
                if best_vid:
                    new_name = os.path.splitext(best_vid)[0] + os.path.splitext(sub_file)[1]
                    new_path = os.path.join(root, new_name)
                    try:
                        if os.path.exists(new_path) and new_path != sub_path:
                            os.remove(new_path)
                        if sub_path != new_path:
                            os.rename(sub_path, new_path)
                        if log: log(f'   ✏️  {sub_file} → {new_name}')
                        renamed += 1
                    except Exception as e:
                        if log: log(f'   ❌ خطأ تسمية: {e}')
                else:
                    if log: log(f'   ℹ️  {sub_file} — لم يُعثر على فيديو مناسب')

            total_renamed += renamed
            if renamed > 0:
                matched_videos = []
                for sub_file in extracted:
                    bv = find_best_video_for_subtitle(sub_file, video_files)
                    if bv and bv not in matched_videos:
                        matched_videos.append(bv)
                send_notification('archive_found', {
                    'file': archive_path,
                    'count': renamed,
                    'videos': matched_videos,
                })

            if progress_cb:
                progress_cb(archive_name, renamed)
    return total_renamed

# ─────────────────────────────────────────────
#  Chrome helpers
# ─────────────────────────────────────────────
def wait_cloudflare(driver, max_wait=20):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if any(kw in driver.title.lower() for kw in ('just a moment','cloudflare','attention')):
            time.sleep(2); continue
        src = driver.page_source[:500].lower()
        if 'challenge' in src or 'cf-browser-verification' in src:
            time.sleep(2); continue
        return True
    return False

def chrome_load(url, wait_css, timeout=30, log=None):
    if log: log(f'   ⏳ Chrome يفتح الصفحة...')
    driver = get_driver(log=log)
    if not driver:
        if log: log('   ❌ Chrome لم يستجب — تأكد من تشغيل البرنامج ببيئة بايثون المثبت بها المكتبات.')
        return ''
    try:
        driver.get(url)
    except Exception as ex:
        if log: log(f'   ❌ driver.get فشل: {str(ex)[:80]}')
        return ''
    cf_passed = wait_cloudflare(driver)
    if log: log(f'   {"✅ Cloudflare عدى" if cf_passed else "⚠️ Cloudflare timeout"}')
    try:
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1); driver.execute_script('window.scrollTo(0, 0);'); time.sleep(1)
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_css)))
        if log: log(f'   ✅ الصفحة محملة')
    except Exception as ex:
        if log: log(f'   ⚠️ انتهى الوقت أو العنصر مش موجود — نكمل بما هو متاح')
    src = driver.page_source
    if log: log(f'   📄 حجم الصفحة: {len(src)} حرف')
    return src

def chrome_get_subtitle_links(page_url, log):
    if log: log(f'   🌐 فتح: {page_url[:80]}')
    html = chrome_load(page_url, 'a[href^="/subtitle/"]', 35, log)
    if not html: return []
    soup = BeautifulSoup(html, 'html.parser')
    links = [{'href': a['href'].strip(),
              'release': a.get_text(strip=True) or a['href'].split('/')[-1]}
             for a in soup.find_all('a', href=re.compile(r'^/subtitle/'))]
    if log: log(f'   {"📋 وجد " + str(len(links)) + " ترجمة" if links else "⚠️ لا نتائج في هذا الرابط"}')
    return links

def chrome_get_download_url(sub_href, log):
    html = chrome_load(f'https://subsource.net{sub_href}',
                       'a[href*="api.subsource.net"][href*="/subtitle/download/"]', 35, log)
    if not html: return None
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=re.compile(r'api\.subsource\.net.*/subtitle/download/')):
        return a['href'].strip()
    for a in soup.find_all('a', href=True):
        if 'download' in a['href'].lower():
            return a['href'] if a['href'].startswith('http') else f'https://subsource.net{a["href"]}'
    return None

def chrome_download_zip(dl_url, sub_href, directory, log):
    driver = get_driver(log=log)
    if not driver: return []
    driver.set_script_timeout(40)
    js = """
    const url=arguments[0], ref=arguments[1], cb=arguments[2];
    fetch(url,{method:'GET',credentials:'include',headers:{'Referer':ref,'Origin':'https://subsource.net'}})
    .then(r=>{if(!r.ok){cb('ERR:'+r.status);return;}return r.arrayBuffer();})
    .then(buf=>{let b='';const u=new Uint8Array(buf);for(let i=0;i<u.byteLength;i++)b+=String.fromCharCode(u[i]);try{cb(btoa(b));}catch(e){cb('ERR:'+e);}})
    .catch(e=>cb('ERR:'+e));
    """
    try:
        result = driver.execute_async_script(js, dl_url, f'https://subsource.net{sub_href}')
    except Exception as ex:
        if log: log(f'   ❌ خطأ تحميل: {str(ex)[:50]}')
        return []
    if not result or str(result).startswith('ERR:'):
        if log: log(f'   ❌ فشل: {result}')
        return []
    try:
        archive_bytes = base64.b64decode(result)
        extracted = extract_archive_bytes(archive_bytes, directory, log)
        if not extracted and log: log('   ⚠️ لا ترجمات في الملف!')
        return extracted
    except Exception as ex:
        if log: log(f'   ❌ خطأ فك تشفير: {ex}')
    return []

def get_best_links(links, video_file, series_match, log, max_candidates=5):
    if not links: return []
    clean_video = get_clean_words(os.path.splitext(video_file)[0])
    candidates = []
    if series_match:
        s, e = series_match.groups()
        pattern = re.compile(rf'S{int(s):02d}E{int(e):02d}', re.IGNORECASE)
        for lnk in links:
            is_ar = '/arabic/' in lnk['href'] or 'arabic' in lnk['release'].lower()
            if is_ar and (pattern.search(lnk['release']) or pattern.search(lnk['href'])):
                candidates.append((lnk['href'], f"عربي مطابق: {lnk['release'][:70]}"))
        for lnk in links:
            if pattern.search(lnk['release']) or pattern.search(lnk['href']):
                candidates.append((lnk['href'], f"تطابق: {lnk['release'][:70]}"))
    else:
        for lnk in links:
            is_ar = '/arabic/' in lnk['href'] or 'arabic' in lnk['release'].lower()
            sim = len(clean_video & get_clean_words(lnk['release'])) / (
                  len(clean_video | get_clean_words(lnk['release'])) or 1)
            if is_ar and sim > 0.4:
                candidates.append((lnk['href'], f"عربي ({sim:.2f}): {lnk['release'][:70]}"))
        for lnk in links:
            if '/arabic/' in lnk['href'] or 'arabic' in lnk['release'].lower():
                candidates.append((lnk['href'], f"عربي: {lnk['release'][:70]}"))
    candidates.append((links[0]['href'], f"أول ترجمة: {links[0]['release'][:70]}"))
    seen = set(); final = []
    for h, r in candidates:
        if h not in seen:
            seen.add(h); final.append({'href': h, 'reason': r})
            if len(final) >= max_candidates: break
    return final

# ─────────────────────────────────────────────
#  Core Logic
# ─────────────────────────────────────────────
def do_rename(video_file, base_name, series_match, directory, log):
    count = 0
    for f in os.listdir(directory):
        if not f.lower().endswith(VALID_SUB_EXTS): continue
        should_rename = False
        if series_match:
            s, e = series_match.groups()
            if re.search(rf'S{s}E{e}', f, re.IGNORECASE): should_rename = True
        else:
            mn, yr = extract_movie_info(video_file)
            sn, sy = extract_movie_info(f)
            if mn and yr and sy == yr and sn:
                w1, w2 = get_clean_words(mn), get_clean_words(sn)
                if w1 and w2 and len(w1 & w2) / max(len(w1), len(w2)) >= 0.6:
                    should_rename = True
        if should_rename:
            new_f = f'{base_name}{os.path.splitext(f)[1]}'
            if f != new_f:
                try:
                    dest = os.path.join(directory, new_f)
                    if os.path.exists(dest): os.remove(dest)
                    os.rename(os.path.join(directory, f), dest)
                    count += 1
                    if log: log(f'✏️  تمت التسمية: {new_f}')
                except: pass
    return count

def has_existing_srt(video_file, directory):
    sm = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)
    if sm:
        s, e = sm.groups()
        return any(re.search(rf'S{s}E{e}', f, re.IGNORECASE)
                   for f in os.listdir(directory) if f.lower().endswith(VALID_SUB_EXTS))
    mn, yr = extract_movie_info(video_file)
    if mn and yr:
        for f in [x for x in os.listdir(directory) if x.lower().endswith(VALID_SUB_EXTS)]:
            sn, sy = extract_movie_info(f)
            if sy == yr and sn:
                w1, w2 = get_clean_words(mn), get_clean_words(sn)
                if w1 and w2 and len(w1 & w2) / max(len(w1), len(w2)) >= 0.6:
                    return True
    return False

def _try_download(season_url, search_url, video_file, series_match, directory, log, cancel_event):
    links = chrome_get_subtitle_links(season_url, log)
    if not links and not cancel_event.is_set():
        links = chrome_get_subtitle_links(search_url, log)
    if not links or cancel_event.is_set(): return 0
    if log: log(f'   📋 {len(links)} ترجمة متاحة')
    candidates = get_best_links(links, video_file, series_match, log, 5)
    for idx, cand in enumerate(candidates, 1):
        if cancel_event.is_set(): break
        if log: log(f"   محاولة {idx}/{len(candidates)} 🎯 {cand['reason']}")
        dl_url = chrome_get_download_url(cand['href'], log)
        if not dl_url or cancel_event.is_set(): continue
        extracted = chrome_download_zip(dl_url, cand['href'], directory, log)
        if extracted:
            if log: log(f'   ✅ نجاح! {", ".join(extracted)}')
            return len(extracted)
        elif idx < len(candidates):
            if log: log('   ⚠️ فشل، نجرب التالي...')
    return 0

def auto_download(season_url, search_url, video_file, series_match, directory, log, cancel_event, known_year=None):
    if not UC_AVAILABLE:
        return 0
    n = _try_download(season_url, search_url, video_file, series_match, directory, log, cancel_event)
    if n or cancel_event.is_set(): return n
    if not known_year and series_match:
        s_num = int(series_match.group(1))
        if s_num > 1: return 0
        raw = video_file[:series_match.start()]
        series_name = re.sub(r'[._-]', ' ', raw).strip()
        slug_base = build_slug(series_name)
        s_url = f'https://subsource.net/search?q={series_name.replace(" ","+")}'
        for yr in range(CURRENT_YEAR, CURRENT_YEAR - 6, -1):
            if cancel_event.is_set(): return 0
            if log: log(f'   🗓️  سنة {yr}...')
            n = _try_download(
                f'https://subsource.net/subtitles/{slug_base}-{yr}/season-{s_num}',
                s_url, video_file, series_match, directory, log, cancel_event)
            if n: return n
    return 0

def process_one_file(file_path, log, set_status, cancel_event, silent=False):
    directory    = os.path.dirname(file_path)
    video_file   = os.path.basename(file_path)
    base_name    = os.path.splitext(video_file)[0]
    series_match = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)

    if series_match:
        s_num = int(series_match.group(1))
        e_num = int(series_match.group(2))
        raw   = video_file[:series_match.start()]
        series_name = re.sub(r'[._-]', ' ', raw).strip()
        media_type = 'episode'
    else:
        mn, yr = extract_movie_info(video_file)
        series_name = None; s_num = None; e_num = None; media_type = 'movie'

    if has_existing_srt(video_file, directory):
        if log: log('✅ ترجمة موجودة مسبقاً — تسمية فقط')
        return do_rename(video_file, base_name, series_match, directory, log)

    season_url, search_url, name, season_num, year, sm = build_urls(video_file)
    if not season_url:
        if log: log('❌ تعذّر بناء الرابط')
        db_log(video_file, media_type, series_name, s_num, e_num, 'failed')
        return 0

    label = name + (f' — الموسم {season_num}' if season_num else f' ({year})' if year else '')
    if set_status: set_status(f'⏳ جاري التحميل:\n{label}')

    if silent:
        send_notification('found', {'name': label})

    if log: log(f'🔗 URL: {season_url}')
    n = auto_download(season_url, search_url, video_file, series_match, directory, log, cancel_event, year)
    if cancel_event.is_set(): return 0

    if n == 0:
        if log: log('⏰ لم نجد ترجمة')
        db_log(video_file, media_type, series_name, s_num, e_num, 'failed')
        if silent:
            send_notification('failed', {'name': label})
        return 0

    db_log(video_file, media_type, series_name, s_num, e_num, 'success')

    if silent:
        if media_type == 'episode':
            send_notification('done_episode', {
                'series': series_name, 'season': s_num, 'episode': e_num
            })
        else:
            mn, yr = extract_movie_info(video_file)
            send_notification('done_movie', {'name': mn or name, 'year': yr or year})

    renamed = do_rename(video_file, base_name, series_match, directory, log)
    return renamed if renamed > 0 else n

def run_all(paths_list, result_label, root_ref, log_func, set_status_func, cancel_event, silent=False):
    video_exts = VALID_VIDEO_EXTS
    video_files_paths = []
    for path in paths_list:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for f in files:
                    if f.lower().endswith(video_exts):
                        video_files_paths.append(os.path.join(root, f))
        elif os.path.isfile(path) and path.lower().endswith(video_exts):
            video_files_paths.append(path)

    if not video_files_paths:
        if result_label:
            result_label.configure(text='لا توجد ملفات فيديو')
        return

    if log_func: log_func(f'🎬 {len(video_files_paths)} ملف فيديو')
    total = 0
    for i, file_path in enumerate(video_files_paths, 1):
        if cancel_event.is_set(): break
        if log_func: log_func(f'\n── [{i}/{len(video_files_paths)}] {os.path.basename(file_path)}')
        total += process_one_file(file_path, log_func, set_status_func, cancel_event, silent)

    quit_driver()

    if cancel_event.is_set():
        if result_label: result_label.configure(text=f'توقف — {total} ملف')
    elif total > 0:
        if result_label: result_label.configure(text=f'✅ تم! {total} ملف')
        if silent and len(video_files_paths) > 1:
            send_notification('done_multi', {
                'count': total,
                'name': os.path.basename(os.path.dirname(video_files_paths[0]))
            })
    else:
        if result_label: result_label.configure(text='لم يُحمَّل أي شيء')

# ─────────────────────────────────────────────
#  Watchdog
# ─────────────────────────────────────────────
_watchdog_observer   = None
_watchdog_lock       = threading.Lock()
_watchdog_folder_ref = [None]
_pending_files       = {}
_heartbeat_thread    = None

class VideoHandler(FileSystemEventHandler):
    def _handle_path(self, path):
        if path in _pending_files: return
        if path.lower().endswith(VALID_VIDEO_EXTS):
            _pending_files[path] = time.time()
            threading.Thread(target=self._wait_and_process, args=(path,), daemon=True).start()

    def on_created(self, event):
        if event.is_directory:
            threading.Thread(target=self._scan_new_folder, args=(event.src_path,), daemon=True).start()
            return
        self._handle_path(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            threading.Thread(target=self._scan_new_folder, args=(event.dest_path,), daemon=True).start()
            return
        self._handle_path(event.dest_path)

    def _scan_new_folder(self, folder_path):
        time.sleep(2)
        if not os.path.isdir(folder_path): return
        for root, dirs, files in os.walk(folder_path):
            for f in files:
                self._handle_path(os.path.join(root, f))

    def _wait_and_process(self, path):
        time.sleep(3)
        prev_size = -1
        stable_count = 0
        for _ in range(120):
            try:
                size = os.path.getsize(path)
                if size > 0 and size == prev_size:
                    stable_count += 1
                    if stable_count >= 2:
                        break
                else:
                    stable_count = 0
                prev_size = size
            except:
                return
            time.sleep(2)
        if not os.path.exists(path): return
        logging.info(f'Watchdog processing: {path}')
        cancel_ev = threading.Event()
        run_all([path], None, None, None, None, cancel_ev, silent=True)

def start_watchdog(folder):
    global _watchdog_observer
    _watchdog_folder_ref[0] = folder
    with _watchdog_lock:
        if _watchdog_observer:
            try: _watchdog_observer.stop(); _watchdog_observer.join(2)
            except: pass
        if not WATCHDOG_AVAILABLE or not folder or not os.path.isdir(folder):
            return False
        _watchdog_observer = Observer()
        _watchdog_observer.schedule(VideoHandler(), folder, recursive=True)
        _watchdog_observer.start()
        logging.info(f'Watchdog started: {folder}')
        return True

def stop_watchdog():
    global _watchdog_observer
    _watchdog_folder_ref[0] = None
    with _watchdog_lock:
        if _watchdog_observer:
            try: _watchdog_observer.stop(); _watchdog_observer.join(2)
            except: pass
            _watchdog_observer = None

def _watchdog_heartbeat():
    while True:
        time.sleep(60)
        try:
            folder = _watchdog_folder_ref[0]
            if not folder: continue
            with _watchdog_lock:
                alive = _watchdog_observer and _watchdog_observer.is_alive()
            if not alive:
                logging.info('Watchdog died, restarting...')
                start_watchdog(folder)
        except Exception as e:
            logging.error(f'heartbeat error: {e}')

def start_heartbeat():
    global _heartbeat_thread
    if _heartbeat_thread and _heartbeat_thread.is_alive():
        return
    _heartbeat_thread = threading.Thread(target=_watchdog_heartbeat, daemon=True)
    _heartbeat_thread.start()

# ─────────────────────────────────────────────
#  System Tray
# ─────────────────────────────────────────────
_tray_icon       = None
_main_window_ref = None

def show_main_window():
    if _main_window_ref:
        try:
            _main_window_ref.deiconify()
            _main_window_ref.lift()
            _main_window_ref.focus_force()
        except: pass

def quit_app():
    stop_watchdog()
    quit_driver()
    if _tray_icon:
        try: _tray_icon.stop()
        except: pass
    if _main_window_ref:
        try: _main_window_ref.destroy()
        except: pass
    os._exit(0)

def run_tray():
    global _tray_icon
    if not TRAY_AVAILABLE: return
    img  = create_tray_image(64)
    menu = pystray.Menu(
        item('فتح Auto Subs', lambda icon, i: show_main_window(), default=True),
        item('إيقاف البرنامج', lambda icon, i: quit_app()),
    )
    _tray_icon = pystray.Icon(APP_NAME, img, 'Auto Subs', menu)
    _tray_icon.run()

# ─────────────────────────────────────────────
#  الواجهة الرئيسية
# ─────────────────────────────────────────────
def parse_dnd_paths(event_data):
    if not event_data: return []
    if '{' in event_data: return re.findall(r'\{([^{}]+)\}', event_data)
    return event_data.split()

class MainApp:
    def __init__(self):
        global _main_window_ref
        init_db()
        self.cfg          = load_config()
        self.cancel_event = threading.Event()

        if DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
            self.root.configure(bg='#121212')
        else:
            self.root = tk.Tk()
            self.root.configure(bg='#121212')

        _main_window_ref = self.root
        self.root.title("Auto Subs")
        self.root.resizable(False, False)

        w, h = 720, 700
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

        if TRAY_AVAILABLE:
            try:
                ico_path = save_icon()
                self.root.iconphoto(True, tk.PhotoImage(file=ico_path))
            except: pass

        self._build_ui()
        self._apply_initial_config()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        if TRAY_AVAILABLE:
            threading.Thread(target=run_tray, daemon=True).start()

        if self.cfg.get('auto_watch'):
            start_watchdog(self.cfg.get('watch_folder', ''))
        start_heartbeat()

        self.root.after(500, self.check_dependencies)

    def check_dependencies(self):
        if not UC_AVAILABLE:
            self.log("❌ خطأ بيئة التشغيل (Environment Error):")
            self.log(f"   السبب الفعلي: {UC_IMPORT_ERROR}")
            self.log("\n💡 الحل الصحيح لهذه المشكلة:")
            self.log("   أنت تقوم بتشغيل البرنامج من خلال بيئة بايثون افتراضية تختلف عن التي قمت بتثبيت المكتبات فيها.")
            self.log("   لحل المشكلة وتشغيل البرنامج بنجاح:")
            self.log("   1. افتح نافذة الـ CMD في مجلد السكريبت.")
            self.log("   2. اكتب الأمر التالي واضغط Enter:")
            self.log("      python auto_subs_v9.py")
            self.log("─────────────────────────────────────────────\n")

    def _on_close(self):
        self.root.withdraw()
        if TRAY_AVAILABLE:
            send_notification('found', {'name': 'Auto Subs يعمل في الخلفية'})

    def _build_ui(self):
        BG     = '#121212'
        CARD   = '#1e1e1e'
        ACCENT = '#4fa8ff'
        GREEN  = '#2ecc71'
        RED    = '#e74c3c'

        hdr = tk.Frame(self.root, bg='#0a0a0a'); hdr.pack(fill=tk.X)
        lf  = tk.Frame(hdr, bg='#0a0a0a'); lf.pack(side=tk.LEFT, padx=15, pady=10)
        tk.Label(lf, text='Auto Subs', font=('Segoe UI', 20, 'bold'),
                 bg='#0a0a0a', fg=ACCENT).pack(anchor='w')
        tk.Label(lf, text='تحميل ترجمات تلقائي • v9', font=('Segoe UI', 8),
                 bg='#0a0a0a', fg='#444').pack(anchor='w')

        tab_bar = tk.Frame(self.root, bg='#0d0d0d'); tab_bar.pack(fill=tk.X)
        self.tabs_content = {}
        self.tab_buttons  = {}
        tab_names = [('main','🎬 تحميل'), ('scan','🔎 فحص Downloads'), ('stats','📊 إحصائيات'), ('settings','⚙️ الإعدادات')]
        for tid, label in tab_names:
            btn = tk.Button(tab_bar, text=label, font=('Segoe UI', 10, 'bold'),
                            bg=ACCENT if tid=='main' else '#1a1a1a',
                            fg='white', relief='flat', padx=14, pady=8, cursor='hand2',
                            command=lambda t=tid: self._switch_tab(t))
            btn.pack(side=tk.LEFT, padx=2)
            self.tab_buttons[tid] = btn

        self.content_area = tk.Frame(self.root, bg=BG); self.content_area.pack(fill=tk.BOTH, expand=True)
        self._build_main_tab()
        self._build_scan_tab()
        self._build_stats_tab()
        self._build_settings_tab()
        self._switch_tab('main')

    def _switch_tab(self, tab_id):
        for f in self.tabs_content.values(): f.pack_forget()
        self.tabs_content[tab_id].pack(fill=tk.BOTH, expand=True)
        for tid, btn in self.tab_buttons.items():
            btn.configure(bg='#4fa8ff' if tid==tab_id else '#1a1a1a')
        if tab_id == 'stats': self._refresh_stats()

    def _build_main_tab(self):
        BG = '#121212'; ACCENT = '#4fa8ff'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['main'] = f

        self.result_label = tk.Label(f, text='بانتظار الملفات...', font=('Segoe UI', 13, 'bold'),
                                     bg=BG, fg='#555')
        self.result_label.pack(pady=(18, 6))

        bf = tk.Frame(f, bg=BG); bf.pack(pady=8)
        self.btn_folder = tk.Button(bf, text='📂 اختيار مجلد', height=2, width=16,
                                    bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                                    relief='flat', cursor='hand2', command=self.select_folder)
        self.btn_folder.pack(side=tk.LEFT, padx=5)
        self.btn_file = tk.Button(bf, text='🎥 اختيار ملف', height=2, width=16,
                                  bg='#27ae60', fg='white', font=('Segoe UI', 10, 'bold'),
                                  relief='flat', cursor='hand2', command=self.select_file)
        self.btn_file.pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(bf, text='⏹ إيقاف', height=2, width=10,
                                  bg='#c0392b', fg='white', font=('Segoe UI', 10, 'bold'),
                                  relief='flat', state='disabled', command=self.stop_process)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        drop_frame = tk.Frame(f, bg='#162333', relief='flat'); drop_frame.pack(fill=tk.X, padx=20, pady=6)
        tk.Label(drop_frame, text='📥 اسحب وأفلت الملفات أو المجلدات هنا',
                 font=('Segoe UI', 10), bg='#162333', fg='#4a90d9', pady=10).pack()
        if DND_AVAILABLE:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.drop_handler)

        log_frame = tk.Frame(f, bg=BG); log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        sb = tk.Scrollbar(log_frame); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_widget = tk.Text(log_frame, height=16, bg='#0a0a0a', fg='#aaa',
                                  font=('Consolas', 9), state='disabled', wrap='word',
                                  yscrollcommand=sb.set, relief='flat', bd=0)
        self.log_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.log_widget.yview)

        deps = (('DnD', DND_AVAILABLE), ('RAR', RAR_AVAILABLE), ('Tray', TRAY_AVAILABLE), ('Watch', WATCHDOG_AVAILABLE))
        status_text = '  '.join(f'{"✅" if ok else "❌"} {name}' for name, ok in deps)
        tk.Label(f, text=status_text, font=('Segoe UI', 7), bg=BG, fg='#333').pack(pady=(2, 6))

    def _build_scan_tab(self):
        BG = '#121212'; ACCENT = '#4fa8ff'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['scan'] = f

        tk.Label(f, text='🔎 فحص مجلد Downloads للأرشيفات',
                 font=('Segoe UI', 13, 'bold'), bg=BG, fg='white').pack(pady=(18,4))
        tk.Label(f, text='يبحث عن ملفات ZIP/RAR تحتوي على ترجمات، يفك ضغطها ويسميها بأسماء ملفات الفيديو',
                 font=('Segoe UI', 9), bg=BG, fg='#666', wraplength=600).pack(pady=(0,12))

        path_f = tk.Frame(f, bg='#1e1e1e'); path_f.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(path_f, text='المجلد:', font=('Segoe UI', 10), bg='#1e1e1e', fg='#aaa').pack(side=tk.LEFT, padx=10, pady=8)
        self.scan_entry = tk.Entry(path_f, font=('Segoe UI', 9), bg='#2a2a2a', fg='white',
                                   relief='flat', insertbackground='white')
        self.scan_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.scan_entry.insert(0, self.cfg.get('watch_folder', ''))
        tk.Button(path_f, text='...', bg=ACCENT, fg='white', relief='flat', cursor='hand2',
                  command=self._browse_scan_folder).pack(side=tk.LEFT, padx=(5, 10))

        self.scan_btn = tk.Button(f, text='▶ ابدأ الفحص', font=('Segoe UI', 11, 'bold'),
                                  bg='#27ae60', fg='white', relief='flat', cursor='hand2',
                                  width=20, pady=8, command=self._run_scan)
        self.scan_btn.pack(pady=10)

        self.scan_status = tk.Label(f, text='', font=('Segoe UI', 11, 'bold'), bg=BG, fg='#4fa8ff')
        self.scan_status.pack()

        log_f = tk.Frame(f, bg=BG); log_f.pack(fill=tk.BOTH, expand=True, padx=15, pady=8)
        sb2 = tk.Scrollbar(log_f); sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.scan_log = tk.Text(log_f, height=14, bg='#0a0a0a', fg='#aaa',
                                font=('Consolas', 9), state='disabled', wrap='word',
                                yscrollcommand=sb2.set, relief='flat', bd=0)
        self.scan_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.config(command=self.scan_log.yview)

    def _browse_scan_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.scan_entry.delete(0, tk.END)
            self.scan_entry.insert(0, d)

    def _run_scan(self):
        folder = self.scan_entry.get()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror('خطأ', 'المجلد غير موجود!')
            return
        self.scan_btn.configure(state='disabled')
        self.scan_status.configure(text='جاري الفحص...', fg='#f39c12')
        self.scan_log.configure(state='normal')
        self.scan_log.delete('1.0', tk.END)
        self.scan_log.configure(state='disabled')

        def _scan_log(msg):
            def _do():
                self.scan_log.configure(state='normal')
                self.scan_log.insert('end', msg + '\n')
                self.scan_log.see('end')
                self.scan_log.configure(state='disabled')
            self.root.after(0, _do)

        def _run():
            total = scan_downloads_for_archives(folder, log=_scan_log)
            def _done():
                self.scan_btn.configure(state='normal')
                if total > 0:
                    self.scan_status.configure(
                        text=f'✅ تم! {total} ترجمة تمت معالجتها', fg='#2ecc71')
                else:
                    self.scan_status.configure(text='لا توجد أرشيفات ترجمة في هذا المجلد', fg='#888')
            self.root.after(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _build_stats_tab(self):
        BG = '#121212'; CARD = '#1e1e1e'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['stats'] = f
        tk.Label(f, text='📊 إحصائيات', font=('Segoe UI', 14, 'bold'), bg=BG, fg='white').pack(pady=(20,10))
        cards_row = tk.Frame(f, bg=BG); cards_row.pack(padx=20, pady=5, fill=tk.X)
        self.stat_labels = {}
        for key, title, color in [
            ('movies',   '🎬 أفلام',       '#4fa8ff'),
            ('series',   '📺 مسلسلات',     '#9b59b6'),
            ('episodes', '📋 حلقات',       '#27ae60'),
            ('failed',   '❌ فشل',         '#e74c3c'),
        ]:
            card_f = tk.Frame(cards_row, bg=CARD, padx=10, pady=10)
            card_f.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
            tk.Label(card_f, text=title, font=('Segoe UI', 9), bg=CARD, fg='#777').pack()
            lbl = tk.Label(card_f, text='0', font=('Segoe UI', 22, 'bold'), bg=CARD, fg=color)
            lbl.pack(); self.stat_labels[key] = lbl

        month_f = tk.Frame(f, bg='#162333'); month_f.pack(fill=tk.X, padx=20, pady=8)
        tk.Label(month_f, text='هذا الشهر:', font=('Segoe UI', 10), bg='#162333', fg='#aaa').pack(side=tk.LEFT, padx=10, pady=8)
        self.month_label = tk.Label(month_f, text='0 ترجمة', font=('Segoe UI', 10, 'bold'), bg='#162333', fg='#4fa8ff')
        self.month_label.pack(side=tk.LEFT)

        top_f = tk.Frame(f, bg=CARD); top_f.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(top_f, text='⭐ أكثر مسلسل:', font=('Segoe UI', 10), bg=CARD, fg='#aaa').pack(side=tk.LEFT, padx=10, pady=8)
        self.top_series_label = tk.Label(top_f, text='—', font=('Segoe UI', 10, 'bold'), bg=CARD, fg='#f39c12')
        self.top_series_label.pack(side=tk.LEFT)

        tk.Label(f, text='⚠️ آخر الملفات التي فشلت:', font=('Segoe UI', 9), bg=BG, fg='#666').pack(anchor='w', padx=20, pady=(12,3))
        failed_f = tk.Frame(f, bg='#0a0a0a'); failed_f.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0,10))
        sb2 = tk.Scrollbar(failed_f); sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.failed_list = tk.Text(failed_f, height=7, bg='#0a0a0a', fg='#e74c3c',
                                   font=('Consolas', 8), state='disabled', wrap='word',
                                   yscrollcommand=sb2.set, relief='flat')
        self.failed_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.config(command=self.failed_list.yview)
        tk.Button(f, text='🔄 تحديث', font=('Segoe UI', 9), bg='#4fa8ff', fg='white',
                  relief='flat', cursor='hand2', command=self._refresh_stats).pack(pady=5)

    def _build_settings_tab(self):
        BG = '#121212'; CARD = '#1e1e1e'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['settings'] = f
        tk.Label(f, text='⚙️ الإعدادات', font=('Segoe UI', 14, 'bold'), bg=BG, fg='white').pack(pady=(20,15))

        watch_f = tk.Frame(f, bg=CARD); watch_f.pack(fill=tk.X, padx=20, pady=6)
        tk.Label(watch_f, text='📁 مجلد المراقبة التلقائية:', font=('Segoe UI', 10), bg=CARD, fg='white').pack(anchor='w', padx=12, pady=(10,2))
        row = tk.Frame(watch_f, bg=CARD); row.pack(fill=tk.X, padx=12, pady=(0,10))
        self.watch_entry = tk.Entry(row, font=('Segoe UI', 9), bg='#2a2a2a', fg='white',
                                    relief='flat', insertbackground='white')
        self.watch_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.watch_entry.insert(0, self.cfg.get('watch_folder', ''))
        tk.Button(row, text='...', bg='#4fa8ff', fg='white', relief='flat', cursor='hand2',
                  command=self._browse_watch_folder).pack(side=tk.LEFT, padx=(5,0))

        toggles_f = tk.Frame(f, bg=CARD); toggles_f.pack(fill=tk.X, padx=20, pady=6)
        self.auto_watch_var = tk.BooleanVar(value=self.cfg.get('auto_watch', True))
        self.startup_var    = tk.BooleanVar(value=self.cfg.get('start_with_windows', True))
        self.notify_var     = tk.BooleanVar(value=self.cfg.get('notifications', True))
        self.scan_arch_var  = tk.BooleanVar(value=self.cfg.get('scan_existing_archives', True))
        for var, text in [
            (self.auto_watch_var, '🔍 مراقبة المجلد تلقائياً'),
            (self.startup_var,    '🚀 بدء مع ويندوز (بدون كونسول)'),
            (self.notify_var,     '🔔 إشعارات تفصيلية عند اكتمال الترجمة'),
            (self.scan_arch_var,  '📦 فحص الأرشيفات الموجودة عند بدء المراقبة'),
        ]:
            row = tk.Frame(toggles_f, bg=CARD); row.pack(fill=tk.X, padx=12, pady=5)
            tk.Checkbutton(row, text=text, variable=var, bg=CARD, fg='white',
                           activebackground=CARD, activeforeground='white',
                           selectcolor='#4fa8ff', font=('Segoe UI', 10)).pack(anchor='w')

        ctx_f = tk.Frame(f, bg=CARD); ctx_f.pack(fill=tk.X, padx=20, pady=6)
        tk.Label(ctx_f, text='🖱️ قائمة الكليك يمين (يتطلب Admin):', font=('Segoe UI', 10), bg=CARD, fg='white').pack(anchor='w', padx=12, pady=(10,5))
        row2 = tk.Frame(ctx_f, bg=CARD); row2.pack(fill=tk.X, padx=12, pady=(0,10))
        tk.Button(row2, text='✅ تفعيل', bg='#27ae60', fg='white', relief='flat', cursor='hand2',
                  width=12, command=self._do_register_ctx).pack(side=tk.LEFT, padx=(0,8))
        tk.Button(row2, text='❌ إلغاء', bg='#e74c3c', fg='white', relief='flat', cursor='hand2',
                  width=12, command=lambda: (unregister_context_menu(), self._ctx_msg('تم إلغاء كليك يمين'))).pack(side=tk.LEFT)
        self.ctx_status = tk.Label(ctx_f, text='', font=('Segoe UI', 8), bg=CARD, fg='#27ae60')
        self.ctx_status.pack(anchor='w', padx=12, pady=(0,8))

        tk.Button(f, text='📄 إنشاء AutoSubs.vbs (تشغيل بدون كونسول)',
                  font=('Segoe UI', 9), bg='#8e44ad', fg='white', relief='flat', cursor='hand2',
                  command=self._create_vbs).pack(pady=(0,5))

        tk.Button(f, text='💾 حفظ الإعدادات', font=('Segoe UI', 11, 'bold'),
                  bg='#4fa8ff', fg='white', relief='flat', cursor='hand2',
                  command=self._save_settings).pack(pady=12)

    def _do_register_ctx(self):
        ok = register_context_menu()
        self.ctx_status.configure(text='✅ تم!' if ok else '❌ فشل (شغّل كـ Admin)')

    def _ctx_msg(self, msg):
        self.ctx_status.configure(text=msg)

    def _create_vbs(self):
        path = create_vbs_launcher()
        messagebox.showinfo('Auto Subs', f'تم إنشاء:\n{path}\n\nاستخدمه لتشغيل البرنامج بدون كونسول.')

    def _browse_watch_folder(self):
        d = filedialog.askdirectory()
        if d: self.watch_entry.delete(0, tk.END); self.watch_entry.insert(0, d)

    def _save_settings(self):
        self.cfg['watch_folder']             = self.watch_entry.get()
        self.cfg['auto_watch']               = self.auto_watch_var.get()
        self.cfg['start_with_windows']       = self.startup_var.get()
        self.cfg['notifications']            = self.notify_var.get()
        self.cfg['scan_existing_archives']   = self.scan_arch_var.get()
        save_config(self.cfg)
        set_startup(self.cfg['start_with_windows'])
        if self.cfg['auto_watch']:
            start_watchdog(self.cfg['watch_folder'])
        else:
            stop_watchdog()
        self.ctx_status.configure(text='✅ تم الحفظ!')

    def _apply_initial_config(self):
        if self.cfg.get('start_with_windows'):
            set_startup(True)

    def _refresh_stats(self):
        s = db_get_stats()
        for k in ('movies','series','episodes','failed'):
            self.stat_labels[k].configure(text=str(s[k]))
        self.month_label.configure(text=f"{s['this_month']} ترجمة")
        if s['top_series']:
            self.top_series_label.configure(text=f"{s['top_series'][0]} ({s['top_series'][1]} حلقة)")
        self.failed_list.configure(state='normal')
        self.failed_list.delete('1.0', tk.END)
        for fname, ts in s['failed_files']:
            self.failed_list.insert(tk.END, f'[{ts}] {fname}\n')
        self.failed_list.configure(state='disabled')

    # ─── Log ────────────────────────────────────
    def log(self, msg):
        def _do():
            self.log_widget.configure(state='normal')
            self.log_widget.insert('end', msg + '\n')
            self.log_widget.see('end')
            self.log_widget.configure(state='disabled')
        self.root.after(0, _do)

    def set_status(self, msg):
        self.root.after(0, lambda: self.result_label.configure(text=msg, fg='#4fa8ff'))

    # ─── Process ────────────────────────────────
    def start_process(self, paths_list):
        if not paths_list: return
        self.cancel_event.clear()
        self.result_label.configure(text='جاري الفحص...', fg='white')
        self.log_widget.configure(state='normal')
        self.log_widget.delete('1.0', 'end')
        self.log_widget.configure(state='disabled')
        self.btn_folder.configure(state='disabled')
        self.btn_file.configure(state='disabled')
        self.stop_btn.configure(state='normal')

        def _run():
            run_all(paths_list, self.result_label, self.root, self.log, self.set_status, self.cancel_event)
            self.root.after(0, lambda: (
                self.btn_folder.configure(state='normal'),
                self.btn_file.configure(state='normal'),
                self.stop_btn.configure(state='disabled'),
                self._refresh_stats() if hasattr(self, 'stat_labels') else None
            ))
        threading.Thread(target=_run, daemon=True).start()

    def select_folder(self):
        d = filedialog.askdirectory()
        if d: self.start_process([d])

    def select_file(self):
        f = filedialog.askopenfilename(filetypes=[("Video Files", "*.mkv *.mp4 *.avi")])
        if f: self.start_process([f])

    def drop_handler(self, event):
        paths = parse_dnd_paths(event.data)
        if paths: self.start_process(paths)

    def stop_process(self):
        self.cancel_event.set()
        self.result_label.configure(text='جاري الإيقاف...', fg='#f1c40f')
        self.stop_btn.configure(state='disabled')
        threading.Thread(target=quit_driver, daemon=True).start()

    def run(self):
        self.root.mainloop()

# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
if __name__ == '__main__':
    init_db()

    if len(sys.argv) >= 2 and sys.argv[1] not in ('--tray', '--scan'):
        file_arg  = sys.argv[1]
        cancel_ev = threading.Event()
        logging.info(f'Context menu: {file_arg}')
        send_notification('found', {'name': os.path.basename(file_arg)})
        run_all([file_arg], None, None, logging.info, None, cancel_ev, silent=True)
        sys.exit(0)

    if '--scan' in sys.argv:
        cfg = load_config()
        folder = cfg.get('watch_folder', '')
        logging.info(f'Scan mode: {folder}')
        scan_downloads_for_archives(folder, log=logging.info)
        sys.exit(0)

    app = MainApp()

    if '--tray' in sys.argv:
        app.root.withdraw()
        cfg = load_config()
        if cfg.get('scan_existing_archives') and cfg.get('auto_watch'):
            folder = cfg.get('watch_folder', '')
            if folder:
                threading.Thread(
                    target=scan_downloads_for_archives,
                    args=(folder,),
                    kwargs={'log': logging.info},
                    daemon=True
                ).start()
    elif len(sys.argv) > 1:
        app.root.after(300, lambda: app.start_process([sys.argv[1]]))

    app.run()