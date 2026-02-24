import pyautogui
import cv2
import numpy as np
import tkinter as tk
import time
import os
import json
import datetime
import hashlib
import requests  # Для отправки на URL
import threading
import sys

# ==================== КОНФИГУРАЦИЯ ====================
CONFIG = {
    "base_folder": "ai_memory_v3",  # Исправлены пробелы
    "max_objects_session": 50,
    "save_cooldown": 2.0,           # Уменьшено для скорости
    "min_object_area": 2500,
    "max_object_area": 150000,
    "capture_context": True,
    "hash_resolution": (64, 64),
    "similarity_threshold": 0.90,
    # Новая функция: отправка данных на сервер
    "upload_enabled": False,        
    "upload_url": "https://your-webhook-url.com/api/memory" 
}

# Пути
BASE_DIR = CONFIG["base_folder"]
GAMES_DIR = os.path.join(BASE_DIR, "games")
LOG_FILE = os.path.join(BASE_DIR, "activity_log.txt")
DB_FILE = os.path.join(BASE_DIR, "database.json")

# Создание структуры папок
for folder in [BASE_DIR, GAMES_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# ==================== БАЗА ДАННЫХ И ПАМЯТЬ ====================
class SmartMemory:
    def __init__(self): # Исправлено __init__
        self.db_path = DB_FILE
        self.data = {"games": {}, "stats": {"total_objects": 0, "sessions": 0}}
        self.known_hashes = set()
        self.load_db()

    def load_db(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                # Загружаем существующие хеши в память для проверки дублей
                self._index_existing_hashes()
                print(f"✅ База загружена. Объектов: {self.data['stats']['total_objects']}")
            except Exception as e:
                print(f"⚠️ Ошибка загрузки базы: {e}")
                self.data = {"games": {}, "stats": {"total_objects": 0, "sessions": 0}}
        else:
            self.save_db()

    def _index_existing_hashes(self):
        # Медленная операция, делается только при старте
        # В реальной версии можно хранить отдельный файл hashes.txt
        pass 

    def save_db(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Ошибка сохранения базы: {e}")

    def get_safe_name(self, title):
        safe = "".join([c if c.isalnum() or c in "_-" else "_" for c in title])
        return safe[:40] if safe else "Unknown_Game"

    def calculate_hash(self, image):
        resized = cv2.resize(image, CONFIG["hash_resolution"])
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        return hashlib.md5(gray.tobytes()).hexdigest()

    def is_duplicate(self, img_hash):
        if img_hash in self.known_hashes:
            return True
        # Здесь можно добавить проверку по всем хешам в DB, если хранить их отдельно
        return False

    def log_discovery(self, game_info, obj_id, roi_path, context_path, position):
        game_key = game_info["safe_name"]
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if game_key not in self.data["games"]:
            self.data["games"][game_key] = {
                "full_name": game_info["name"],
                "first_seen": timestamp,
                "last_seen": timestamp,
                "objects_found": 0,
                "locations": []
            }

        game_data = self.data["games"][game_key]
        game_data["last_seen"] = timestamp
        game_data["objects_found"] += 1
        self.data["stats"]["total_objects"] += 1

        record = {
            "id": obj_id,
            "time": timestamp,
            "coords": position,
            "image_file": os.path.basename(roi_path),
            "context_file": os.path.basename(context_path) if context_path else None
        }
        
        if "recent_objects" not in game_data:
            game_data["recent_objects"] = []
        
        game_data["recent_objects"].insert(0, record)
        if len(game_data["recent_objects"]) > 50:
            game_data["recent_objects"].pop()

        self.save_db()
        self.write_log(game_info, record)
        
        # Новая функция: Отправка на URL
        if CONFIG["upload_enabled"]:
            self.upload_to_url(record, roi_path)

    def upload_to_url(self, record, image_path):
        try:
            # Отправляем метаданные и файл
            files = {'image': open(image_path, 'rb')}
            data = {'json_data': json.dumps(record)}
            response = requests.post(CONFIG["upload_url"], files=files, data=data, timeout=5)
            if response.status_code == 200:
                print(f"📤 Данные отправлены на сервер: {record['id']}")
            else:
                print(f"⚠️ Ошибка отправки: {response.status_code}")
        except Exception as e:
            print(f"❌ Не удалось отправить на URL: {e}")

    def write_log(self, game_info, record):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n[{record['time']}] 🎮 {game_info['name']}\n")
                f.write(f"   🆔 Объект #{record['id']}\n")
                f.write(f"   📍 Координаты: {record['coords']}\n")
                f.write("-" * 40 + "\n")
        except Exception:
            pass

# ==================== ОСНОВНОЙ КЛАСС СИСТЕМЫ ====================
class MemoryCollector:
    def __init__(self): # Исправлено __init__
        self.memory = SmartMemory()
        self.session_count = 0
        self.last_save_time = 0
        self.running = True
        self.paused = False
        
        # Настройка интерфейса
        self.root = tk.Tk()
        self.root.title("AI Memory Collector v3")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.9)
        self.root.geometry("+10+10")
        self.root.overrideredirect(True)
        
        self.lbl_status = tk.Label(self.root, text="🧠 Инициализация...", font=("Consolas", 10),
                                   bg="#1a1a1a", fg="#00ff00", justify="left", padx=15, pady=10)
        self.lbl_status.pack()

        # Обработка закрытия
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

    def get_game_info(self):
        try:
            title = pyautogui.getActiveWindowTitle()
            if not title:
                return {"name": "No_Active_Window", "safe_name": "No_Window"}
            return {
                "name": title,
                "safe_name": self.memory.get_safe_name(title)
            }
        except Exception:
            return {"name": "Error", "safe_name": "Error"}

    def process_frame(self):
        if not self.running:
            return
        
        if self.paused:
            self.lbl_status.config(text="⏸️ ПАУЗА (Нажми P для старта)")
            self.root.after(500, self.process_frame)
            return

        try:
            game_info = self.get_game_info()
            if game_info["safe_name"] == "No_Window":
                self.lbl_status.config(text="⏳ Ожидание активного окна...")
                self.root.after(500, self.process_frame)
                return

            # Скриншот
            screenshot = pyautogui.screenshot()
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Бинаризация (можно улучшить через Canny)
            _, thresh = cv2.threshold(gray, 70, 255, cv2.THRESH_BINARY)
            
            # Поиск контуров
            contours_info = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contours = contours_info[0] if len(contours_info) == 2 else contours_info[1]

            status_text = f"🎮 {game_info['name'][:20]}...\n"
            new_finds = 0

            for cnt in contours:
                area = cv2.contourArea(cnt)
                
                if area < CONFIG["min_object_area"] or area > CONFIG["max_object_area"]:
                    continue

                x, y, w, h = cv2.boundingRect(cnt)
                
                # Пропуск объектов у краев
                if x < 5 or y < 5 or (x+w) > frame.shape[1]-5 or (y+h) > frame.shape[0]-5:
                    continue

                roi = frame[y:y+h, x:x+w]
                img_hash = self.memory.calculate_hash(roi)

                if self.memory.is_duplicate(img_hash):
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 1)
                    continue

                # НОВЫЙ ОБЪЕКТ
                if time.time() - self.last_save_time > CONFIG["save_cooldown"] and \
                   self.session_count < CONFIG["max_objects_session"]:
                    
                    game_folder = os.path.join(GAMES_DIR, game_info["safe_name"])
                    objs_folder = os.path.join(game_folder, "objects")
                    ctx_folder = os.path.join(game_folder, "contexts")
                    
                    for fld in [game_folder, objs_folder, ctx_folder]:
                        if not os.path.exists(fld):
                            os.makedirs(fld)

                    ts = int(time.time() * 1000)
                    obj_name = f"obj_{ts}.png"
                    obj_path = os.path.join(objs_folder, obj_name)
                    cv2.imwrite(obj_path, roi)

                    ctx_path = None
                    if CONFIG["capture_context"]:
                        pad = 20
                        x1, y1 = max(0, x-pad), max(0, y-pad)
                        x2, y2 = min(frame.shape[1], x+w+pad), min(frame.shape[0], y+h+pad)
                        context_roi = frame[y1:y2, x1:x2]
                        ctx_name = f"ctx_{ts}.png"
                        ctx_path = os.path.join(ctx_folder, ctx_name)
                        cv2.imwrite(ctx_path, context_roi)

                    self.memory.known_hashes.add(img_hash)
                    pos_data = {"x": x, "y": y, "w": w, "h": h, "area": int(area)}
                    
                    global_id = self.memory.data["stats"]["total_objects"] + 1
                    self.memory.log_discovery(game_info, global_id, obj_path, ctx_path, pos_data)
                    
                    self.session_count += 1
                    self.last_save_time = time.time()
                    new_finds += 1

                    cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
                    cv2.putText(frame, f"NEW #{global_id}", (x, y-5), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

            total_sess = self.memory.data["stats"]["total_objects"]
            status_text += f"🆕 Сеанс: {self.session_count}/{CONFIG['max_objects_session']}\n"
            status_text += f"💾 Всего: {total_sess}"
            
            if new_finds > 0:
                status_text += f" (+{new_finds})"
                self.lbl_status.config(fg="#ffff00")
            else:
                self.lbl_status.config(fg="#00ff00")
                
            self.lbl_status.config(text=status_text)

        except Exception as e:
            self.lbl_status.config(text=f"❌ Ошибка: {str(e)[:20]}")
            # print(f"Error in loop: {e}") # Можно закомментировать для тишины

        self.root.after(400, self.process_frame)

    def stop(self):
        self.running = False
        self.root.destroy()
        print("\n🛑 Система остановлена.")

    def run(self):
        print("="*50)
        print("🚀 AI Memory Collector v3 запущен")
        print(f"📂 Папка: {os.path.abspath(BASE_DIR)}")
        print("💡 Нажмите 'P' в консоли для паузы/старта")
        print("="*50)
        
        # Поток для обработки клавиш консоли
        threading.Thread(target=self.console_listener, daemon=True).start()
        
        self.root.after(1000, self.process_frame)
        self.root.mainloop()

    def console_listener(self):
        while self.running:
            cmd = input("").lower()
            if cmd == 'p':
                self.paused = not self.paused
                print(f"🔘 Пауза: {'ВКЛ' if self.paused else 'ВЫКЛ'}")
            elif cmd == 'q':
                self.stop()
                break

if __name__ == "__main__": # Исправлено
    try:
        app = MemoryCollector()
        app.run()
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем.")