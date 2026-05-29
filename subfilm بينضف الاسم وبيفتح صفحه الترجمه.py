import webbrowser
import re
import os
import sys
import datetime  # لاستخراج السنة الحالية
from tkinter import Tk, Label, Frame
from tkinterdnd2 import DND_FILES, TkinterDnD

def process_and_rename(dropped_path):
    # التحقق مما إذا كان المسحوب مجلداً أو ملفاً
    is_dir = os.path.isdir(dropped_path)
    folder_path = os.path.dirname(dropped_path)
    full_name = os.path.basename(dropped_path)

    valid_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.srt')
    actual_ext = ""

    # استخراج الامتداد فقط إذا كان ملفاً
    if not is_dir:
        for ext in valid_extensions:
            if full_name.lower().endswith(ext):
                actual_ext = ext
                break

    name_part = full_name[:-len(actual_ext)] if actual_ext else full_name

    print(f"[DEBUG] full_name: {full_name}")
    print(f"[DEBUG] name_part: {name_part}")
    print(f"[DEBUG] is_folder: {is_dir}")

    # 1. البحث عن السنة
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', name_part)
    
    # 2. البحث عن الموسم أو الحلقة مع استخراج رقم الموسم (مثال S04)
    season_match = re.search(r'\b[sS](\d{2})(?:[eE]\d{2})?\b', name_part)
    
    # 3. البحث عن الجودات والترميزات
    tech_match = re.search(r'\b(720p|1080p|2160p|480p|WEBRip|WEB-DL|BluRay|x264|x265|HEVC)\b', name_part, re.IGNORECASE)

    cut_index = len(name_part)
    year_found = ""
    season_num = None

    if year_match:
        cut_index = min(cut_index, year_match.start())
        year_found = year_match.group(0)

    if season_match:
        cut_index = min(cut_index, season_match.start())
        season_num = int(season_match.group(1)) # يحول "04" إلى 4

    if tech_match:
        cut_index = min(cut_index, tech_match.start())

    # أخذ اسم الفيلم/المسلسل بناءً على نقطة القص
    if cut_index < len(name_part):
        title_raw = name_part[:cut_index]
    else:
        title_raw = name_part

    # حذف الفاصلة العليا (') لكي تصبح Margo's -> Margos وليس margo-s
    title_raw = title_raw.replace("'", "").replace("’", "")

    # تنظيف الاسم من الرموز والنقاط وتحويلها لمسافات
    clean_title = re.sub(r'[^a-zA-Z0-9]+', ' ', title_raw).strip()
    clean_title = clean_title.title()

    # صناعة الرابط الأساسي (Slug)
    url_slug = clean_title.replace(' ', '-').lower()
    url_slug = re.sub(r'-+', '-', url_slug).strip('-')

    # === الميزة الجديدة: تحديد سنة للرابط ===
    # إذا لم يجد سنة في الاسم، سيستخدم السنة الحالية تلقائياً للرابط
    current_year = str(datetime.datetime.now().year)
    link_year = year_found if year_found else current_year

    # تحديد الاسم الجديد ورابط البحث بناءً على ما إذا كان مسلسل أم فيلم
    if season_num is not None:
        # رابط المسلسلات مع الموسم وسنة الإصدار
        final_url = f"https://subsource.net/subtitles/{url_slug}-{link_year}/season-{season_num}"
        # اسم المجلد الجديد (في حال كان مجلداً)
        new_name = f"{clean_title} S{season_num:02d}"
    else:
        # رابط الأفلام
        final_url = f"https://subsource.net/subtitles/{url_slug}-{link_year}"
        # اسم المجلد الجديد
        new_name = f"{clean_title} ({year_found})" if year_found else clean_title

    print(f"[DEBUG] final_url: {final_url}")
    print(f"[DEBUG] new_folder_name_if_renamed: {new_name}")

    # === تغيير الاسم فقط إذا كان المسحوب "مجلداً Folder" ===
    if is_dir:
        final_file_name = new_name + actual_ext
        new_full_path = os.path.join(folder_path, final_file_name)
        try:
            if dropped_path != new_full_path:
                if not os.path.exists(new_full_path):
                    os.rename(dropped_path, new_full_path)
        except Exception as e:
            print(f"Error: {e}")

    return final_url, new_name

def process_file(dropped_path):
    final_url, friendly_name = process_and_rename(dropped_path)
    
    if final_url:
        webbrowser.open(final_url)
        return friendly_name
    return None

def handle_drop(event):
    # إزالة الأقواس التي تظهر في مسارات الويندوز أحياناً
    dropped_path = event.data.strip('{}')
    new_name = process_file(dropped_path)
    
    if new_name:
        if os.path.isdir(dropped_path):
            status_label.config(text=f"تم تغيير اسم المجلد والبحث!\n{new_name}", fg="#4CAF50")
        else:
            status_label.config(text=f"تم البحث عن الترجمة (بدون تغيير الاسم)\n{new_name}", fg="#2196F3")

# دعم السحب على الأيقونة
if len(sys.argv) > 1:
    process_file(sys.argv[1])
    sys.exit()

# واجهة المستخدم
root = TkinterDnD.Tk()
root.title("Subsource Movie & TV Cleaner")
root.geometry("400x200")
root.configure(bg="#1a1a1a")

drop_frame = Frame(root, bg="#333333", bd=2, relief="groove")
drop_frame.pack(expand=True, fill="both", padx=20, pady=20)

status_label = Label(
    drop_frame,
    text="اسحب الفيلم أو المسلسل هنا\n(الملفات للبحث فقط - المجلدات للبحث وتغيير الاسم)",
    fg="white", bg="#333333", font=("Arial", 10, "bold"), wraplength=350
)
status_label.pack(expand=True)

drop_frame.drop_target_register(DND_FILES)
drop_frame.dnd_bind('<<Drop>>', handle_drop)

root.mainloop()