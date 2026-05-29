
# ─────────────────────────────────────────────
#  Auto Subs — v10  (Optimized, Folder-Icon & Fixed Syntax)
# ─────────────────────────────────────────────

import os, re, sys, zipfile, shutil, time, io, threading, base64, json, sqlite3, logging
import multiprocessing
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime
import subprocess
import webbrowser
import urllib.parse

# ── إخفاء نافذة CMD عند تشغيل subprocess على ويندوز ──
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

# ─────────────────────────────────────────────
#  تثبيت مجلد العمل الحالي (CWD) لمنع مشاكل صلاحيات ويندوز عند الإقلاع التلقائي
# ─────────────────────────────────────────────
try:
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
except Exception:
    pass

# ─────────────────────────────────────────────
#  إصلاح قنوات المخرجات لبيئة الـ EXE صامت الكونسول (--noconsole)
# ─────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')
        if sys.stdin is None:
            sys.stdin = open(os.devnull, 'r')
    except Exception:
        pass

# ─────────────────────────────────────────────
#  إخفاء الكونسول في ويندوز فوراً
# ─────────────────────────────────────────────
if sys.platform == "win32":
    try:
        import ctypes
        if not getattr(sys, 'frozen', False):
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from deep_translator import GoogleTranslator
    GOOGLE_TRANSLATE_AVAILABLE = True
except ImportError:
    GOOGLE_TRANSLATE_AVAILABLE = False

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    STATIC_FFMPEG_AVAILABLE = True
except ImportError:
    STATIC_FFMPEG_AVAILABLE = False

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

UC_AVAILABLE = False
UC_IMPORT_ERROR = None
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
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
    from PIL import Image, ImageDraw, ImageFont, ImageTk
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
#  المسارات والمتغيرات العامة
# ─────────────────────────────────────────────
APP_NAME  = 'AutoSubs'
APP_DIR   = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), APP_NAME)
DB_PATH   = os.path.join(APP_DIR, 'stats.db')
CFG_PATH  = os.path.join(APP_DIR, 'config.json')
LOG_PATH  = os.path.join(APP_DIR, 'app.log')
ICON_PATH = os.path.join(APP_DIR, 'icon.png')
os.makedirs(APP_DIR, exist_ok=True)

_app_instance = None
_active_jobs  = {}
_active_jobs_lock = threading.Lock()

# نظام حماية ضد التكرار والتداخل لمراقبة المجلدات والأيقونات
_processed_dirs_cache = {}
_processed_dirs_lock = threading.Lock()
_ACTIVE_PICKERS = set()
_ACTIVE_PICKERS_LOCK = threading.Lock()

# ثوابت نظام التشغيل ويندوز لتحديث الأيقونات
SHCNE_UPDATEDIR = 0x00001000
SHCNF_PATHW     = 0x0005

# ─────────────────────────────────────────────
#  Queue System — حد أقصى لعمليات Chrome المتزامنة
# ─────────────────────────────────────────────
import queue as _queue_module

_subtitle_queue     = _queue_module.Queue()
_queue_worker_count = 0
_queue_lock         = threading.Lock()
MAX_CONCURRENT_JOBS = 2   # حد أقصى: شغلتين Chrome في نفس الوقت

def _queue_worker():
    """Worker thread يأخذ شغل من الـ queue واحد واحد"""
    global _queue_worker_count
    try:
        while True:
            try:
                task = _subtitle_queue.get(timeout=30)
                if task is None:          # poison pill للإيقاف
                    break
                func, args, kwargs = task
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logging.error(f'queue_worker: task error: {e}')
                finally:
                    _subtitle_queue.task_done()
            except _queue_module.Empty:
                break   # انتهى الشغل — نخلّي الـ worker يموت لطبيعي
    finally:
        with _queue_lock:
            _queue_worker_count -= 1
        logging.info(f'queue: worker exited. active workers={_queue_worker_count}')

def _ensure_queue_workers():
    """يتأكد إن في workers شغالين — يشغّل واحد جديد لو محتاج"""
    global _queue_worker_count
    with _queue_lock:
        if _queue_worker_count < MAX_CONCURRENT_JOBS:
            _queue_worker_count += 1
            t = threading.Thread(target=_queue_worker, daemon=True)
            t.start()
            logging.info(f'queue: started worker #{_queue_worker_count}')

def enqueue_subtitle_job(func, *args, **kwargs):
    """يضيف شغلة لـ queue الترجمة ويتأكد إن في workers"""
    _subtitle_queue.put((func, args, kwargs))
    _ensure_queue_workers()
    logging.info(f'queue: job enqueued. queue size={_subtitle_queue.qsize()}')

# ─────────────────────────────────────────────
#  uTorrent Web API — بسيطة وموثوقة
# ─────────────────────────────────────────────
def ut_get_session(cfg=None):
    """يرجع (session, token, host) أو (None, None, None) لو فشل الاتصال"""
    if cfg is None:
        cfg = load_config()
    host = cfg.get('utorrent_host', 'http://localhost:8080/gui/').rstrip('/')
    user = cfg.get('utorrent_user', 'admin')
    pwd  = cfg.get('utorrent_pass', 'admin')
    session = requests.Session()
    session.auth = (user, pwd)
    try:
        r = session.get(f'{host}/token.html', timeout=5)
        m = re.search(r"<div id=['\"]token['\"][^>]*>([^<]+)</div>", r.text)
        if m:
            return session, m.group(1).strip(), host
        logging.warning('uTorrent: token not found — check Web UI settings')
    except Exception as e:
        logging.warning(f'ut_get_session: {e}')
    return None, None, None


def ut_list_torrents(session, token, host):
    """يرجع list من التورنتات [{hash, name, progress, save_path}]"""
    try:
        r = session.get(f'{host}/?token={token}&list=1', timeout=8)
        result = []
        for t in r.json().get('torrents', []):
            result.append({
                'hash':      t[0],
                'name':      t[2],
                'progress':  t[4],   # 1000 = 100%
                'save_path': t[26] if len(t) > 26 else '',
            })
        return result
    except Exception as e:
        logging.warning(f'ut_list_torrents: {e}')
        return []


def ut_remove_torrent(session, token, host, torrent_hash):
    """يمسح التورنت من القائمة (بدون حذف الملفات من القرص)"""
    try:
        session.get(f'{host}/?token={token}&action=remove&hash={torrent_hash}', timeout=5)
        logging.info(f'uTorrent: removed torrent {torrent_hash[:8]}...')
    except Exception as e:
        logging.warning(f'ut_remove_torrent: {e}')


def ut_test_connection(host=None, user=None, pwd=None):
    """يختبر الاتصال بـ uTorrent — يرجع True لو ناجح"""
    cfg = load_config()
    tmp = {
        'utorrent_host': host or cfg.get('utorrent_host', 'http://localhost:8080/gui/'),
        'utorrent_user': user or cfg.get('utorrent_user', 'admin'),
        'utorrent_pass': pwd  or cfg.get('utorrent_pass', ''),
    }
    s, t, h = ut_get_session(tmp)
    return s is not None


# ─────────────────────────────────────────────
#  uTorrent Monitor — مراقبة اكتمال التحميل والتنظيف
# ─────────────────────────────────────────────
_ut_monitor_running = False
_ut_seen_complete   = set()   # hashes التورنتات المكتملة المعالجة بالفعل


def rename_path_cleanly(path):
    """
    تقوم بتنظيف أسماء المجلدات فقط وتتجنب تغيير أسماء ملفات الفيديو نهائياً.
    تزيل الكلمات التقنية والزيادات مع الحفاظ على السنة في الأفلام.
    """
    if not os.path.exists(path):
        return path

    # ── قصر عملية إعادة التسمية على المجلدات فقط لحماية ملفات الفيديو ──
    if not os.path.isdir(path):
        return path

    folder_path = os.path.dirname(path)
    full_name = os.path.basename(path)
    name_part = full_name

    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', name_part)
    season_match = re.search(r'\b[sS](\d{2})(?:[eE]\d{2})?\b', name_part)
    season_word_match = re.search(r'\bSEASON[\s._-]*\d+\b', name_part, re.IGNORECASE)
    tech_match = re.search(r'\b(720p|1080p|2160p|480p|WEBRip|WEB-DL|BluRay|x264|x265|HEVC|10bit|2CH|PSA|COMPLETE|REPACK|REMUX|HDR|SDR|DV|AMZN|NF|DSNP)\b', name_part, re.IGNORECASE)

    cut_index = len(name_part)
    year_found = ""

    if year_match:
        cut_index = min(cut_index, year_match.start())
        year_found = year_match.group(0)

    if season_word_match:
        cut_index = min(cut_index, season_word_match.start())

    if season_match:
        cut_index = min(cut_index, season_match.start())

    if tech_match:
        cut_index = min(cut_index, tech_match.start())

    if cut_index < len(name_part):
        title_raw = name_part[:cut_index]
    else:
        title_raw = name_part

    title_raw = title_raw.replace("'", "").replace("’", "")
    clean_title = re.sub(r'[^a-zA-Z0-9]+', ' ', title_raw).strip()
    clean_title = clean_title.title()

    if year_found:
        new_name = f"{clean_title} ({year_found})"
    else:
        new_name = clean_title

    new_full_path = os.path.join(folder_path, new_name)

    try:
        if path != new_full_path:
            if not os.path.exists(new_full_path):
                os.rename(path, new_full_path)
                logging.info(f"Renamed on disk: {full_name} -> {new_name}")
                return new_full_path
    except Exception as e:
        logging.error(f"Error Renaming: {e}")

    return path


def _handle_completed_torrent(torrent, session, token, host):
    """
    عند اكتمال تحميل تورنت:
      1. ينظف اسم المجلد الناتج فقط ويزيل الزوائد التقنية.
      2. يبحث عن ملفات الفيديو المرتبطة به.
      3. يجلب الترجمة (بدون نقل — uTorrent لسه فاتح الملف).
      4. يمسح التورنت وينتظر uTorrent يسيب الملف.
      5. ينقل الحلقة + الترجمة لفولدر المسلسل.
    """
    name      = torrent['name']
    save_path = torrent['save_path']
    logging.info(f'uTorrent: handling completed torrent: "{name}"')

    # تحديد المسار الفعلي للملف أو المجلد
    target_path = os.path.join(save_path, name) if (save_path and name and os.path.exists(os.path.join(save_path, name))) else save_path

    # ── تنظيف اسم المجلد على القرص فوراً (الملفات الفردية لن يتم تغيير أسمائها) ──
    cleaned_target_path = target_path
    if target_path and os.path.exists(target_path):
        cleaned_target_path = rename_path_cleanly(target_path)

    # ── البحث عن ملفات الفيديو داخل المجلد الذي تم تنظيفه ──
    video_files  = []
    cfg          = get_cached_config()
    watch_folder = cfg.get('watch_folder', '')
    excluded     = {'$recycle.bin', 'system volume information', 'node_modules', '.git', 'appdata'}

    search_roots = []
    if cleaned_target_path and os.path.exists(cleaned_target_path):
        search_roots.append(cleaned_target_path)
    elif watch_folder and os.path.isdir(watch_folder):
        search_roots.append(watch_folder)

    for root in search_roots:
        if os.path.isdir(root):
            for r, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d.lower() not in excluded]
                for f in files:
                    if f.lower().endswith(VALID_VIDEO_EXTS):
                        fpath = os.path.join(r, f)
                        if fpath not in video_files:
                            video_files.append(fpath)
        elif os.path.isfile(root) and root.lower().endswith(VALID_VIDEO_EXTS):
            if root not in video_files:
                video_files.append(root)

    if not video_files:
        logging.warning(f'uTorrent: no video files found for "{name}"')
        return

    # ── الخطوة 1: جيب الترجمة بس — من غير نقل (uTorrent لسه فاتح الملف) (مع skip_icon=True لمنع تكرار الأيقونة) ──
    logging.info(f'uTorrent: found {len(video_files)} video(s) — fetching subtitles (no move yet)...')
    cancel_ev = threading.Event()
    try:
        run_all(video_files, None, None, logging.info, None, cancel_ev, silent=True, allow_move=False, skip_icon=True)
    except Exception as e:
        logging.error(f'uTorrent run_all error: {e}')

    # ── الخطوة 2: امسح التورنت وانتظر uTorrent يسيب الملف ──
    if cfg.get('utorrent_delete_torrent', True):
        ut_remove_torrent(session, token, host, torrent['hash'])
        logging.info('uTorrent: torrent removed — waiting for file release...')
        time.sleep(4)   # وقت كافي لـ uTorrent يغلق الملف

    # ── الخطوة 3: دلوقتي انقل الحلقة + الترجمة — التورنت اتمسح والملف حر ──
    logging.info('uTorrent: moving episode(s) + subtitle(s) to series folder...')
    seen_picker_folders = set()
    for video_path in video_files:
        if not os.path.isfile(video_path):
            logging.warning(f'uTorrent: video not found after torrent removal: {os.path.basename(video_path)}')
            continue
        try:
            final_folder = None

            # أولاً: جرب ينقل لفولدر موجود
            moved = move_to_series_folder(video_path, logging.info)
            if moved:
                logging.info(f'uTorrent: moved to existing folder "{os.path.basename(moved)}"')
                final_folder = moved
            else:
                # ثانياً: لو E01 — أنشئ فولدر جديد أو استخدم فولدر التورنت
                new_folder = maybe_create_series_folder(video_path, logging.info)
                if new_folder:
                    logging.info(f'uTorrent: series folder ready "{os.path.basename(new_folder)}"')
                    final_folder = new_folder

            # افتح icon picker بعد مسح التورنت — الاسم نظيف هنا
            picker_folder = final_folder or (cleaned_target_path if os.path.isdir(cleaned_target_path) else None)
            if picker_folder:
                if picker_folder.lower() not in seen_picker_folders:
                    seen_picker_folders.add(picker_folder.lower())
                    media_type = "episode" if re.search(r'S\d+E\d+', os.path.basename(video_path), re.IGNORECASE) else "movie"
                    threading.Thread(target=async_setup_folder_icon, args=(picker_folder, media_type, logging.info), daemon=True).start()

        except Exception as e:
            logging.error(f'uTorrent move error for {os.path.basename(video_path)}: {e}')


