"""
Чистильщик: тёмный интерфейс на KivyMD 1.2.0, без рекламы и без сети.
Android 11+: для доступа к общему хранилищу нужно разрешение
«Доступ ко всем файлам» (MANAGE_EXTERNAL_STORAGE), его выдаёт пользователь в настройках.
"""
import os
import threading

from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Line
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog

import cleaner_core as core

if platform == "android":
    from jnius import autoclass
    ROOT = "/storage/emulated/0"
else:
    ROOT = os.path.expanduser("~/cleaner_test")
    os.makedirs(ROOT, exist_ok=True)
    Window.size = (390, 800)


KV = """
#:import human cleaner_core.human

<Gauge>:
    size_hint: None, None
    size: dp(190), dp(190)
    pos_hint: {"center_x": .5}
    MDLabel:
        text: root.big_text
        halign: "center"
        font_style: "H4"
        bold: True
        theme_text_color: "Custom"
        text_color: "#FFFFFF"
        pos: root.x, root.center_y - dp(6)
        size_hint: None, None
        size: root.width, dp(44)
    MDLabel:
        text: root.small_text
        halign: "center"
        font_style: "Caption"
        theme_text_color: "Custom"
        text_color: "#8A93A6"
        pos: root.x, root.center_y - dp(34)
        size_hint: None, None
        size: root.width, dp(24)

<CategoryCard>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(76)
    padding: dp(14), dp(8)
    spacing: dp(12)
    radius: [dp(18)]
    md_bg_color: "#171A21"
    elevation: 0
    MDIcon:
        icon: root.icon
        theme_text_color: "Custom"
        text_color: "#4DD0A7"
        size_hint: None, None
        size: dp(32), dp(32)
        pos_hint: {"center_y": .5}
        font_size: "28sp"
    BoxLayout:
        orientation: "vertical"
        pos_hint: {"center_y": .5}
        MDLabel:
            text: root.title
            font_style: "Subtitle1"
            theme_text_color: "Custom"
            text_color: "#FFFFFF"
            shorten: True
        MDLabel:
            text: root.subtitle
            font_style: "Caption"
            theme_text_color: "Custom"
            text_color: "#8A93A6"
            shorten: True
    MDLabel:
        text: root.size_text
        halign: "right"
        size_hint_x: None
        width: dp(78)
        theme_text_color: "Custom"
        text_color: "#4DD0A7" if root.has_items else "#5A6275"
        font_style: "Subtitle2"
    MDCheckbox:
        size_hint: None, None
        size: dp(36), dp(36)
        pos_hint: {"center_y": .5}
        active: root.checked
        disabled: not root.has_items
        selected_color: "#4DD0A7"
        unselected_color: "#5A6275"
        on_active: root.checked = self.active

MDScreen:
    md_bg_color: "#0E1014"
    BoxLayout:
        orientation: "vertical"
        padding: dp(18), dp(28), dp(18), dp(14)
        spacing: dp(14)

        MDLabel:
            text: "Чистильщик"
            font_style: "H5"
            bold: True
            size_hint_y: None
            height: dp(34)
            theme_text_color: "Custom"
            text_color: "#FFFFFF"

        Gauge:
            id: gauge

        MDLabel:
            id: status
            text: app.status_text
            halign: "center"
            font_style: "Body2"
            size_hint_y: None
            height: dp(40)
            theme_text_color: "Custom"
            text_color: "#8A93A6"

        ScrollView:
            do_scroll_x: False
            bar_width: 0
            BoxLayout:
                id: cards
                orientation: "vertical"
                spacing: dp(10)
                size_hint_y: None
                height: self.minimum_height

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(12)
            MDRaisedButton:
                text: "СКАНИРОВАТЬ"
                md_bg_color: "#222733"
                theme_text_color: "Custom"
                text_color: "#FFFFFF"
                size_hint_x: .5
                disabled: app.busy
                on_release: app.start_scan()
            MDRaisedButton:
                text: "ОЧИСТИТЬ"
                md_bg_color: "#4DD0A7"
                theme_text_color: "Custom"
                text_color: "#07281E"
                size_hint_x: .5
                disabled: app.busy or not app.can_clean
                on_release: app.confirm_clean()
"""


class Gauge(BoxLayout):
    """Круговой индикатор занятого места."""
    value = NumericProperty(0.0)          # 0..1
    big_text = StringProperty("—")
    small_text = StringProperty("")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, value=self._draw)

    def _draw(self, *_):
        self.canvas.before.clear()
        cx, cy = self.center
        r = min(self.width, self.height) / 2 - 12
        with self.canvas.before:
            Color(0.13, 0.15, 0.2, 1)
            Line(circle=(cx, cy, r), width=9, cap="round")
            Color(0.30, 0.82, 0.65, 1)
            Line(circle=(cx, cy, r, 0, 360 * max(0.01, self.value)),
                 width=9, cap="round")


class CategoryCard(MDCard):
    key = StringProperty("")
    title = StringProperty("")
    subtitle = StringProperty("")
    icon = StringProperty("broom")
    size_text = StringProperty("—")
    has_items = BooleanProperty(False)
    checked = BooleanProperty(False)


