import os
import sys
import re
import shutil

def clean_media_file(file_path):
    if not os.path.isfile(file_path):
        return

    # استخراج المسار، اسم الملف، والامتداد
    dir_name = os.path.dirname(file_path)
    file_full_name = os.path.basename(file_path)
    file_name, file_ext = os.path.splitext(file_full_name)

    # 1. حالة المسلسلات: البحث عن S01, S02... إلخ
    series_match = re.search(r'(.*?)\.S\d+', file_name, re.IGNORECASE)
    
    # 2. حالة الأفلام: البحث عن سنة (19xx أو 20xx)
    movie_match = re.search(r'(.*?)\.((?:19|20)\d{2})', file_name)

    new_folder_name = ""

    if series_match:
        # تنظيف اسم المسلسل (تبديل النقط بمسافات)
        name = series_match.group(1).replace('.', ' ').strip()
        new_folder_name = name
    
    elif movie_match:
        # تنظيف اسم الفيلم + السنة بين قوسين
        name = movie_match.group(1).replace('.', ' ').strip()
        year = movie_match.group(2)
        new_folder_name = f"{name} ({year})"
    
    # إذا تم تحديد اسم فولدر جديد
    if new_folder_name:
        target_dir = os.path.join(dir_name, new_folder_name)
        
        # إنشاء الفولدر لو مش موجود
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        
        # نقل الملف للفولدر الجديد
        try:
            shutil.move(file_path, os.path.join(target_dir, file_full_name))
            print(f"Done: {new_folder_name}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # التأكد من تمرير ملف كـ argument
    if len(sys.argv) > 1:
        clean_media_file(sys.argv[1])