def _utorrent_monitor_loop():
    """Thread يشتغل في الخلفية ويتحقق من uTorrent كل 30 ثانية"""
    global _ut_seen_complete
    POLL_SECS = 30
    logging.info('uTorrent monitor: loop started')
    while _ut_monitor_running:
        time.sleep(POLL_SECS)
        try:
            cfg = get_cached_config()
            if not cfg.get('utorrent_enabled', False):
                continue

            session, token, host = ut_get_session(cfg)
            if not session:
                continue

            torrents = ut_list_torrents(session, token, host)

            # نظّف الـ seen set من التورنتات اللي اتحذفت فعلاً
            active_hashes = {t['hash'] for t in torrents}
            _ut_seen_complete &= active_hashes

            for t in torrents:
                if t['progress'] < 1000:
                    continue
                if t['hash'] in _ut_seen_complete:
                    continue
                # تورنت جديد اكتمل!
                _ut_seen_complete.add(t['hash'])
                logging.info(f'uTorrent monitor: NEW complete → "{t["name"]}"')
                threading.Thread(
                    target=_handle_completed_torrent,
                    args=(t, session, token, host),
                    daemon=True
                ).start()

        except Exception as e:
            logging.error(f'_utorrent_monitor_loop: {e}')


def start_utorrent_monitor():
    """يشغّل thread مراقبة uTorrent في الخلفية لو مش شغّال"""
    global _ut_monitor_running
    if _ut_monitor_running:
        return
    _ut_monitor_running = True
    threading.Thread(target=_utorrent_monitor_loop, daemon=True).start()
    logging.info('uTorrent monitor started')


def stop_utorrent_monitor():
    global _ut_monitor_running
    _ut_monitor_running = False

def _setup_logging():
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

_setup_logging()

# ─────────────────────────────────────────────
#  قاعدة البيانات
# ─────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH, timeout=15.0)
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

# ── persistent connection للكتابة السريعة ──
_db_write_con   = None
_db_write_lock  = threading.Lock()

def _get_db_con():
    global _db_write_con
    if _db_write_con is None:
        _db_write_con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
    return _db_write_con

def db_log(filename, media_type, series_name=None, season=None, episode=None, status='success'):
    try:
        with _db_write_lock:
            con = _get_db_con()
            con.execute('''INSERT INTO downloads
                (filename,media_type,series_name,season,episode,status,timestamp)
                VALUES (?,?,?,?,?,?,?)''',
                (filename, media_type, series_name, season, episode, status,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            con.commit()
    except Exception as e:
        logging.error(f'db_log: {e}')
        # إعادة فتح الـ connection لو فيه مشكلة
        global _db_write_con
        try:
            if _db_write_con: _db_write_con.close()
        except Exception: pass
        _db_write_con = None

def db_get_stats():
    try:
        con = sqlite3.connect(DB_PATH, timeout=15.0)
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
    'utorrent_enabled':  False,
    'utorrent_host':     'http://127.0.0.1:8080',
    'utorrent_user':     'admin',
    'utorrent_pass':     '',
    'utorrent_delete_torrent': True,
    'auto_translate_fallback': True,   # ترجمة تلقائية بـ Google Translate لو مفيش ترجمة عربية
    'auto_translate_silent':  False,   # True = ترجم بدون سؤال حتى في الـ tray/watchdog
}

def db_clear_all():
    try:
        with _db_write_lock:
            con = _get_db_con()
            con.execute('DELETE FROM downloads')
            con.commit()
        logging.info('DB cleared by user')
        return True
    except Exception as e:
        logging.error(f'db_clear_all: {e}')
        return False

def load_config():
    try:
        if os.path.exists(CFG_PATH):
            with open(CFG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg: cfg[k] = v
            return cfg
    except Exception as e:
        logging.warning(f'load_config: {e} — using defaults')
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    """يحفظ الـ config بأمان — كتابة في ملف مؤقت ثم rename لحماية من انقطاع الكهرباء"""
    tmp_path = CFG_PATH + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        if os.path.exists(CFG_PATH):
            os.replace(tmp_path, CFG_PATH)  # atomic على ويندوز ولينكس
        else:
            os.rename(tmp_path, CFG_PATH)
    except Exception as e:
        logging.error(f'save_config: {e}')
        try:
            if os.path.exists(tmp_path): os.remove(tmp_path)
        except Exception:
            pass
    # نفرّغ الـ cache عشان send_notification تقرأ الجديد
    global _cached_cfg, _cached_cfg_mtime
    _cached_cfg = dict(cfg)
    _cached_cfg_mtime = os.path.getmtime(CFG_PATH) if os.path.exists(CFG_PATH) else 0

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
    cfg = get_cached_config()
    if not cfg.get('notifications', True):
        return

    ALLOWED = {'done_movie', 'done_episode', 'done_multi', 'archive_found', 'failed', 'found'}
    if event_type not in ALLOWED:
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
            except Exception as e:
                logging.debug(f'unregister_context_menu inner: {e}')
    except Exception as e:
        logging.error(f'unregister_context_menu: {e}')

# ─────────────────────────────────────────────
#  إدارة عمليات Chrome والمتصفحات الخاملة
# ─────────────────────────────────────────────
_driver             = None
_driver_lock        = threading.Lock()
_driver_last_used   = 0
_driver_crash_count = 0          # عدد مرات الـ crash لتجنب حلقة لا نهائية
DRIVER_IDLE_TIMEOUT  = 5 * 60
DRIVER_MAX_CRASHES   = 3         # بعد 3 crashes متتالية، ما نجرّبش تاني في نفس الجلسة

def kill_our_chrome_processes():
    """
    تغلق فقط متصفحات Chrome والـ Drivers المرتبطة بمجلد الـ Profile الخاص ببرنامجنا
    لمنع حدوث قفل للمجلد والملفات، مع ترك متصفح المستخدم الشخصي يعمل بأمان.
    """
    if sys.platform != 'win32': return
    try:
        cmd = 'wmic process where "name=\'chrome.exe\' and CommandLine like \'%chrome_profile%\'" call terminate'
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def kill_orphaned_chromes():
    if sys.platform == "win32":
        try:
            subprocess.run("taskkill /f /im chromedriver.exe", shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            kill_our_chrome_processes()
        except Exception as e:
            logging.debug(f'kill_orphaned_chromes: {e}')

def _get_chrome_version():
    try:
        import undetected_chromedriver as uc
        chrome_path = uc.util.find_chrome_executable()
        if chrome_path and os.path.exists(chrome_path):
            chrome_dir = os.path.dirname(chrome_path)
            for entry in os.listdir(chrome_dir):
                if re.match(r'^\d+\.\d+\.\d+', entry):
                    major_ver = entry.split('.')[0]
                    logging.info(f"Chrome Disk Version Detected: {major_ver}")
                    return int(major_ver)
    except Exception as e:
        logging.error(f"Failed to detect Chrome version from disk: {e}")

    try:
        import winreg
        for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for key_path in [
                r'SOFTWARE\Google\Chrome\BLBeacon',
                r'SOFTWARE\Wow6432Node\Google\Chrome\BLBeacon',
            ]:
                try:
                    key = winreg.OpenKey(root, key_path)
                    ver, _ = winreg.QueryValueEx(key, 'version')
                    winreg.CloseKey(key)
                    return int(ver.split('.')[0])
                except Exception:
                    pass
    except Exception as e:
        logging.debug(f'_get_chrome_version registry: {e}')

    try:
        import subprocess
        for path in [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            os.path.join(os.environ.get('LOCALAPPDATA', ''), r'Google\Chrome\Application\chrome.exe')
        ]:
            if os.path.exists(path):
                out = subprocess.check_output(
                    f'"{path}" --version', shell=True,
                    stderr=subprocess.DEVNULL, timeout=5
                ).decode()
                ver = re.search(r'(\d+)\.', out)
                if ver: return int(ver.group(1))
    except Exception as e:
        logging.debug(f'_get_chrome_version subprocess: {e}')
    return None

def _hide_chrome_window(driver_pid=None):
    if sys.platform != 'win32': return
    if driver_pid is None: return
    try:
        import ctypes
        import ctypes.wintypes
        time.sleep(0.5)

        try:
            result = subprocess.check_output(
                f'wmic process where "ParentProcessId={driver_pid}" get ProcessId',
                shell=True, stderr=subprocess.DEVNULL, timeout=5
            ).decode()
            child_pids = {int(l.strip()) for l in result.splitlines() if l.strip().isdigit()}
        except Exception:
            child_pids = set()

        target_pids = child_pids | {driver_pid}

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        def _callback(hwnd, lParam):
            try:
                pid = ctypes.wintypes.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in target_pids:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)
            except Exception:
                pass
            return True

        ctypes.windll.user32.EnumWindows(EnumWindowsProc(_callback), 0)
    except Exception:
        pass

def auto_log_letterboxd(title, year):
    """تقوم بفتح صفحة بحث الفيلم داخل Letterboxd مباشرة في متصفح المستخدم الافتراضي الشخصي."""
    try:
        query = f"{title} {year}"
        encoded_query = urllib.parse.quote_plus(query)
        # توجيه المستخدم مباشرة لصفحة نتائج الأفلام في Letterboxd
        url = f"https://letterboxd.com/search/films/{encoded_query}/"
        
        logging.info(f"Letterboxd: Opening search for '{query}' in user's default browser.")
        webbrowser.open(url)
    except Exception as e:
        logging.error(f"auto_log_letterboxd error: {e}")

def get_driver(log=None):
    global _driver, _driver_last_used, _driver_crash_count

    # ── فحص سريع بدون lock لو Driver شغال بالفعل ──────────────────
    if _driver is not None:
        try:
            _ = _driver.title
            _driver_last_used = time.time()
            return _driver
        except Exception:
            logging.warning('get_driver: driver became unresponsive, resetting.')
            _driver = None

    if not UC_AVAILABLE:
        if log: log(f'   ❌ مكتبة Chrome غير متاحة: {UC_IMPORT_ERROR}')
        return None

    # ── حماية من حلقة crash لا نهائية ──────────────────────────────
    if _driver_crash_count >= DRIVER_MAX_CRASHES:
        if log: log(f'   ❌ Chrome فشل {DRIVER_MAX_CRASHES} مرات متتالية — يُعاد التعيين بعد إعادة تشغيل البرنامج.')
        logging.error('get_driver: max crash count reached, refusing to restart Chrome.')
        return None

    # ── lock مع timeout آمن ─────────────────────────────────────────
    acquired = _driver_lock.acquire(timeout=90)
    if not acquired:
        # لو الـ lock ما اتحررش في 90 ثانية → crash مؤكد
        logging.error('get_driver: lock timeout after 90s — forcing driver reset.')
        if log: log('   ⚠️ Chrome تعلق — يتم إعادة التهيئة...')
        # نعيد تعيين الـ driver بالقوة
        try:
            if _driver:
                _driver.quit()
        except Exception:
            pass
        _driver = None
        kill_our_chrome_processes()
        # نحاول نحصل على الـ lock بعد التنظيف
        acquired = _driver_lock.acquire(timeout=30)
        if not acquired:
            if log: log('   ❌ فشل تماماً — أعد تشغيل البرنامج.')
            return None

    try:
        # ── فحص تاني بعد حصولنا على الـ lock (قد يكون thread تاني حضّره) ──
        if _driver is not None:
            try:
                _ = _driver.title
                _driver_last_used = time.time()
                return _driver
            except Exception:
                _driver = None

        if log: log('   ⏳ جاري تهيئة Chrome...')
        kill_orphaned_chromes()

        # ── ChromeDriver Cache — نتحقق من النسخة المحفوظة قبل تنزيل جديدة ──
        _driver_cache_file = os.path.join(APP_DIR, 'chromedriver_cache.json')
        driver_path = None
        current_chrome_ver = _get_chrome_version()

        try:
            if os.path.exists(_driver_cache_file):
                with open(_driver_cache_file, 'r') as _cf:
                    _cache_data = json.load(_cf)
                cached_path = _cache_data.get('path', '')
                cached_ver  = _cache_data.get('chrome_ver')
                if (os.path.exists(cached_path) and
                        cached_ver == current_chrome_ver):
                    driver_path = cached_path
                    if log: log(f'   ✅ ChromeDriver من الـ cache: {cached_path}')
        except Exception as _ce:
            logging.debug(f'get_driver: cache read error: {_ce}')

        if not driver_path:
            try:
                driver_path = ChromeDriverManager().install()
                if log: log(f'   🔍 ChromeDriver جديد: {driver_path}')
                # حفظ المسار في الـ cache
                try:
                    with open(_driver_cache_file, 'w') as _cf:
                        json.dump({'path': driver_path, 'chrome_ver': current_chrome_ver}, _cf)
                except Exception: pass
            except Exception as ex:
                if log: log(f'   ❌ فشل تحميل ChromeDriver: {ex}')
                logging.error(f'get_driver: ChromeDriverManager failed: {ex}')
                _driver_crash_count += 1
                return None

        def get_fresh_options():
            opts = uc.ChromeOptions()
            chrome_profile_dir = os.path.join(APP_DIR, 'chrome_profile')
            os.makedirs(chrome_profile_dir, exist_ok=True)
            opts.add_argument(f'--user-data-dir={chrome_profile_dir}')
            opts.add_argument('--window-position=-32000,-32000')
            opts.add_argument('--window-size=1280,800')
            opts.add_argument('--lang=en-US')
            opts.add_argument('--no-sandbox')
            opts.add_argument('--disable-dev-shm-usage')
            opts.add_argument('--disable-gpu')
            opts.add_argument('--no-first-run')
            opts.add_argument('--no-default-browser-check')
            opts.add_argument('--disable-search-engine-choice-screen')
            opts.add_argument('--disable-blink-features=AutomationControlled')
            return opts

        attempts = [
            ('with_path', {'options': get_fresh_options(), 'driver_executable_path': driver_path, 'use_subprocess': True}),
            ('standard',  {'options': get_fresh_options(), 'use_subprocess': True}),
        ]

        for name, kwargs in attempts:
            try:
                if log: log(f'   🔄 محاولة {name}...')
                _driver = uc.Chrome(**kwargs)
                _driver.set_page_load_timeout(40)
                try:
                    _driver_pid = _driver.service.process.pid
                except Exception:
                    _driver_pid = None
                _hide_chrome_window(driver_pid=_driver_pid)
                _driver_last_used = time.time()
                _driver_crash_count = 0      # نجح → نصفّر عداد الـ crash
                _start_driver_idle_watcher()
                if log: log('   ✅ Chrome يعمل.')
                return _driver
            except Exception as ex:
                if log: log(f'   ⚠️ فشلت ({name}): {str(ex)[:120]}')
                logging.error(f'get_driver ({name}): {ex}')
                _driver = None

        _driver_crash_count += 1
        if log: log(f'   ❌ فشلت جميع محاولات تشغيل Chrome. (محاولة {_driver_crash_count}/{DRIVER_MAX_CRASHES})')
        logging.error(f'get_driver: all attempts failed. crash_count={_driver_crash_count}')
        return None

    finally:
        # ── الـ lock دايماً بيتحرر حتى لو في exception ─────────────
        try:
            _driver_lock.release()
        except RuntimeError:
            pass  # لو اتحرر بالفعل

def _get_driver(log=None):
    return get_driver(log)

def quit_driver():
    global _driver, _driver_crash_count
    with _driver_lock:
        if _driver:
            try: _driver.quit()
            except Exception as e:
                logging.warning(f'quit_driver: {e}')
            _driver = None
    _driver_crash_count = 0      # quit طبيعي → نصفّر العداد
    kill_our_chrome_processes()

_idle_watcher_running = False

def _start_driver_idle_watcher():
    global _idle_watcher_running
    if _idle_watcher_running: return
    _idle_watcher_running = True
    def _watch():
        global _idle_watcher_running
        while True:
            time.sleep(30)
            with _driver_lock:
                if _driver is None:
                    _idle_watcher_running = False
                    return
                idle_secs = time.time() - _driver_last_used
                if idle_secs >= DRIVER_IDLE_TIMEOUT:
                    logging.info(f'Chrome idle {idle_secs:.0f}s — closing.')
                    try: _driver.quit()
                    except Exception as e: logging.debug(f'idle_watcher quit: {e}')
                    globals()['_driver'] = None
                    _idle_watcher_running = False
                    kill_our_chrome_processes()
                    return
    threading.Thread(target=_watch, daemon=True).start()

# ─────────────────────────────────────────────
#  مساعدات فحص البيانات وعناوين البحث
# ─────────────────────────────────────────────
VALID_SUB_EXTS   = ('.srt', '.ass', '.vtt', '.sub', '.idx')
VALID_VIDEO_EXTS = ('.mkv', '.mp4', '.avi')
CURRENT_YEAR     = datetime.now().year   # ديناميكي — لا حاجة لتحديث يدوي

def extract_movie_info(filename):
    m = re.search(r'[.\s_]((19|20)\d{2})[.\s_]?', filename)
    if m:
        raw = filename[:m.start()]
        return re.sub(r'[._\-\(\)]', ' ', raw).strip(), m.group(1)
    
    m2 = re.search(r'\b((19|20)\d{2})\b', filename)
    if m2:
        raw = filename[:m2.start()]
        return re.sub(r'[._\-\(\)]', ' ', raw).strip(), m2.group(1)
    return None, None

def is_probable_movie_folder(folder_name):
    """تتحقق مما إذا كان المجلد المحذوف هو مجلد فيلم محتمل (يحتوي على اسم وسنة ولا يحتوي على دلالات المسلسلات)."""
    if re.search(r'\b[sS]\d+\b|\b[eE]\d+\b|\bseason\b|\bepisodes?\b', folder_name, re.IGNORECASE):
        return False
    title, year = extract_movie_info(folder_name)
    return title is not None and year is not None

@lru_cache(maxsize=1024)
def get_clean_words(text):
    """تنظيف النص وتحويله إلى كلمات فريدة مخزنة مؤقتاً لتسريع الأداء."""
    return frozenset(re.sub(r'[._-]', ' ', text.lower()).split())

_year_cache     = {}
_YEAR_CACHE_MAX = 200
_year_cache_lock = threading.Lock()   # حماية thread-safe للـ cache
_http = requests.Session()
_http.headers['User-Agent'] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                'AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36')

# ── Config cache — نقرأ من الـ disk مرة واحدة فقط، تحديث عند save_config ──
_cached_cfg      = None
_cached_cfg_mtime = 0

def get_cached_config():
    """يرجع الـ config من الذاكرة — بيتحدث تلقائياً لو الملف اتغيّر"""
    global _cached_cfg, _cached_cfg_mtime
    try:
        mtime = os.path.getmtime(CFG_PATH) if os.path.exists(CFG_PATH) else 0
        if _cached_cfg is None or mtime != _cached_cfg_mtime:
            _cached_cfg       = load_config()
            _cached_cfg_mtime = mtime
    except Exception:
        if _cached_cfg is None:
            _cached_cfg = dict(DEFAULT_CONFIG)
    return _cached_cfg

def _cache_set(key, val):
    with _year_cache_lock:
        if len(_year_cache) >= _YEAR_CACHE_MAX:
            _year_cache.pop(next(iter(_year_cache)))
        _year_cache[key] = val

def fetch_year(title):
    with _year_cache_lock:
        if title in _year_cache:
            return _year_cache[title]
    try:
        d = _http.get('http://www.omdbapi.com/',
                      params={'t': title, 'type': 'series', 'apikey': 'trilogy'}, timeout=6).json()
        if d.get('Response') == 'True' and re.match(r'(19|20)\d{2}', d.get('Year','')[:4]):
            y = d['Year'][:4]; _cache_set(title, y); return y
    except Exception as e:
        logging.debug(f'fetch_year OMDB: {e}')
    try:
        d = _http.get('https://api.themoviedb.org/3/search/tv',
                      params={'query': title, 'api_key': '2696829a81b1b5827d515571ef8d8289'}, timeout=6).json()
        if d.get('results') and re.match(r'(19|20)\d{2}', d['results'][0].get('first_air_date','')[:4]):
            y = d['results'][0]['first_air_date'][:4]; _cache_set(title, y); return y
    except Exception as e:
        logging.debug(f'fetch_year TMDB: {e}')
    _cache_set(title, None); return None

def build_slug(name):
    """يبني slug للـ URL — يدعم الأسماء العربية والمختلطة"""
    # تحويل الأسماء العربية إلى ترانزليتريشن إنجليزي بسيط
    arabic_map = {
        'ا': 'a', 'أ': 'a', 'إ': 'a', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
        'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'th', 'ر': 'r', 'ز': 'z',
        'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
        'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
        'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ة': 'a', 'ء': '', 'ئ': 'y',
        'ؤ': 'w', 'لا': 'la',
    }
    s = name.lower()
    for ar, en in arabic_map.items():
        s = s.replace(ar, en)
    s = re.sub(r"'s\b", 's', s)
    s = re.sub(r"'", '', s).replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    # لو النتيجة فاضية (اسم غريب جداً) نرجع النص الأصلي بعد encode
    if not s:
        import urllib.parse
        s = urllib.parse.quote(name.lower(), safe='')
    return s

def build_urls(video_file, force_year=None):
    sm = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)
    if sm:
        season_num  = int(sm.group(1))
        raw         = video_file[:sm.start()]
        series_name = re.sub(r'[._-]', ' বিস্ত'.strip(), raw).strip()
        year_m      = re.search(r'((?:19|20)\d{2})', raw)
        year        = force_year or (year_m.group(1) if year_m else None)
        slug = build_slug(series_name)
        if season_num == 1:
            if not year: year = fetch_year(series_name) or str(CURRENT_YEAR)
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
            search_url = f'https://subsource.net/search?q={mn.replace(" ","+")}'
            return movie_url, search_url, mn, None, yr, None
    return None, None, None, None, None, None