class CleanerApp(MDApp):
    status_text = StringProperty("Нажмите «Сканировать», чтобы найти ненужные файлы")
    busy = BooleanProperty(False)
    can_clean = BooleanProperty(False)

    def build(self):
        self.title = "Чистильщик"
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Teal"
        self.categories = core.make_categories()
        self.cancel_flag = False
        self.dialog = None
        self.root_widget = Builder.load_string(KV)
        self._build_cards()
        return self.root_widget

    def on_start(self):
        self.update_storage_gauge()
        if platform == "android" and not self._has_all_files_access():
            Clock.schedule_once(lambda dt: self._ask_permission(), 0.6)

    # ---------- разрешения Android 11+ ----------
    def _has_all_files_access(self):
        Environment = autoclass("android.os.Environment")
        return Environment.isExternalStorageManager()

    def _ask_permission(self):
        self._show_dialog(
            "Нужен доступ к файлам",
            "Чтобы находить мусор в памяти телефона, Android требует разрешение "
            "«Доступ ко всем файлам». Приложение работает без интернета, "
            "ничего не отправляет и не трогает папку Android/ других программ.",
            [MDFlatButton(text="ПОЗЖЕ", on_release=lambda *_: self._close_dialog()),
             MDRaisedButton(text="ОТКРЫТЬ НАСТРОЙКИ",
                            on_release=lambda *_: self._open_settings())])

    def _open_settings(self):
        self._close_dialog()
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
        intent.setData(Uri.parse("package:" + activity.getPackageName()))
        activity.startActivity(intent)

    # ---------- интерфейс ----------
    def _build_cards(self):
        box = self.root_widget.ids.cards
        self.cards = {}
        for key, cat in self.categories.items():
            card = CategoryCard(key=key, title=cat.title,
                                subtitle=cat.description, icon=cat.icon)
            self.cards[key] = card
            box.add_widget(card)

    def update_storage_gauge(self):
        try:
            st = os.statvfs(ROOT)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            g = self.root_widget.ids.gauge
            g.value = used / total if total else 0
            g.big_text = f"{int(g.value * 100)}%"
            g.small_text = f"занято {core.human(used)} из {core.human(total)}"
        except OSError:
            pass

    def _show_dialog(self, title, text, buttons):
        self._close_dialog()
        self.dialog = MDDialog(title=title, text=text, buttons=buttons)
        self.dialog.open()

    def _close_dialog(self):
        if self.dialog:
            self.dialog.dismiss()
            self.dialog = None

    # ---------- сканирование ----------
    def start_scan(self):
        if platform == "android" and not self._has_all_files_access():
            self._ask_permission()
            return
        self.busy = True
        self.can_clean = False
        self.status_text = "Сканирую…"
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            cats = core.scan(ROOT, progress=self._scan_progress)
        except Exception as e:                      # не роняем приложение
            self._scan_failed(str(e))
            return
        self._scan_done(cats)

    @mainthread
    def _scan_progress(self, path):
        name = os.path.basename(path) or path
        self.status_text = f"Сканирую: {name[:34]}"

    @mainthread
    def _scan_failed(self, msg):
        self.busy = False
        self.status_text = "Не удалось выполнить сканирование"

    @mainthread
    def _scan_done(self, cats):
        self.categories = cats
        total = 0
        for key, cat in cats.items():
            card = self.cards[key]
            card.has_items = cat.count > 0
            card.checked = cat.count > 0
            card.size_text = core.human(cat.total) if cat.count else "чисто"
            total += cat.total
        self.busy = False
        self.can_clean = any(c.count for c in cats.values())
        self.status_text = (f"Можно освободить {core.human(total)}"
                            if self.can_clean else "Ничего лишнего не найдено")

    # ---------- очистка ----------
    def _selected(self):
        return [self.categories[k] for k, card in self.cards.items()
                if card.checked and self.categories[k].count]

    def confirm_clean(self):
        selected = self._selected()
        if not selected:
            self.status_text = "Выберите хотя бы одну категорию"
            return
        n = sum(c.count for c in selected)
        size = sum(c.total for c in selected)
        self._show_dialog(
            "Удалить выбранное?",
            f"Будет удалено объектов: {n}\nОсвободится: {core.human(size)}\n\n"
            "Удаление необратимо. Фото, видео, документы и музыка не затрагиваются.",
            [MDFlatButton(text="ОТМЕНА", on_release=lambda *_: self._close_dialog()),
             MDRaisedButton(text="УДАЛИТЬ", on_release=lambda *_: self._do_clean())])

    def _do_clean(self):
        selected = self._selected()
        self._close_dialog()
        self.busy = True
        self.status_text = "Очищаю…"
        threading.Thread(target=self._clean_worker, args=(selected,),
                         daemon=True).start()

    def _clean_worker(self, selected):
        res = core.clean(selected, ROOT)
        self._clean_done(res)

    @mainthread
    def _clean_done(self, res):
        self.busy = False
        self.can_clean = False
        for card in self.cards.values():
            card.has_items = False
            card.checked = False
            card.size_text = "—"
        self.update_storage_gauge()
        extra = f" (пропущено: {res.skipped}, ошибок: {res.errors})" if res.skipped or res.errors else ""
        self.status_text = f"Готово: освобождено {core.human(res.freed)}{extra}"


if __name__ == "__main__":
    CleanerApp().run()
