"""
Ядро очистки. Не зависит от UI, можно тестировать на ПК.

Принципы безопасности:
  * работаем ТОЛЬКО внутри корня общего хранилища (root);
  * папка Android/ (данные других приложений) не трогается никогда;
  * симлинки не обходятся и не удаляются;
  * файлы моложе MIN_AGE_SEC не трогаются (могут быть ещё нужны);
  * перед удалением путь перепроверяется (realpath внутри root, не в защищённых зонах);
  * пользовательские данные (фото, видео, документы, музыка) не удаляются никогда;
  * скан только читает диск - удаляет лишь отдельный вызов clean() после подтверждения.
"""
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

MIN_AGE_SEC = 24 * 3600          # не трогаем файлы моложе суток
LOG_AGE_SEC = 7 * 24 * 3600      # логи чистим, если старше недели

# Папки верхнего уровня, которые не обходим вообще
PROTECTED_TOP = {"android"}
# Стандартные папки: сами по себе никогда не считаются «пустыми папками»
STANDARD_DIRS = {
    "dcim", "pictures", "download", "downloads", "documents", "music",
    "movies", "podcasts", "ringtones", "alarms", "notifications",
    "audiobooks", "recordings", "android", "data", "obb",
}

TEMP_EXT = {".tmp", ".temp", ".cache"}
LOG_EXT = {".log"}


@dataclass
class Item:
    path: str
    size: int
    is_dir: bool = False


@dataclass
class Category:
    key: str
    title: str
    description: str
    icon: str
    items: List[Item] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(i.size for i in self.items)

    @property
    def count(self) -> int:
        return len(self.items)


def make_categories() -> Dict[str, Category]:
    cats = [
        Category("temp", "Временные файлы",
                 "Файлы .tmp, .temp, .cache и копии с ~ старше суток", "file-clock-outline"),
        Category("thumbs", "Кэш миниатюр",
                 "Папки .thumbnails: Android создаст их заново", "image-multiple-outline"),
        Category("logs", "Журналы (логи)",
                 "Файлы .log старше 7 дней", "text-box-outline"),
        Category("apk", "Установочные APK",
                 "Скачанные .apk в папке Загрузки (старше суток)", "android"),
        Category("empty", "Пустые папки",
                 "Пустые папки вне системных и стандартных", "folder-outline"),
    ]
    return {c.key: c for c in cats}


def _size(path: str) -> int:
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def _is_old(path: str, age: float, now: float) -> bool:
    try:
        return now - os.lstat(path).st_mtime >= age
    except OSError:
        return False


def _classify_file(path: str, name: str, parts_lower: List[str], now: float) -> Optional[str]:
    low = name.lower()
    ext = os.path.splitext(low)[1]

    if ".thumbnails" in parts_lower or ".thumbcache" in parts_lower:
        return "thumbs"
    if ext == ".apk" and any(p in ("download", "downloads") for p in parts_lower):
        return "apk" if _is_old(path, MIN_AGE_SEC, now) else None
    if ext in LOG_EXT:
        return "logs" if _is_old(path, LOG_AGE_SEC, now) else None
    if ext in TEMP_EXT or low.endswith("~"):
        return "temp" if _is_old(path, MIN_AGE_SEC, now) else None
    return None


def scan(root: str,
         progress: Optional[Callable[[str], None]] = None,
         cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Category]:
    """Только чтение. Ничего не удаляет."""
    cats = make_categories()
    root = os.path.realpath(root)
    now = time.time()
    flagged_empty = set()
    counter = 0

    # topdown=False: сначала дети, потом родитель - так находим вложенные пустые папки
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        if cancelled and cancelled():
            break

        rel = os.path.relpath(dirpath, root)
        parts = [] if rel == "." else rel.split(os.sep)
        parts_lower = [p.lower() for p in parts]

        if parts_lower and parts_lower[0] in PROTECTED_TOP:
            continue

        counter += 1
        if progress and counter % 50 == 0:
            progress(dirpath)

        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            key = _classify_file(full, name, parts_lower, now)
            if key:
                cats[key].items.append(Item(full, _size(full)))

        # пустая папка?
        if parts and parts_lower[-1] not in STANDARD_DIRS and len(parts) >= 1:
            if os.path.islink(dirpath):
                continue
            try:
                children = os.listdir(dirpath)
            except OSError:
                continue
            all_empty_children = all(
                os.path.join(dirpath, c) in flagged_empty for c in children
            )
            if all_empty_children and _is_old(dirpath, MIN_AGE_SEC, now):
                # .nomedia и подобное - значит папка не пустая (children не пуст и не в flagged)
                flagged_empty.add(dirpath)
                cats["empty"].items.append(Item(dirpath, 0, is_dir=True))

    return cats


def _is_safe_target(path: str, root: str) -> bool:
    if os.path.islink(path):
        return False
    real = os.path.realpath(path)
    root_real = os.path.realpath(root)
    if not real.startswith(root_real + os.sep):
        return False
    rel = os.path.relpath(real, root_real).split(os.sep)
    if rel[0].lower() in PROTECTED_TOP:
        return False
    return True


@dataclass
class CleanResult:
    freed: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: int = 0


def clean(categories: List[Category], root: str,
          progress: Optional[Callable[[int, int], None]] = None) -> CleanResult:
    """Удаляет найденное в выбранных категориях с повторной проверкой каждого пути."""
    res = CleanResult()
    items: List[Item] = [i for c in categories for i in c.items]
    # файлы раньше папок, глубокие папки раньше мелких
    items.sort(key=lambda i: (i.is_dir, -len(i.path)))
    total = len(items)

    for n, it in enumerate(items, 1):
        if progress:
            progress(n, total)
        try:
            if not os.path.lexists(it.path) or not _is_safe_target(it.path, root):
                res.skipped += 1
                continue
            if it.is_dir:
                os.rmdir(it.path)       # rmdir удалит только действительно пустую папку
            else:
                size = _size(it.path)
                os.remove(it.path)
                res.freed += size
            res.deleted += 1
        except OSError:
            res.errors += 1
    return res


def human(n: int) -> str:
    size = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} Б"