# ─────────────────────────────────────────────
#  ميزة: تنظيف الاسم والبحث في DeviantArt وتطبيق الأيقونة
# ─────────────────────────────────────────────
def clean_and_rename_folder_on_disk(folder_path):
    return rename_path_cleanly(folder_path)

def clean_name_strict(folder_name):
    cut_index = len(folder_name)
    
    # البحث عن كلمات الموسم أو السنة أو الكلمات التقنية لقص كل ما بعدها
    year_match = re.search(r'\b(19|20)\d{2}\b', folder_name)
    season_match = re.search(r'\b([sS]\d{2}|[sS]eason[\s._-]*\d+)\b', folder_name, re.IGNORECASE)
    tech_match = re.search(r'\b(1080p|720p|2160p|4K|BluRay|WEBRip|WEB-DL|COMPLETE|PSA|10bit|2CH|x264|x265|HEVC|REPACK|REMUX|HDR)\b', folder_name, re.IGNORECASE)

    if year_match: cut_index = min(cut_index, year_match.start())
    if season_match: cut_index = min(cut_index, season_match.start())
    if tech_match: cut_index = min(cut_index, tech_match.start())

    if cut_index < len(folder_name):
        clean_title = folder_name[:cut_index]
    else:
        clean_title = folder_name

    # تنظيف المسافات والرموز المتبقية
    clean_title = re.sub(r'[._\-]', ' ', clean_title)
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', clean_title)
    return re.sub(r'\s+', ' ', clean_title).strip()

def search_deviantart(query):
    clean_query = query.strip()
    unique_images = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    search_term = clean_query.replace(" ", "+") + "+folder+icon"
    url = f"https://www.deviantart.com/search?q={search_term}"

    try:
        session = requests.Session()
        res = session.get(url, headers=headers, timeout=10, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')

        raw_links = []
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src and ('deviantart.net' in src or 'images-wixmp' in src):
                if '/f/' in src:
                    large_src = re.sub(r'/w_\d+,h_\d+,q_\d+/', '/w_1024,h_1024,q_100/', src)
                    raw_links.append(large_src)
                else:
                    raw_links.append(src)

        art_pages = []
        for a in soup.find_all('a', href=True):
            if '/art/' in a['href'] and a['href'] not in art_pages:
                art_pages.append(a['href'])

        def fetch_from_art_page(art_url):
            try:
                r = session.get(art_url, headers=headers, timeout=3)
                s = BeautifulSoup(r.text, 'html.parser')
                img_tag = s.find('img', {'src': re.compile(r'images-wixmp')})
                return img_tag['src'] if img_tag else None
            except: return None

        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_from_art_page, art_pages[:12]))
            raw_links.extend([r for r in results if r])

        for link in raw_links:
            if link not in unique_images:
                unique_images.append(link)

    except Exception as e:
        logging.error(f"DeviantArt Error: {e}")

    if len(unique_images) < 5:
        try:
            bing_url = f"https://www.bing.com/images/search?q={clean_query}+folder+icon+deviantart"
            res = session.get(bing_url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            for a in soup.find_all('a', class_='iusc'):
                m = json.loads(a.get('m', '{}'))
                img_link = m.get('murl')
                if img_link and img_link not in unique_images:
                    unique_images.append(img_link)
        except: pass

    return unique_images[:28]

def process_and_set_icon(img_url, folder_path):
    if sys.platform != 'win32':
        return False, "تغيير الأيقونات مدعوم فقط على نظام التشغيل Windows."
    try:
        h = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(img_url, headers=h, timeout=15, verify=False)
        img = Image.open(BytesIO(r.content))

        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        width, height = img.size
        new_size = max(width, height)
        square_img = Image.new("RGBA", (new_size, new_size), (0, 0, 0, 0))
        square_img.paste(img, ((new_size - width) // 2, (new_size - height) // 2))

        icon_path = os.path.join(folder_path, "folder.ico")
        ini_path = os.path.join(folder_path, "desktop.ini")

        for f in [icon_path, ini_path]:
            if os.path.exists(f):
                ctypes.windll.kernel32.SetFileAttributesW(f, 128)
                os.remove(f)

        square_img.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48)])

        ini_content = "[.ShellClassInfo]\r\nIconResource=folder.ico,0\r\n[ViewState]\r\nMode=\r\nVid=\r\nFolderType=Videos\r\n"
        with open(ini_path, 'w', encoding='utf-16') as f:
            f.write(ini_content)

        ctypes.windll.kernel32.SetFileAttributesW(icon_path, 0x02 | 0x04)
        ctypes.windll.kernel32.SetFileAttributesW(ini_path, 0x02 | 0x04)
        ctypes.windll.kernel32.SetFileAttributesW(folder_path, 0x01)

        ctypes.windll.shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, folder_path, None)
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)

        return True, "Success"
    except Exception as e:
        return False, str(e)

def should_apply_folder_icon(directory, media_type):
    if not os.path.isdir(directory):
        return False, None

    # ── حماية لمنع تغيير أيقونة مجلد المراقبة الرئيسي (مثل Downloads) ──
    cfg = get_cached_config()
    watch_folder = cfg.get('watch_folder', '')
    if watch_folder and os.path.abspath(directory).lower() == os.path.abspath(watch_folder).lower():
        return False, None

    # ── تحقق فقط من وجود ملف الأيقونة الفعلي لمنع تخطي المجلدات بسبب ملفات desktop.ini التلقائية من ويندوز ──
    icon_file = os.path.join(directory, "folder.ico")
    if os.path.exists(icon_file):
        return False, None

    folder_name = os.path.basename(directory)
    query = clean_name_strict(folder_name)
    return True, query

def scan_for_missing_folder_icons(parent_folder, log=None):
    if not os.path.isdir(parent_folder):
        return
    excluded_dirs = {'$recycle.bin', 'system volume information', 'node_modules', '.git', 'appdata'}
    for entry in os.scandir(parent_folder):
        if entry.is_dir() and entry.name.lower() not in excluded_dirs and not entry.name.startswith('.'):
            has_icon = os.path.exists(os.path.join(entry.path, "folder.ico"))
            if not has_icon:
                if log: log(f"📁 وجد مجلد بدون أيقونة: {entry.name}")
                cleaned_path = clean_and_rename_folder_on_disk(entry.path)
                query = clean_name_strict(os.path.basename(cleaned_path))
                if _app_instance and _app_instance.root:
                    _app_instance.root.after(0, lambda p=cleaned_path, q=query: _show_icon_picker(p, q, log))

# ─────────────────────────────────────────────
#  فك الضغط والأرشيفات
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
    except Exception:
        pass
    if RAR_AVAILABLE:
        try:
            with rarfile.RarFile(archive_path) as rf:
                return any(n.lower().endswith(VALID_SUB_EXTS) for n in rf.namelist())
        except Exception:
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
    excluded_dirs = {'$recycle.bin', 'system volume information', 'node_modules', '.git', 'appdata'}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in excluded_dirs]
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
#  مساعدات متصفح Chrome والـ Cloudflare
# ─────────────────────────────────────────────
def wait_cloudflare(driver, max_wait=45):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if any(kw in driver.title.lower() for kw in ('just a moment','cloudflare','attention')):
            time.sleep(2); continue
        src = driver.page_source[:500].lower()
        if 'challenge' in src or 'cf-browser-verification' in src:
            time.sleep(2); continue
        return True
    return False

def chrome_load(url, wait_css, timeout=45, log=None):
    if log: log(f'   ⏳ Chrome يفتح الصفحة...')
    driver = get_driver(log=log)
    if not driver:
        if log: log('   ❌ Chrome لم يستجب — تأكد من تثبيت المتصفح بشكل كامل.')
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
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, 0);')
        time.sleep(1)
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_css)))
        if log: log(f'   ✅ الصفحة محملة')
    except Exception as ex:
        if log: log(f'   ⚠️ انتهى الوقت أو العنصر مش موجود — نكمل بما هو متاح')
    src = driver.page_source
    if log: log(f'   📄 حجم الصفحة: {len(src)} حرف')
    return src

def chrome_get_subtitle_links(page_url, log, force_subtitle_page=False):
    if log: log(f'   🌐 فتح: {page_url[:80]}')

    is_search_results = '/search' in page_url and 'q=' in page_url and not force_subtitle_page

    wait_css = 'a[href^="/subtitles/"],a[href^="/subtitle/"]' if is_search_results else 'a[href^="/subtitle/"]'
    html = chrome_load(page_url, wait_css, 45, log)
    if not html and log: log('   ⚠️ لم يتم تحميل الصفحة')
    if not html: return []
    soup = BeautifulSoup(html, 'html.parser')

    if is_search_results:
        movie_anchors = soup.find_all('a', href=re.compile(r'^/subtitles/[^/]+/?$'))
        seen_slugs = set()
        links = []
        for a in movie_anchors:
            href = a['href'].strip().rstrip('/')
            if href in seen_slugs: continue
            seen_slugs.add(href)
            title = a.get_text(strip=True) or href.split('/')[-1]
            links.append({'href': href, 'release': title, '_type': 'subtitles_page'})
        if log: log(f'   🔎 وجد {len(links)} فيلم/مسلسل في نتايج البحث')
        return links

    links = [{'href': a['href'].strip(),
              'release': a.get_text(strip=True) or a['href'].split('/')[-1],
              '_type': 'subtitle'}
             for a in soup.find_all('a', href=re.compile(r'^/subtitle/'))]

    if not links:
        page_text = soup.get_text()
        has_content = len(page_text.strip()) > 500
        if has_content:
            if log: log('   ⚠️ الصفحة اتحملت بس مفيش ترجمات — subsource ممكن غيّر البنية أو الحلقة دي مش فيها ترجمة عربي')
        else:
            if log: log('   ❌ الصفحة فارغة — تحقق من الاتصال أو Cloudflare')

    if log: log(f'   📋 وجد {len(links)} ترجمة' if links else '   ⚠️ لا نتائج في هذا الرابط')
    return links

def chrome_get_download_url(sub_href, log):
    html = chrome_load(f'https://subsource.net{sub_href}',
                       'a[href*="api.subsource.net"][href*="/subtitle/download/"]', 45, log)
    if not html: return None
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=re.compile(r'api\.subsource\.net.*/subtitle/download/')):
        return a['href'].strip()
    for a in soup.find_all('a', href=True):
        if 'download' in a['href'].lower():
            return a['href'] if a['href'].startswith('http') else f'https://subsource.net{a["href"]}'
    return None

def _validate_subtitles(extracted, video_file, log=None):
    sm = re.search(r'S(\d+)E(\d+)', video_file, re.IGNORECASE)
    if not sm:
        return extracted
    s, e = sm.groups()
    s_num, e_num = int(s), int(e)
    valid = []
    for fname in extracted:
        fm = re.search(r'S(\d+)E(\d+)', fname, re.IGNORECASE)
        if fm:
            if int(fm.group(1)) == s_num and int(fm.group(2)) == e_num:
                valid.append(fname)
        else:
            valid.append(fname)
    return valid

def chrome_download_zip(dl_url, sub_href, directory, log, video_file=None):
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
        if extracted and video_file:
            extracted = _validate_subtitles(extracted, video_file, log)
            if not extracted and log: log('   ❌ الترجمة المحملة مش للحلقة دي — نجرب التالية')
        return extracted
    except Exception as ex:
        if log: log(f'   ❌ خطأ فك تشفير: {ex}')
    return []

# ─────────────────────────────────────────────
#  نظام فحص أولوية حزم المواسم الكاملة (Season Packs)
# ─────────────────────────────────────────────
def is_season_pack(release_name, href, season_num):
    """تتحقق إذا كان الرابط يخص حزمة ترجمة لموسم كامل (Season Pack) لموسم معين."""
    name_lower = f"{release_name} {href}".lower()
    
    season_patterns = [
        rf'\bs{season_num:02d}\b',
        rf'\bs{season_num}\b',
        rf'\bseason[\s._-]*{season_num}\b',
        rf'\bseason[\s._-]*{season_num:02d}\b'
    ]
    if not any(re.search(pat, name_lower) for pat in season_patterns):
        return False
        
    has_pack_keywords = any(kw in name_lower for kw in ['complete', 'pack', 'full', 'all', 'كامل', 'دفعة', 'الموسم'])
    
    has_single_ep = re.search(r'\be\d+\b', name_lower) and not re.search(r'\be\d+[\s._-]*to[\s._-]*\be?\d+\b|\be\d+-\d+\b', name_lower)
    
    return has_pack_keywords or not has_single_ep

def get_best_links(links, video_file, series_match, log, max_candidates=5):
    if not links: return []
    links = [l for l in links if l.get('_type', 'subtitle') == 'subtitle']
    if not links: return []
    clean_video = get_clean_words(os.path.splitext(video_file)[0])
    candidates = []

    arabic_links = [l for l in links if '/arabic/' in l['href'] or 'arabic' in l['release'].lower()]
    if not arabic_links:
        if log: log('   ℹ️ لا توجد ترجمات عربية في هذه الصفحة')
        return []

    if series_match:
        s, e = series_match.groups()
        s_num, e_num = int(s), int(e)
        ep_pattern = re.compile(rf'S{s_num:02d}E{e_num:02d}', re.IGNORECASE)

        for lnk in arabic_links:
            if is_season_pack(lnk['release'], lnk['href'], s_num):
                candidates.append((lnk['href'], f"عربي موسم كامل: {lnk['release'][:70]}"))

        for lnk in arabic_links:
            if ep_pattern.search(lnk['release']):
                candidates.append((lnk['href'], f"عربي مطابق للحلقة: {lnk['release'][:70]}"))

        for lnk in arabic_links:
            candidates.append((lnk['href'], f"عربي: {lnk['release'][:70]}"))

    else:
        for lnk in arabic_links:
            sim = len(clean_video & get_clean_words(lnk['release'])) / (
                  len(clean_video | get_clean_words(lnk['release'])) or 1)
            candidates.append((lnk['href'], sim, f"عربي ({sim:.2f}): {lnk['release'][:70]}"))
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = [(h, r) for h, _, r in candidates]

    seen = set(); final = []
    for h, r in candidates:
        if h not in seen:
            seen.add(h); final.append({'href': h, 'reason': r})
            if len(final) >= max_candidates: break
    return final

# ─────────────────────────────────────────────
#  إعادة التسمية والتنظيم
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
                except Exception as e:
                    if log: log(f'   ⚠️ خطأ تسمية {f}: {e}')
                    logging.warning(f'do_rename: {e}')
    return count

# ─────────────────────────────────────────────
#  نقل الحلقة لفولدر المسلسل تلقائياً
# ─────────────────────────────────────────────
def _folder_name_match(series_name, folder_name):
    """
    مقارنة ذكية بين اسم المسلسل المستخرج من اسم الملف واسم الفولدر.
    يتعامل مع فروق النقط والشرطات والمسافات والأحرف الكبيرة.
    """
    def _norm(s):
        s = re.sub(r'[._\-]', ' ', s)
        s = s.replace("'", "").replace("'", "").replace("'", "")   # Widow's → Widows
        s = re.sub(r'\s+', ' ', s).strip().lower()
        return s

    sn = _norm(series_name)
    fn = _norm(folder_name)

    if not sn or not fn:
        return False

    # مطابقة تامة
    if sn == fn:
        return True

    # كلمات المسلسل
    s_words = sn.split()
    f_words = fn.split()

    # لو كل كلمات المسلسل موجودة كاملة في الفولدر (الفولدر ممكن فيه "Season 1" زيادة)
    if all(w in f_words for w in s_words):
        return True

    # نسبة التشابه ≥ 85%
    common = len(set(s_words) & set(f_words))
    if common == 0:
        return False
    ratio = common / max(len(s_words), len(f_words))
    return ratio >= 0.85


def move_to_series_folder(video_path, log=None):
    """
    لو الملف حلقة (SxxExx) والمسلسل عنده فولدر بالاسم ده في نفس مجلد الـ downloads،
    بينقل الفيديو والسورس بتاعته جواه تلقائياً.
    ويُرجع المسار الجديد.
    """
    if not os.path.isfile(video_path):
        return None

    fname     = os.path.basename(video_path)
    directory = os.path.dirname(video_path)

    sm = re.search(r'S(\d+)E(\d+)', fname, re.IGNORECASE)
    if not sm:
        return None   # مش حلقة

    raw         = fname[:sm.start()]
    series_name = re.sub(r'[._-]', ' ', raw).strip()
    if not series_name:
        return None

    if log: log(f'   🔎 بيدور على فولدر لـ "{series_name}" في {directory}')

    # البحث عن فولدر مطابق في نفس مجلد الفيديو
    target_folder = None
    try:
        for entry in os.scandir(directory):
            if not entry.is_dir():
                continue
            if os.path.abspath(entry.path) == os.path.abspath(directory):
                continue
            if _folder_name_match(series_name, entry.name):
                target_folder = entry.path
                break
    except Exception as e:
        if log: log(f'   ⚠️ move_to_series_folder scan error: {e}')
        return None

    if not target_folder:
        if log: log(f'   ℹ️ مفيش فولدر مناسب لـ "{series_name}" — مش هينقل')
        return None

    if log: log(f'   ✅ لاقى الفولدر: "{os.path.basename(target_folder)}"')

    # تجميع الفيديو + كل السورس بنفس الاسم الأساسي
    base_name     = os.path.splitext(fname)[0]
    files_to_move = [video_path]
    try:
        for f in os.listdir(directory):
            if f == fname:
                continue
            if f.lower().endswith(VALID_SUB_EXTS) and f.startswith(base_name):
                files_to_move.append(os.path.join(directory, f))
    except Exception as e:
        if log: log(f'   ⚠️ move_to_series_folder list error: {e}')

    moved_count = 0
    for src_path in files_to_move:
        src_name = os.path.basename(src_path)
        dst_path = os.path.join(target_folder, src_name)
        try:
            if os.path.exists(dst_path):
                if log: log(f'   ⚠️ موجود بالفعل: {src_name}')
                continue
            shutil.move(src_path, dst_path)
            if log: log(f'   📁 نُقل: {src_name} → {os.path.basename(target_folder)}/')
            moved_count += 1
        except Exception as e:
            if log: log(f'   ❌ خطأ نقل {src_name}: {e}')
            logging.error(f'move_to_series_folder: {e}')

    if moved_count:
        if log: log(f'   ✅ تم نقل {moved_count} ملف لـ "{os.path.basename(target_folder)}"')
        return target_folder
    return None


def maybe_create_series_folder(video_path, log=None):
    """
    لو الحلقة E01 من أي موسم ومفيش فولدر للمسلسل:
      - لو الفيديو فايل منفرد في downloads  → ينشئ فولدر باسم المسلسل وينقل الفيديو + الترجمة جواه
      - لو الفيديو جوا فولدر التورنت (اتسمى مسبقاً)  → يرجع الفولدر ده مباشرةً للـ icon picker
    يُرجع مسار الفولدر الجديد/الموجود، أو None لو مش E01 أو في فولدر بالفعل.
    """
    if not os.path.isfile(video_path):
        return None

    fname     = os.path.basename(video_path)
    directory = os.path.dirname(video_path)

    sm = re.search(r'S(\d+)E(\d+)', fname, re.IGNORECASE)
    if not sm:
        return None
    if int(sm.group(2)) != 1:          # بس E01
        return None

    # ── استخرج الاسم النظيف للمسلسل ──
    raw         = fname[:sm.start()]
    series_name = re.sub(r'[._-]', ' ', raw).strip()
    clean_name  = series_name.replace("'", "").replace("\u2019", "").replace("\u2018", "")
    clean_name  = re.sub(r'\s+', ' ', clean_name).strip()
    if not clean_name:
        return None

    cfg          = get_cached_config()
    watch_folder = cfg.get('watch_folder', '')

    # ── Case A: الفيديو جوا فولدر التورنت اللى اتسمى بالفعل ──
    # يعني directory مش هو watch_folder نفسه — الفولدر ده هو المسلسل
    if watch_folder and os.path.abspath(directory).lower() != os.path.abspath(watch_folder).lower():
        if log: log(f'   📂 الفيديو جوا فولدر التورنت بالفعل: "{os.path.basename(directory)}" — هيُفتح اختيار الأيقونة')
        return directory   # أرجع الفولدر الموجود للـ icon picker

    # ── Case B: الفيديو فايل منفرد في downloads ──
    # تحقق إن مفيش فولدر مطابق بالفعل
    try:
        for entry in os.scandir(directory):
            if entry.is_dir() and _folder_name_match(series_name, entry.name):
                if log: log(f'   ℹ️ فولدر "{entry.name}" موجود بالفعل — move_to_series_folder هيتولاه')
                return None
    except Exception as e:
        if log: log(f'   ⚠️ maybe_create scan error: {e}')

    # أنشئ الفولدر الجديد
    new_folder = os.path.join(directory, clean_name)
    try:
        os.makedirs(new_folder, exist_ok=True)
        if log: log(f'   📁 تم إنشاء فولدر جديد: "{clean_name}"')
    except Exception as e:
        if log: log(f'   ❌ فشل إنشاء الفولدر "{clean_name}": {e}')
        return None

    # انقل الفيديو + الترجمة جواه
    base_name    = os.path.splitext(fname)[0]
    files_to_move = [video_path]
    try:
        for f in os.listdir(directory):
            if f == fname:
                continue
            if f.lower().endswith(VALID_SUB_EXTS) and f.startswith(base_name):
                files_to_move.append(os.path.join(directory, f))
    except Exception as e:
        if log: log(f'   ⚠️ maybe_create list error: {e}')

    for src in files_to_move:
        dst = os.path.join(new_folder, os.path.basename(src))
        try:
            if os.path.exists(dst):
                if log: log(f'   ⚠️ موجود بالفعل: {os.path.basename(src)}')
                continue
            shutil.move(src, dst)
            if log: log(f'   📁 نُقل: {os.path.basename(src)} → {clean_name}/')
        except Exception as e:
            if log: log(f'   ❌ خطأ نقل {os.path.basename(src)}: {e}')
            logging.error(f'maybe_create_series_folder move: {e}')

    return new_folder


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
    links = chrome_get_subtitle_links(season_url, log, force_subtitle_page=True)

    if not links and not cancel_event.is_set():
        links = chrome_get_subtitle_links(search_url, log)

    if not links or cancel_event.is_set(): return 0, False

    if links and links[0].get('_type') == 'subtitles_page':
        clean_video = get_clean_words(os.path.splitext(video_file)[0])
        best = None; best_score = -1
        for lnk in links:
            score = len(clean_video & get_clean_words(lnk['release'])) / (
                    len(clean_video | get_clean_words(lnk['release'])) or 1)
            if score > best_score:
                best_score = score; best = lnk
        if best:
            if log: log(f'   🔗 أقرب نتيجة: {best["release"]} (تشابه {best_score:.0%})')
            sub_page_url = f'https://subsource.net{best["href"]}'
            links = chrome_get_subtitle_links(sub_page_url, log, force_subtitle_page=True)

    if not links or cancel_event.is_set(): return 0, False

    arabic_on_site = any(
        '/arabic/' in lnk.get('href', '') or 'arabic' in lnk.get('release', '').lower()
        for lnk in links
    )

    if log: log(f'   📋 وجد {len(links)} ترجمة — يبحث عن عربي...')
    candidates = get_best_links(links, video_file, series_match, log, 5)
    if not candidates:
        if log: log('   ℹ️ مفيش ترجمة عربية — سيتم تجربة الترجمة التلقائية')
        return 0, arabic_on_site
    for idx, cand in enumerate(candidates, 1):
        if cancel_event.is_set(): break
        if log: log(f"   ⬇️ محاولة {idx}/{len(candidates)}: {cand['reason'][:60]}")
        dl_url = chrome_get_download_url(cand['href'], log)
        if not dl_url or cancel_event.is_set(): continue
        if log: log(f"   📦 جاري تحميل الملف...")
        extracted = chrome_download_zip(dl_url, cand['href'], directory, log, video_file=video_file)
        if extracted:
            if log: log(f'   ✅ نجاح! {", ".join(extracted)}')
            return len(extracted), arabic_on_site
        if log: log(f'   ⚠️ فشل، نجرب التالي...')
    return 0, arabic_on_site

def auto_download(season_url, search_url, video_file, series_match, directory, log, cancel_event, known_year=None):
    if not UC_AVAILABLE:
        if log: log(f'   ❌ Chrome غير متاح: {UC_IMPORT_ERROR}')
        return 0, False
    
    n, arabic_on_site = _try_download(season_url, search_url, video_file, series_match, directory, log, cancel_event)
    if n or cancel_event.is_set(): return n, arabic_on_site
    
    if not known_year and series_match:
        s_num = int(series_match.group(1))
        if s_num > 1: return 0, arabic_on_site
        raw = video_file[:series_match.start()]
        series_name = re.sub(r'[._-]', ' ', raw).strip()
        slug_base = build_slug(series_name)
        s_url = f'https://subsource.net/search?q={series_name.replace(" ","+")}'
        for yr in range(CURRENT_YEAR, CURRENT_YEAR - 6, -1):
            if cancel_event.is_set(): return 0, arabic_on_site
            if log: log(f'   🗓️  سنة {yr}...')
            n, ar = _try_download(
                f'https://subsource.net/subtitles/{slug_base}-{yr}/season-{s_num}',
                s_url, video_file, series_match, directory, log, cancel_event)
            arabic_on_site = arabic_on_site or ar
            if n: return n, arabic_on_site
    return 0, arabic_on_site

# ─────────────────────────────────────────────
#  ترجمة تلقائية من الإنجليزي المدمج عبر Google Translator
# ─────────────────────────────────────────────
_ffmpeg_installed_cache = None

def _has_ffmpeg():
    global _ffmpeg_installed_cache
    if _ffmpeg_installed_cache is not None:
        return _ffmpeg_installed_cache
    try:
        subprocess.run(['ffprobe', '-version'], capture_output=True, timeout=5, creationflags=_NO_WINDOW)
        _ffmpeg_installed_cache = True
        return True
    except Exception:
        pass
    if STATIC_FFMPEG_AVAILABLE:
        try:
            static_ffmpeg.add_paths()
            subprocess.run(['ffprobe', '-version'], capture_output=True, timeout=5, creationflags=_NO_WINDOW)
            _ffmpeg_installed_cache = True
            return True
        except Exception:
            pass
    _ffmpeg_installed_cache = False
    return False

def extract_embedded_english_sub(video_path, log=None):
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_path],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW
        )
        if probe.returncode != 0:
            return None
        import json as _j
        info = _j.loads(probe.stdout)
        sub_streams = [s for s in info.get('streams', [])
                       if s.get('codec_type') == 'subtitle']
        if not sub_streams:
            return None

        eng = next(
            (s for s in sub_streams
             if s.get('tags', {}).get('language', '').lower() in ('eng', 'en')),
            sub_streams[0]
        )
        idx = eng['index']
        tmp_srt = video_path + '.extracted.srt'
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', video_path, '-map', f'0:{idx}', '-c:s', 'srt', tmp_srt],
            capture_output=True, timeout=60,
            creationflags=_NO_WINDOW
        )
        if result.returncode == 0 and os.path.exists(tmp_srt):
            try:
                with open(tmp_srt, 'r', encoding='utf-8', errors='replace') as fh:
                    content = fh.read()
                return content if content.strip() else None
            finally:
                try: os.remove(tmp_srt)
                except Exception: pass
    except Exception as e:
        if log: log(f'   ⚠️ ffmpeg: {e}')
    return None

def translate_srt_arabic(srt_content, log=None):
    if not GOOGLE_TRANSLATE_AVAILABLE:
        if log: log('   ❌ مكتبة deep-translator غير مثبتة')
        return None

    raw_blocks = re.split(r'\n\n+', srt_content.strip())
    total      = len(raw_blocks)
    if log: log(f'   🌐 جاري ترجمة {total} سطر...')

    translator   = GoogleTranslator(source='en', target='ar')
    MAX_CHARS    = 4500
    SEPARATOR    = '\n⬛\n'

    def _translate_batch(texts):
        results  = list(texts)
        batch    = []
        b_idxs   = []
        b_chars  = 0

        def _flush(b, idxs):
            joined = SEPARATOR.join(b)
            try:
                ar = translator.translate(joined) or joined
                parts = ar.split(SEPARATOR.strip())
                if len(parts) == len(idxs):
                    for i, p in zip(idxs, parts):
                        results[i] = p.strip()
                else:
                    for i, orig in zip(idxs, b):
                        try:
                            results[i] = (translator.translate(orig) or orig).strip()
                        except Exception:
                            pass
            except Exception as e:
                if log: log(f'   ⚠️ خطأ ترجمة: {e}')

        for i, txt in enumerate(texts):
            tlen = len(txt)
            if b_chars + tlen + len(SEPARATOR) > MAX_CHARS and batch:
                _flush(batch, b_idxs)
                batch, b_idxs, b_chars = [], [], 0
            batch.append(txt)
            b_idxs.append(i)
            b_chars += tlen + len(SEPARATOR)

        if batch:
            _flush(batch, b_idxs)

        return results

    headers  = []
    dialogs  = []
    empties  = []

    for blk in raw_blocks:
        lines    = blk.splitlines()
        hdr_part = []
        dlg_part = []
        for ln in lines:
            if re.match(r'^\s*\d+\s*$', ln) or '-->' in ln:
                hdr_part.append(ln)
            else:
                if ln.strip():
                    dlg_part.append(ln)
        headers.append('\n'.join(hdr_part))
        dialogs.append('\n'.join(dlg_part))
        empties.append(not bool(dlg_part))

    texts_to_translate = [d for d in dialogs if d]
    translated_dialogs = _translate_batch(texts_to_translate)

    tr_iter = iter(translated_dialogs)
    output  = []
    done    = 0
    for i, blk in enumerate(raw_blocks):
        if empties[i]:
            output.append(blk)
            continue
        ar = next(tr_iter, dialogs[i])
        output.append(headers[i] + '\n' + ar)
        done += 1
        if log and done % 100 == 0:
            log(f'   🌐 تمت ترجمة {done}/{total - sum(empties)}...')

    if log: log(f'   ✅ اكتملت الترجمة ({done} سطر)')
    return '\n\n'.join(output) + '\n'

def _ask_user_translate(video_name):
    result = {'ok': False}
    done   = threading.Event()
    def _show():
        answer = messagebox.askyesno(
            'Auto Subs — ترجمة تلقائية',
            f'مش لاقيتش ترجمة عربية على SubSource لـ:\n{video_name}\n\n'
            'تحب أستخرج الترجمة الإنجليزية المدمجة\nوأترجمهالك بـ Google Translate؟',
            icon='question'
        )
        result['ok'] = answer
        done.set()
    if _app_instance and _app_instance.root:
        _app_instance.root.after(0, _show)
        done.wait(timeout=120)
    else:
        result['ok'] = True
        done.set()
    return result['ok']

def try_auto_translate(video_path, base_name, directory, log=None, silent=False):
    cfg = get_cached_config()
    if not cfg.get('auto_translate_fallback', True):
        return False
    if not GOOGLE_TRANSLATE_AVAILABLE:
        if log: log('   ℹ️ مكتبة Google Translate غير مثبتة — pip install deep-translator')
        return False
    if not _has_ffmpeg():
        if log: log('   ℹ️ ffmpeg مش متاح — شغّل: pip install static-ffmpeg  (أو ثبّت ffmpeg على جهازك)')
        return False

    auto_silent = cfg.get('auto_translate_silent', False)
    if not auto_silent:
        video_name = os.path.basename(video_path)
        if log: log('   ❓ مفيش ترجمة عربية — بسأل المستخدم...')
        user_ok = _ask_user_translate(video_name)
        if not user_ok:
            if log: log('   ⏭️ المستخدم اختار عدم الترجمة')
            return False

    if log: log('   🔍 جاري فحص الترجمة المدمجة في الفيديو...')
    srt_content = extract_embedded_english_sub(video_path, log)
    if not srt_content:
        if log: log('   ℹ️ مفيش ترجمة إنجليزية مدمجة في الملف')
        return False

    if log: log(f'   ✅ وجد ترجمة إنجليزية ({len(srt_content)} حرف) — جاري الترجمة...')
    arabic_srt = translate_srt_arabic(srt_content, log=log)
    if not arabic_srt:
        if log: log('   ❌ فشلت الترجمة التلقائية')
        return False

    out_path = os.path.join(directory, base_name + '.ar.srt')
    try:
        with open(out_path, 'w', encoding='utf-8-sig') as fh:
            fh.write(arabic_srt)
        if log: log(f'   ✅ ترجمة عربية حُفظت: {os.path.basename(out_path)}')
        return True
    except Exception as e:
        if log: log(f'   ❌ فشل حفظ الترجمة: {e}')
    return False

# ─────────────────────────────────────────────
#  مساعدات البحث وتعيين أيقونة المجلد (Folder Icon)
# ─────────────────────────────────────────────
def _fetch_images_via_chrome(query, max_results=8, log=None):
    if not UC_AVAILABLE:
        return []
    results = []
    driver  = None
    try:
        import urllib.parse
        q_enc = urllib.parse.quote(f'{query} folder icon')
        url   = f'https://www.bing.com/images/search?q={q_enc}&form=HDRSC2'

        driver = _get_driver(log)
        if not driver:
            return []

        driver.get(url)
        time.sleep(2)

        script = """
        var items = [];
        var cards = document.querySelectorAll('a.iusc');
        for (var i = 0; i < Math.min(cards.length, 12); i++) {
            try {
                var m = JSON.parse(cards[i].getAttribute('m') || '{}');
                if (m.murl) items.push({thumb: m.turl || m.murl, full: m.murl});
            } catch(e) {}
        }
        if (items.length === 0) {
            var imgs = document.querySelectorAll('.mimg');
            for (var j = 0; j < Math.min(imgs.length, 12); j++) {
                var src = imgs[j].src || imgs[j].getAttribute('data-src');
                if (src && src.startsWith('http')) items.push({thumb: src, full: src});
            }
        }
        return JSON.stringify(items);
        """
        raw = driver.execute_script(script)
        import json as _j
        items = _j.loads(raw or '[]')
        for item in items:
            t = item.get('thumb', '')
            f = item.get('full', '')
            if f and (t, f) not in results:
                results.append((t or f, f))
            if len(results) >= max_results:
                break
    except Exception as e:
        if log: log(f'   ⚠️ chrome image fetch: {e}')
    return results[:max_results]


def _show_icon_picker(directory, query, log=None):
    if not _app_instance or not _app_instance.root:
        return

    # فحص أخير قبل فتح نافذة الاختيار لمنع فتح نوافذ مكررة لنفس المجلد
    with _ACTIVE_PICKERS_LOCK:
        if directory.lower() in _ACTIVE_PICKERS:
            return
        _ACTIVE_PICKERS.add(directory.lower())

    BG     = '#121212'
    CARD   = '#1e1e1e'
    ACCENT = '#4fa8ff'
    THUMB  = 150
    COLS   = 4

    win = tk.Toplevel(_app_instance.root)
    win.title('🎨 اختار أيقونة للمجلد')
    win.configure(bg=BG)
    win.resizable(False, False)
    
    # ── ضمان ظهور النافذة بشكل مرئي في المقدمة حتى لو كان البرنامج صامتاً في الـ Tray ──
    win.deiconify()
    win.attributes('-topmost', True)
    win.after(600, lambda: win.attributes('-topmost', False))  # فك التثبيت لتسهيل الاستخدام لاحقاً
    win.lift()
    win.focus_force()
    win.grab_set()

    W = COLS * (THUMB + 20) + 60
    H = 560
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f'{W}x{H}+{(sw-W)//2}+{(sh-H)//2}')

    # تحرير قفل المجلد عند غلق النافذة يدوياً
    def _on_destroy():
        with _ACTIVE_PICKERS_LOCK:
            _ACTIVE_PICKERS.discard(directory.lower())
        try: win.destroy()
        except Exception: pass

    win.protocol('WM_DELETE_WINDOW', _on_destroy)

    tk.Label(win, text='🎨 اختار أيقونة للمجلد من DeviantArt',
             font=('Segoe UI', 12, 'bold'), bg=BG, fg=ACCENT).pack(pady=(12, 4))

    search_f = tk.Frame(win, bg=BG)
    search_f.pack(fill=tk.X, padx=16, pady=(0, 8))
    search_var = tk.StringVar(value=f'{query}')
    search_entry = tk.Entry(search_f, textvariable=search_var,
                            font=('Segoe UI', 10), bg='#2a2a2a', fg='white',
                            insertbackground='white', relief='flat')
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 6))
    search_btn = tk.Button(search_f, text='🔍 بحث', font=('Segoe UI', 10),
                           bg=ACCENT, fg='white', relief='flat', padx=12, pady=4,
                           cursor='hand2')
    search_btn.pack(side=tk.LEFT)

    status_var  = tk.StringVar(value='')
    loading_var = tk.StringVar(value='')
    tk.Label(win, textvariable=status_var,  font=('Segoe UI', 9), bg=BG, fg='#27ae60').pack()
    tk.Label(win, textvariable=loading_var, font=('Segoe UI', 8), bg=BG, fg='#555').pack()

    outer  = tk.Frame(win, bg=BG)
    outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
    vsb    = tk.Scrollbar(outer, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    grid_f = tk.Frame(canvas, bg=BG)
    cwin   = canvas.create_window((0, 0), window=grid_f, anchor='nw')
    grid_f.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfig(cwin, width=e.width))
    canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-1*(e.delta//120), 'units'))

    tk.Button(win, text='❌ إلغاء', font=('Segoe UI', 10),
              bg='#2c2c2c', fg='white', relief='flat', padx=14, pady=5,
              cursor='hand2', command=_on_destroy).pack(pady=6)

    _photos   = []
    _cells    = []
    _search_running = [False]

    def _clear_grid():
        for w in grid_f.winfo_children():
            w.destroy()
        _cells.clear()
        _photos.clear()

    def _make_placeholder(i):
        r, c = divmod(i, COLS)
        cell = tk.Frame(grid_f, bg='#2a2a2a', width=THUMB+10, height=THUMB+10,
                        relief='flat', cursor='hand2')
        cell.grid(row=r, column=c, padx=5, pady=5)
        cell.grid_propagate(False)
        ph = tk.Label(cell, text='⏳', font=('Segoe UI', 20),
                      bg='#2a2a2a', fg='#444')
        ph.place(relx=0.5, rely=0.5, anchor='center')
        _cells.append({'cell': cell, 'ph': ph, 'full_url': ''})

    def _place_image(idx, raw, full_url):
        if not win.winfo_exists() or idx >= len(_cells):
            return
        d   = _cells[idx]
        cell = d['cell']
        ph   = d['ph']
        d['full_url'] = full_url

        loaded = sum(1 for c in _cells if c['full_url'])
        loading_var.set(f'تحميل {loaded}/{len(_cells)} صورة')
        if loaded >= len(_cells):
            loading_var.set('')

        if raw is None:
            ph.configure(text='✗', fg='#555')
            return
        try:
            img   = Image.open(io.BytesIO(raw)).convert('RGBA')
            img.thumbnail((THUMB, THUMB), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            ph.configure(text='✗', fg='#555')
            return

        _photos.append(photo)
        try: ph.destroy()
        except Exception: pass
        lbl = tk.Label(cell, image=photo, bg='#2a2a2a', cursor='hand2')
        lbl.place(relx=0.5, rely=0.5, anchor='center')

        def _apply(c=cell, u=full_url):
            for d2 in _cells:
                try:
                    d2['cell'].configure(bg='#2a2a2a')
                    for w in d2['cell'].winfo_children():
                        w.configure(bg='#2a2a2a')
                except Exception:
                    pass
            c.configure(bg=ACCENT)
            for w in c.winfo_children():
                try: w.configure(bg=ACCENT)
                except Exception: pass
            status_var.set('⏳ جاري التطبيق...')
            win.update_idletasks()
            def _do():
                ok, msg = process_and_set_icon(u, directory)
                def _done():
                    if ok:
                        status_var.set('✅ تم تطبيق الأيقونة!')
                        if log: log('   ✅ تم تعيين أيقونة المجلد!')
                        win.after(1500, _on_destroy)
                    else:
                        status_var.set(f'❌ فشل: {msg}')
                win.after(0, _done)
            threading.Thread(target=_do, daemon=True).start()

        lbl.bind('<Button-1>', lambda e, fn=_apply: fn())
        cell.bind('<Button-1>', lambda e, fn=_apply: fn())

    def _load_one(idx, thumb_url, full_url):
        ua = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        for url in ([thumb_url, full_url] if thumb_url != full_url else [full_url]):
            if not url:
                continue
            try:
                r = requests.get(url, timeout=10, headers=ua, verify=False,
                                 allow_redirects=True)
                ct = r.headers.get('content-type', '')
                ok_magic = r.content[:4] in (b'\x89PNG', b'GIF8', b'\xff\xd8\xff', b'RIFF') or \
                           r.content[:2] == b'BM' or b'WEBP' in r.content[:12]
                if r.status_code == 200 and len(r.content) > 1000 and ('image' in ct or ok_magic):
                    return idx, r.content, full_url
            except Exception:
                continue
        return idx, None, full_url

    def _do_search(q=None):
        if _search_running[0]:
            return
        _search_running[0] = True
        search_btn.configure(state='disabled', text='⏳ جاري...')
        status_var.set('')
        _clear_grid()

        search_q = (q or search_var.get()).strip()
        if not search_q:
            _search_running[0] = False
            search_btn.configure(state='normal', text='🔍 بحث')
            return

        MAX = 8
        for i in range(MAX):
            _make_placeholder(i)
        loading_var.set(f'⏳ جاري البحث عن: {search_q}')
        win.update_idletasks()

        def _bg():
            da_images = search_deviantart(search_q)
            images_data = []
            for img_url in da_images:
                images_data.append((img_url, img_url))

            if not images_data:
                chrome_images = _fetch_images_via_chrome(search_q, max_results=MAX, log=log)
                for t, f in chrome_images:
                    images_data.append((t, f))

            if not images_data:
                try:
                    import urllib.parse
                    hdrs = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                                      'Chrome/124.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.bing.com/',
                    }
                    sess = requests.Session()
                    q_enc = urllib.parse.quote(search_q)
                    r = sess.get(
                        f'https://www.bing.com/images/search?q={q_enc}&form=HDRSC2',
                        headers=hdrs, timeout=12, verify=False)
                    import json as _j
                    from bs4 import BeautifulSoup as BS
                    soup = BS(r.text, 'html.parser')
                    for a in soup.select('a.iusc, [m]'):
                        raw = a.get('m') or ''
                        if not raw:
                            continue
                        try:
                            data = _j.loads(raw)
                            fu   = data.get('murl', '')
                            tu   = data.get('turl', '') or fu
                            if fu and (tu, fu) not in images_data:
                                images_data.append((tu, fu))
                                if len(images_data) >= MAX:
                                    break
                        except Exception:
                            continue
                except Exception as e:
                    logging.debug(f'fallback search: {e}')

            actual = len(images_data)
            def _update_placeholders():
                if not win.winfo_exists():
                    return
                while len(_cells) > actual:
                    d = _cells.pop()
                    try: d['cell'].destroy()
                    except Exception: pass
                loading_var.set(f'تحميل الصور... 0/{actual}' if actual else '')
                if actual == 0:
                    status_var.set('⚠️ مفيش نتائج — جرب كلمة تانية')
                search_btn.configure(state='normal', text='🔍 بحث')
                _search_running[0] = False

            win.after(0, _update_placeholders)

            if not images_data:
                return

            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(_load_one, i, t, f): i
                        for i, (t, f) in enumerate(images_data)}
                for fut in as_completed(futs):
                    try:
                        idx, raw, full = fut.result()
                    except Exception:
                        continue
                    if win.winfo_exists():
                        win.after_idle(lambda i=idx, rb=raw, fu=full: _place_image(i, rb, fu))

        threading.Thread(target=_bg, daemon=True).start()

    search_btn.configure(command=_do_search)
    search_entry.bind('<Return>', lambda e: _do_search())

    win.after(300, lambda: _do_search(f'{query}'))


def async_setup_folder_icon(directory, media_type, log=None):
    """يفتح picker اختيار أيقونة المجلد — في الـ main thread."""
    should_run, query = should_apply_folder_icon(directory, media_type)
    if not should_run or not query:
        return
    if not _app_instance or not _app_instance.root:
        return
    _app_instance.root.after(0, lambda: _show_icon_picker(directory, query, log))


# ─────────────────────────────────────────────
#  معالجة ملف منفرد وإصلاح الخلل البنائي
# ─────────────────────────────────────────────
def process_one_file(file_path, log=None, set_status=None, cancel_event=None, silent=False, allow_move=True, skip_icon=False):
    """معالجة ملف فيديو واحد للبحث والتحميل أو ربط الترجمة تلقائياً."""
    if silent:
        log = log or logging.info

    fname = os.path.basename(file_path)

    def _set_job(status):
        with _active_jobs_lock:
            _active_jobs[fname] = status
        if _app_instance:
            _app_instance._refresh_active_jobs()

    _set_job('🔍 يبحث...')

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

    # التحقق من وجود ترجمة مسابقة وإتمام النقل للمسلسلات
    if has_existing_srt(video_file, directory):
        if log: log("✅ ترجمة مطابقة موجودة بالفعل على القرص أو داخل حزمة موسم — يتم الربط المباشر")
        _set_job('✅ موجودة')
        result = do_rename(video_file, base_name, series_match, directory, log)
        
        final_dir = directory
        if allow_move and media_type == 'episode':
            target_dir = move_to_series_folder(file_path, log)
            if target_dir: final_dir = target_dir
        elif allow_move and media_type == 'movie':
            # نظّف اسم مجلد الفيلم أولاً قبل فتح اختيار الأيقونة
            cleaned = rename_path_cleanly(directory)
            if cleaned and cleaned != directory:
                if log: log(f'   📁 تم تنظيف اسم المجلد: {os.path.basename(cleaned)}')
            final_dir = cleaned if cleaned else directory

        if not skip_icon:
            threading.Thread(target=async_setup_folder_icon, args=(final_dir, media_type, log), daemon=True).start()
        
        with _active_jobs_lock: _active_jobs.pop(fname, None)
        if _app_instance: _app_instance._refresh_active_jobs()
        return result

    season_url, search_url, name, season_num, year, sm = build_urls(video_file)
    if not season_url:
        if log: log('❌ تعذّر بناء الرابط')
        db_log(video_file, media_type, series_name, s_num, e_num, 'failed')
        _set_job('❌ فشل')
        with _active_jobs_lock: _active_jobs.pop(fname, None)
        if _app_instance: _app_instance._refresh_active_jobs()
        return 0

    label = name + (f' — الموسم {season_num}' if season_num else f' ({year})' if year else '')
    if set_status: set_status(f'⏳ جاري التحميل:\n{label}')
    _set_job(f'⬇️ {label}')

    if silent:
        send_notification('found', {'name': label})

    if log: log(f'🔗 URL: {season_url}')

    n, arabic_on_site = auto_download(season_url, search_url, video_file, series_match, directory, log, cancel_event, year)
    if cancel_event.is_set():
        with _active_jobs_lock: _active_jobs.pop(fname, None)
        if _app_instance: _app_instance._refresh_active_jobs()
        return 0

    if n == 0:
        translated_ok = False
        if not arabic_on_site:
            _set_job('🌐 جاري الترجمة التلقائية...')
            translated_ok = try_auto_translate(file_path, base_name, directory, log)

        if translated_ok:
            db_log(video_file, media_type, series_name, s_num, e_num, 'success')
            if silent:
                if media_type == 'episode':
                    send_notification('done_episode', {
                        'series': series_name, 'season': s_num, 'episode': e_num
                    })
                else:
                    mn2, yr2 = extract_movie_info(video_file)
                    send_notification('done_movie', {'name': mn2 or name, 'year': yr2 or year})
            _set_job('✅ مترجم تلقائياً')
            
            final_dir = directory
            if allow_move and media_type == 'episode':

                target_dir = move_to_series_folder(file_path, log)
                if target_dir: final_dir = target_dir
            elif allow_move and media_type == 'movie':
                # نظّف اسم مجلد الفيلم أولاً قبل فتح اختيار الأيقونة
                cleaned = rename_path_cleanly(directory)
                if cleaned and cleaned != directory:
                    if log: log(f'   📁 تم تنظيف اسم المجلد: {os.path.basename(cleaned)}')
                final_dir = cleaned if cleaned else directory

            if not skip_icon:
                threading.Thread(target=async_setup_folder_icon, args=(final_dir, media_type, log), daemon=True).start()
            
            with _active_jobs_lock: _active_jobs.pop(fname, None)
            if _app_instance: _app_instance._refresh_active_jobs()
            return 1

        if log: log('⏰ لم نجد ترجمة')
        db_log(video_file, media_type, series_name, s_num, e_num, 'failed')
        if silent:
            send_notification('failed', {'name': label})
        _set_job('❌ فشل')
        with _active_jobs_lock: _active_jobs.pop(fname, None)
        if _app_instance: _app_instance._refresh_active_jobs()
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

    # النقل التلقائي وتحديث الأيقونة
    final_dir = directory
    if allow_move and media_type == 'episode':
        target_dir = move_to_series_folder(file_path, log)
        if target_dir: final_dir = target_dir
    elif allow_move and media_type == 'movie':
        # نظّف اسم مجلد الفيلم أولاً قبل فتح اختيار الأيقونة
        cleaned = rename_path_cleanly(directory)
        if cleaned and cleaned != directory:
            if log: log(f'   📁 تم تنظيف اسم المجلد: {os.path.basename(cleaned)}')
        final_dir = cleaned if cleaned else directory

    if not skip_icon:
        threading.Thread(target=async_setup_folder_icon, args=(final_dir, media_type, log), daemon=True).start()

    with _active_jobs_lock: _active_jobs.pop(fname, None)
    if _app_instance: _app_instance._refresh_active_jobs()
    return renamed if renamed > 0 else n

def run_all(paths_list, result_label, root_ref, log_func, set_status_func, cancel_event, silent=False, allow_move=True, skip_icon=False):
    video_exts = VALID_VIDEO_EXTS
    video_files_paths = []
    excluded_dirs = {'$recycle.bin', 'system volume information', 'node_modules', '.git', 'appdata'}
    for path in paths_list:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in excluded_dirs]
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
        if not os.path.exists(file_path):
            if log_func: log_func('   ⚠️ الملف غير موجود في هذا المسار (قد يكون تم نقله أو إعادة تسميته) — تخطي')
            continue
        total += process_one_file(file_path, log_func, set_status_func, cancel_event, silent, allow_move=allow_move, skip_icon=skip_icon)
        if silent:
            quit_driver()

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
_pending_files_lock  = threading.Lock()
_heartbeat_thread    = None
_PENDING_TIMEOUT     = 30 * 60

def _cleanup_stale_pending():
    now = time.time()
    with _pending_files_lock:
        stale = [p for p, t in _pending_files.items() if now - t > _PENDING_TIMEOUT]
        for p in stale:
            logging.warning(f'pending_cleanup: removing stale entry: {os.path.basename(p)}')
            _pending_files.pop(p, None)

class VideoHandler(FileSystemEventHandler):
    def _handle_path(self, path):
        with _pending_files_lock:
            if path in _pending_files: return
            if not path.lower().endswith(VALID_VIDEO_EXTS): return
            _pending_files[path] = time.time()
        enqueue_subtitle_job(self._wait_and_process, path)

    def _handle_directory(self, folder_path):
        time.sleep(2)
        if not os.path.isdir(folder_path): return
        
        # التأكد من عدم معالجة مسار تم التعامل معه في الـ 60 ثانية الماضية لمنع الحلقات اللانهائية
        with _processed_dirs_lock:
            now = time.time()
            for p, t in list(_processed_dirs_cache.items()):
                if now - t > 60:
                    _processed_dirs_cache.pop(p, None)
            if folder_path.lower() in _processed_dirs_cache:
                return
            _processed_dirs_cache[folder_path.lower()] = now

        watch_folder = _watchdog_folder_ref[0]
        if watch_folder:
            parent_dir = os.path.dirname(os.path.abspath(folder_path))
            if os.path.abspath(parent_dir).lower() != os.path.abspath(watch_folder).lower():
                return
        
        # نسجل المسار الأصلي في الـ cache قبل التنظيف لمنع on_moved من فتح picker ثانٍ
        with _processed_dirs_lock:
            _processed_dirs_cache[folder_path.lower()] = time.time()

        cleaned_path = clean_and_rename_folder_on_disk(folder_path)
        
        # إذا تم تغيير اسم المجلد، نسجل المسار الجديد في ذاكرة الحماية المؤقتة لمنع إطلاق الحدث مجدداً
        if cleaned_path.lower() != folder_path.lower():
            with _processed_dirs_lock:
                _processed_dirs_cache[cleaned_path.lower()] = time.time()

    def on_created(self, event):
        if event.is_directory:
            watch_folder = _watchdog_folder_ref[0]
            if watch_folder:
                parent_dir = os.path.dirname(os.path.abspath(event.src_path))
                if os.path.abspath(parent_dir).lower() == os.path.abspath(watch_folder).lower():
                    with _processed_dirs_lock:
                        if event.src_path.lower() in _processed_dirs_cache:
                            return
                    threading.Thread(target=self._handle_directory, args=(event.src_path,), daemon=True).start()
            return
        self._handle_path(event.src_path)

    def _check_and_trigger_letterboxd(self, folder_path):
        """تقوم بالتحقق من هوية المجلد المحذوف أو المنقول لسلة المهملات، وتفعيل Letterboxd عند المطابقة."""
        folder_name = os.path.basename(os.path.normpath(folder_path))
        
        # 1. تجاهل أي ملف ينتهي بامتداد فيديو أو ترجمة لتجنب الخلط
        if folder_name.lower().endswith(VALID_VIDEO_EXTS) or folder_name.lower().endswith(VALID_SUB_EXTS):
            return
            
        watch_folder = _watchdog_folder_ref[0]
        if not watch_folder:
            return
        
        # 2. مقارنة وتوحيد المسار الأب بشكل متوافق تماماً
        parent_dir = os.path.dirname(os.path.normpath(folder_path))
        if os.path.normpath(parent_dir).lower() == os.path.normpath(watch_folder).lower():
            if is_probable_movie_folder(folder_name):
                title, year = extract_movie_info(folder_name)
                if title and year:
                    logging.info(f"Watchdog Trigger: Movie folder '{folder_name}' removed. Opening Letterboxd for {title} ({year})")
                    threading.Thread(target=auto_log_letterboxd, args=(title, year), daemon=True).start()

    def on_deleted(self, event):
        # تفعيل التحقق فوراً عند الحذف متخطين شرط is_directory لتفادي قيود نظام التشغيل بعد مسح الفولدر
        self._check_and_trigger_letterboxd(event.src_path)

    def on_moved(self, event):
        watch_folder = _watchdog_folder_ref[0]
        if watch_folder:
            src_path  = os.path.normpath(event.src_path)
            dest_path = os.path.normpath(event.dest_path)
            
            src_parent = os.path.dirname(src_path)
            if os.path.normpath(src_parent).lower() == os.path.normpath(watch_folder).lower():
                # إذا تم نقله خارج مجلد المراقبة بالكامل (نقل إلى سلة المهملات)
                if not dest_path.lower().startswith(os.path.normpath(watch_folder).lower()):
                    self._check_and_trigger_letterboxd(event.src_path)
                    return

        if event.is_directory:
            watch_folder = _watchdog_folder_ref[0]
            if watch_folder:
                # المعالجة الطبيعية للنقل والتسمية داخل مجلد المراقبة
                parent_dir = os.path.dirname(os.path.abspath(event.dest_path))
                if os.path.abspath(parent_dir).lower() == os.path.abspath(watch_folder).lower():
                    with _processed_dirs_lock:
                        if event.dest_path.lower() in _processed_dirs_cache:
                            return
                        if event.src_path.lower() in _processed_dirs_cache:
                            return
                    threading.Thread(target=self._handle_directory, args=(event.dest_path,), daemon=True).start()
            return
        self._handle_path(event.dest_path)

    def _scan_new_folder(self, folder_path):
        time.sleep(2)
        if not os.path.isdir(folder_path): return
        excluded_dirs = {'$recycle.bin', 'system volume information', 'node_modules', '.git', 'appdata'}
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in excluded_dirs]
            for f in files:
                self._handle_path(os.path.join(root, f))

    def _wait_and_process(self, path):
        time.sleep(3)
        fname = os.path.basename(path)
        logging.info(f'Watchdog: fetching subtitle for {fname}')
        cancel_ev = threading.Event()
        global _app_instance
        if _app_instance:
            # allow_move=False: الـ watchdog بيشتغل أثناء التحميل — النقل هيحصل بس لما يتمسح التورنت
            _app_instance.start_background_process([path], allow_move=False, skip_icon=True)
        else:
            run_all([path], None, None, logging.info, None, cancel_ev, silent=True, allow_move=False, skip_icon=True)
        with _pending_files_lock:
            _pending_files.pop(path, None)

def start_watchdog(folder, app_instance=None):
    global _watchdog_observer, _app_instance
    if app_instance:
        _app_instance = app_instance
    _watchdog_folder_ref[0] = folder
    with _watchdog_lock:
        if _watchdog_observer:
            try: _watchdog_observer.stop(); _watchdog_observer.join(2)
            except Exception as e: logging.warning(f'start_watchdog stop old: {e}')
        if not WATCHDOG_AVAILABLE or not folder or not os.path.isdir(folder):
            return False
        _watchdog_observer = Observer()
        _watchdog_observer.schedule(VideoHandler(), folder, recursive=True)
        _watchdog_observer.start()
        logging.info(f'Watchdog started: {folder}')
        # تشغيل مراقب uTorrent مع الـ watchdog
        start_utorrent_monitor()
        return True

def stop_watchdog():
    global _watchdog_observer
    _watchdog_folder_ref[0] = None
    with _watchdog_lock:
        if _watchdog_observer:
            try: _watchdog_observer.stop(); _watchdog_observer.join(2)
            except Exception as e: logging.warning(f'stop_watchdog: {e}')
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
            _cleanup_stale_pending()
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
        except Exception as e:
            logging.debug(f'show_main_window: {e}')

def quit_app():
    stop_watchdog()
    quit_driver()
    if _tray_icon:
        try: _tray_icon.stop()
        except Exception as e: logging.debug(f'quit_app tray stop: {e}')
    if _main_window_ref:
        try: _main_window_ref.destroy()
        except Exception as e: logging.debug(f'quit_app destroy: {e}')
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
#  الواجهة الرئيسية ومصادر الواجهة
# ─────────────────────────────────────────────
def parse_dnd_paths(event_data):
    if not event_data: return []
    if '{' in event_data: return re.findall(r'\{([^{}]+)\}', event_data)
    return event_data.split()

class MainApp:
    def __init__(self):
        global _main_window_ref, _app_instance
        _app_instance = self
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
            except Exception as e:
                logging.warning(f'MainApp icon load: {e}')

        self._build_ui()
        self._apply_initial_config()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        if TRAY_AVAILABLE:
            threading.Thread(target=run_tray, daemon=True).start()

        if self.cfg.get('auto_watch'):
            start_watchdog(self.cfg.get('watch_folder', ''), app_instance=self)
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
            self.log("      python auto_subs_v10.py")
            self.log("─────────────────────────────────────────────\n")

    def _on_close(self):
        self.root.withdraw()
        if TRAY_AVAILABLE:
            send_notification('found', {'name': 'Auto Subs يعمل في الخلفية'})

    def _build_ui(self):
        BG     = '#121212'
        ACCENT = '#4fa8ff'

        hdr = tk.Frame(self.root, bg='#0a0a0a'); hdr.pack(fill=tk.X)
        lf  = tk.Frame(hdr, bg='#0a0a0a'); lf.pack(side=tk.LEFT, padx=15, pady=10)
        tk.Label(lf, text='Auto Subs', font=('Segoe UI', 20, 'bold'),
                 bg='#0a0a0a', fg=ACCENT).pack(anchor='w')
        tk.Label(lf, text='تحميل ترجمات تلقائي • v10', font=('Segoe UI', 8),
                 bg='#0a0a0a', fg='#444').pack(anchor='w')

        tab_bar = tk.Frame(self.root, bg='#0d0d0d'); tab_bar.pack(fill=tk.X)
        self.tabs_content = {}
        self.tab_buttons  = {}
        tab_names = [('main','🎬 تحميل'), ('active','⚡ جاري الآن'), ('torrent','🔗 uTorrent'), ('scan','🔎 فحص'), ('stats','📊 إحصائيات'), ('settings','⚙️ الإعدادات')]
        for tid, label in tab_names:
            btn = tk.Button(tab_bar, text=label, font=('Segoe UI', 10, 'bold'),
                            bg=ACCENT if tid=='main' else '#1a1a1a',
                            fg='white', relief='flat', padx=14, pady=8, cursor='hand2',
                            command=lambda t=tid: self._switch_tab(t))
            btn.pack(side=tk.LEFT, padx=2)
            self.tab_buttons[tid] = btn

        self.content_area = tk.Frame(self.root, bg=BG); self.content_area.pack(fill=tk.BOTH, expand=True)
        self._build_main_tab()
        self._build_active_tab()
        self._build_torrent_tab()
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

    def _build_active_tab(self):
        BG = '#121212'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['active'] = f

        tk.Label(f, text='⚡ جاري الآن', font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg='white').pack(pady=(20, 4))
        tk.Label(f, text='الملفات اللي البرنامج بيشتغل عليها دلوقتي في الخلفية',
                 font=('Segoe UI', 9), bg=BG, fg='#555').pack(pady=(0, 12))

        self.active_empty_label = tk.Label(f, text='لا يوجد شيء جاري الآن ✅',
                                           font=('Segoe UI', 11), bg=BG, fg='#444')
        self.active_empty_label.pack(pady=30)

        self.active_jobs_frame = tk.Frame(f, bg=BG)
        self.active_jobs_frame.pack(fill=tk.BOTH, expand=True, padx=20)

        self.active_job_widgets = {}

    def _refresh_active_jobs(self):
        if not hasattr(self, 'active_jobs_frame'): return
        def _do():
            with _active_jobs_lock:
                jobs = dict(_active_jobs)

            for w in self.active_jobs_frame.winfo_children():
                w.destroy()
            self.active_job_widgets.clear()

            if not jobs:
                self.active_empty_label.pack(pady=30)
                return

            self.active_empty_label.pack_forget()
            for fname, status in jobs.items():
                row = tk.Frame(self.active_jobs_frame, bg='#1e1e1e', pady=8, padx=12)
                row.pack(fill=tk.X, pady=3)
                tk.Label(row, text=fname[:60] + ('...' if len(fname) > 60 else ''),
                         font=('Segoe UI', 9, 'bold'), bg='#1e1e1e', fg='white',
                         anchor='w').pack(side=tk.LEFT, fill=tk.X, expand=True)
                tk.Label(row, text=status, font=('Segoe UI', 9),
                         bg='#1e1e1e', fg='#4fa8ff', anchor='e').pack(side=tk.RIGHT)

        self.root.after(0, _do)

    def _build_torrent_tab(self):
        BG = '#121212'; CARD = '#1e1e1e'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['torrent'] = f

        tk.Label(f, text='🔗 تكامل uTorrent', font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg='white').pack(pady=(20, 4))
        tk.Label(f, text='بعد الاكتمال: يجيب الترجمة ← يستنى التورنت ← يمسحه ← يربط الترجمة في مكانها',
                 font=('Segoe UI', 9), bg=BG, fg='#555').pack(pady=(0, 16))

        card = tk.Frame(f, bg=CARD); card.pack(fill=tk.X, padx=24, pady=4)

        self.utorrent_enabled_var = tk.BooleanVar(value=self.cfg.get('utorrent_enabled', False))
        tk.Checkbutton(card, text='تفعيل التكامل مع uTorrent',
                       variable=self.utorrent_enabled_var,
                       bg=CARD, fg='white', activebackground=CARD, activeforeground='white',
                       selectcolor='#27ae60', font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=16, pady=(14,6))

        self.ut_delete_var = tk.BooleanVar(value=self.cfg.get('utorrent_delete_torrent', True))
        tk.Checkbutton(card, text='مسح التورنت من القايمة تلقائياً بعد الاكتمال',
                       variable=self.ut_delete_var,
                       bg=CARD, fg='#ccc', activebackground=CARD, activeforeground='white',
                       selectcolor='#e67e22', font=('Segoe UI', 9)).pack(anchor='w', padx=32, pady=(0,10))

        tk.Frame(card, bg='#2a2a2a', height=1).pack(fill=tk.X, padx=16, pady=6)

        fields = [
            ('🌐  Host', 'utorrent_host', 'http://127.0.0.1:8080', False),
            ('👤  Username', 'utorrent_user', 'admin', False),
            ('🔑  Password', 'utorrent_pass', '', True),
        ]
        self._ut_entries = {}
        for label, key, default, secret in fields:
            row = tk.Frame(card, bg=CARD); row.pack(fill=tk.X, padx=16, pady=5)
            tk.Label(row, text=label, font=('Segoe UI', 10), bg=CARD, fg='#aaa',
                     width=14, anchor='w').pack(side=tk.LEFT)
            e = tk.Entry(row, font=('Segoe UI', 10), bg='#2a2a2a', fg='white',
                         relief='flat', insertbackground='white',
                         show='●' if secret else '')
            e.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0,4))
            e.insert(0, self.cfg.get(key, default))
            self._ut_entries[key] = e

            if secret:
                def _toggle(entry=e):
                    entry.config(show='' if entry.cget('show') else '●')
                tk.Button(row, text='👁', font=('Segoe UI', 9), bg='#2a2a2a', fg='#aaa',
                          relief='flat', cursor='hand2', command=_toggle).pack(side=tk.LEFT)

        tk.Frame(card, bg='#2a2a2a', height=1).pack(fill=tk.X, padx=16, pady=10)

        btn_row = tk.Frame(card, bg=CARD); btn_row.pack(fill=tk.X, padx=16, pady=(0,14))
        self.ut_status_lbl = tk.Label(btn_row, text='', font=('Segoe UI', 9),
                                      bg=CARD, fg='#27ae60')
        self.ut_status_lbl.pack(side=tk.LEFT)
        tk.Button(btn_row, text='💾 حفظ', font=('Segoe UI', 10, 'bold'),
                  bg='#4fa8ff', fg='white', relief='flat', cursor='hand2', width=10,
                  command=self._save_utorrent).pack(side=tk.RIGHT, padx=(6,0))
        tk.Button(btn_row, text='🔗 اختبار الاتصال', font=('Segoe UI', 9),
                  bg='#27ae60', fg='white', relief='flat', cursor='hand2',
                  command=self._test_utorrent).pack(side=tk.RIGHT)

        guide = tk.Frame(f, bg='#1a1a2e'); guide.pack(fill=tk.X, padx=24, pady=(12,4))
        tk.Label(guide, text='📋 إزاي تفعّل Web UI في uTorrent',
                 font=('Segoe UI', 10, 'bold'), bg='#1a1a2e', fg='#4fa8ff').pack(anchor='w', padx=14, pady=(10,4))
        steps = [
            '1.  افتح uTorrent  →  Options  →  Preferences',
            '2.  روح  Advanced  →  Web UI',
            '3.  فعّل  "Enable Web UI"',
            '4.  حط Username: admin  والـ Password بتاعك',
            '5.  Port افتراضي: 8080  (متغيّرهوش)',
            '6.  اضغط OK  —  ارجع هنا وحط نفس البيانات واتست',
        ]
        for s in steps:
            tk.Label(guide, text=s, font=('Segoe UI', 9), bg='#1a1a2e',
                     fg='#ccc', anchor='w').pack(anchor='w', padx=24, pady=1)
        tk.Frame(guide, bg='#1a1a2e', height=10).pack()

    def _save_utorrent(self):
        self.cfg['utorrent_enabled']        = self.utorrent_enabled_var.get()
        self.cfg['utorrent_delete_torrent'] = self.ut_delete_var.get()
        self.cfg['utorrent_host']           = self._ut_entries['utorrent_host'].get()
        self.cfg['utorrent_user']           = self._ut_entries['utorrent_user'].get()
        self.cfg['utorrent_pass']           = self._ut_entries['utorrent_pass'].get()
        global _utorrent_api
        _utorrent_api = None
        save_config(self.cfg)
        self.ut_status_lbl.configure(text='✅ تم الحفظ!', fg='#27ae60')

    def _build_scan_tab(self):
        BG = '#121212'; ACCENT = '#4fa8ff'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['scan'] = f

        tk.Label(f, text='🔎 فحص مجلد Downloads للأرشيفات والأيقونات',
                 font=('Segoe UI', 13, 'bold'), bg=BG, fg='white').pack(pady=(18,4))
        tk.Label(f, text='يبحث عن ملفات ZIP/RAR تحتوي على ترجمات، يفك ضغطها ويسميها بأسماء ملفات الفيديو ويحدث أيقونات المجلدات المفقودة',
                 font=('Segoe UI', 9), bg=BG, fg='#666', wraplength=600).pack(pady=(0,12))

        path_f = tk.Frame(f, bg='#1e1e1e'); path_f.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(path_f, text='المجلد:', font=('Segoe UI', 10), bg='#1e1e1e', fg='#aaa').pack(side=tk.LEFT, padx=10, pady=8)
        self.scan_entry = tk.Entry(path_f, font=('Segoe UI', 9), bg='#2a2a2a', fg='white',
                                   relief='flat', insertbackground='white')
        self.scan_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.scan_entry.insert(0, self.cfg.get('watch_folder', ''))
        tk.Button(path_f, text='...', bg=ACCENT, fg='white', relief='flat', cursor='hand2',
                  command=self._browse_scan_folder).pack(side=tk.LEFT, padx=(5, 10))

        btn_container = tk.Frame(f, bg=BG)
        btn_container.pack(pady=10)

        self.scan_btn = tk.Button(btn_container, text='▶ ابدأ فحص الأرشيفات', font=('Segoe UI', 11, 'bold'),
                                  bg='#27ae60', fg='white', relief='flat', cursor='hand2',
                                  width=18, pady=8, command=self._run_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=5)

        self.scan_icons_btn = tk.Button(btn_container, text='🎨 فحص الأيقونات المفقودة', font=('Segoe UI', 11, 'bold'),
                                        bg='#9b59b6', fg='white', relief='flat', cursor='hand2',
                                        width=20, pady=8, command=self._run_icon_scan)
        self.scan_icons_btn.pack(side=tk.LEFT, padx=5)

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

    def _run_icon_scan(self):
        folder = self.scan_entry.get()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror('خطأ', 'المجلد غير موجود!')
            return
        self.scan_icons_btn.configure(state='disabled')
        self.scan_status.configure(text='جاري فحص الأيقونات المفقودة...', fg='#f39c12')
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
            scan_for_missing_folder_icons(folder, log=_scan_log)
            def _done():
                self.scan_icons_btn.configure(state='normal')
                self.scan_status.configure(text='✅ اكتمل فحص وتحديث الأيقونات المفقودة!', fg='#2ecc71')
            self.root.after(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _build_stats_tab(self):
        BG = '#121212'; CARD = '#1e1e1e'
        f = tk.Frame(self.content_area, bg=BG); self.tabs_content['stats'] = f

        hdr_row = tk.Frame(f, bg=BG); hdr_row.pack(fill=tk.X, padx=20, pady=(20, 5))
        tk.Label(hdr_row, text='📊 إحصائيات', font=('Segoe UI', 14, 'bold'),
                 bg=BG, fg='white').pack(side=tk.LEFT)
        tk.Button(hdr_row, text='🗑️ مسح السجل كله', font=('Segoe UI', 9),
                  bg='#c0392b', fg='white', relief='flat', cursor='hand2',
                  command=self._clear_stats).pack(side=tk.RIGHT)
        tk.Button(hdr_row, text='🔄 تحديث', font=('Segoe UI', 9),
                  bg='#4fa8ff', fg='white', relief='flat', cursor='hand2',
                  command=self._refresh_stats).pack(side=tk.RIGHT, padx=(0, 6))
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
            (self.scan_arch_var,  '📦 فحص الأرشيفات في المجلدات الجديدة المضافة أثناء التشغيل'),
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

        api_f = tk.Frame(f, bg=CARD); api_f.pack(fill=tk.X, padx=20, pady=6)
        tk.Label(api_f, text='🌐 ترجمة تلقائية بـ Google Translate:',
                 font=('Segoe UI', 10), bg=CARD, fg='white').pack(anchor='w', padx=12, pady=(10,2))
        tk.Label(api_f, text='لو SubSource ما عندهوش ترجمة عربية، البرنامج يسألك وبيترجم الترجمة الإنجليزية المدمجة (يحتاج ffmpeg + deep-translator)',
                 font=('Segoe UI', 8), bg=CARD, fg='#888', wraplength=580).pack(anchor='w', padx=12)

        self.auto_translate_var = tk.BooleanVar(value=self.cfg.get('auto_translate_fallback', True))
        tk.Checkbutton(api_f, text='✅ تفعيل الترجمة التلقائية',
                       variable=self.auto_translate_var, bg=CARD, fg='white',
                       activebackground=CARD, activeforeground='white',
                       selectcolor='#4fa8ff', font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=(6,2))

        self.auto_translate_silent_var = tk.BooleanVar(value=self.cfg.get('auto_translate_silent', False))
        tk.Checkbutton(api_f, text='🔕 ترجمة صامتة بدون سؤال (مناسب للـ tray/watchdog)',
                       variable=self.auto_translate_silent_var, bg=CARD, fg='white',
                       activebackground=CARD, activeforeground='white',
                       selectcolor='#4fa8ff', font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=(0,10))

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

    def _test_utorrent(self):
        self.ut_status_lbl.configure(text='⏳ جاري الاختبار...', fg='#aaa')
        def _do():
            ok = ut_test_connection(
                host=self._ut_entries['utorrent_host'].get(),
                user=self._ut_entries['utorrent_user'].get(),
                pwd =self._ut_entries['utorrent_pass'].get(),
            )
            self.root.after(0, lambda: self.ut_status_lbl.configure(
                text='✅ اتصال ناجح!' if ok else '❌ فشل — تحقق من uTorrent Web UI',
                fg='#27ae60' if ok else '#e74c3c'
            ))
        threading.Thread(target=_do, daemon=True).start()

    def _save_settings(self):
        self.cfg['watch_folder']             = self.watch_entry.get()
        self.cfg['auto_watch']               = self.auto_watch_var.get()
        self.cfg['start_with_windows']       = self.startup_var.get()
        self.cfg['notifications']            = self.notify_var.get()
        self.cfg['scan_existing_archives']   = self.scan_arch_var.get()
        self.cfg['auto_translate_fallback']  = self.auto_translate_var.get()
        self.cfg['auto_translate_silent']    = self.auto_translate_silent_var.get()
        save_config(self.cfg)
        set_startup(self.cfg['start_with_windows'])
        if self.cfg['auto_watch']:
            start_watchdog(self.cfg['watch_folder'], app_instance=self)
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

    def _clear_stats(self):
        from tkinter import messagebox
        if messagebox.askyesno('مسح السجل', 'هتمسح كل الإحصائيات والسجل. متأكد؟'):
            if db_clear_all():
                self._refresh_stats()
            else:
                messagebox.showerror('خطأ', 'حصل خطأ أثناء المسح')

    def log(self, msg):
        def _do():
            self.log_widget.configure(state='normal')
            self.log_widget.insert('end', msg + '\n')
            current_lines = int(self.log_widget.index('end-1c').split('.')[0])
            if current_lines > 1500:
                self.log_widget.delete('1.0', f'{current_lines - 1000}.0')
            self.log_widget.see('end')
            self.log_widget.configure(state='disabled')
        self.root.after(0, _do)

    def set_status(self, msg):
        self.root.after(0, lambda: self.result_label.configure(text=msg, fg='#4fa8ff'))

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

    def start_background_process(self, paths_list, allow_move=False, skip_icon=False):
        if not paths_list: return
        def _run():
            cancel_ev = threading.Event()
            def _log(msg):
                logging.info(msg)
                self.log(f'[Auto] {msg}')
            run_all(paths_list, None, None, _log, None, cancel_ev, silent=True, allow_move=allow_move, skip_icon=skip_icon)
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
#  نقطة الدخول الرئيسية
# ─────────────────────────────────────────────
if __name__ == '__main__':
    multiprocessing.freeze_support()
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