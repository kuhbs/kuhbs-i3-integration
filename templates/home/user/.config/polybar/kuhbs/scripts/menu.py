#!/usr/bin/env python3

import subprocess
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

BAR_HEIGHT = 32
MENU_Y = BAR_HEIGHT
MENU_X = 0

BAR_COLOR = "#338dcc"

MENU_BG = "#f5f5f7"
MENU_FG = "#1d1d1f"
MENU_WIDTH = 250
SUBMENU_WIDTH = 315

root_menu = None
qubes_menu = None
click_armed = False

css = f"""
window.menu-window {{
  background-color: {MENU_BG};
}}

box.menu-box {{
  background-color: {MENU_BG};
  padding: 7px;
}}

button.menu-button {{
  background-image: none;
  background-color: transparent;
  border: 0px;
  border-radius: 8px;
  box-shadow: none;
  text-shadow: none;
  padding: 8px 12px;
  color: {MENU_FG};
}}

button.menu-button label {{
  color: {MENU_FG};
  text-shadow: none;
  font-weight: 600;
}}

button.menu-button:hover {{
  background-image: none;
  background-color: {BAR_COLOR};
  color: #ffffff;
}}

button.menu-button:hover label {{
  color: #ffffff;
}}

button.menu-button:active {{
  background-image: none;
  background-color: {BAR_COLOR};
  color: #ffffff;
}}

button.menu-button:active label {{
  color: #ffffff;
}}

separator {{
  margin: 5px 8px;
}}
"""

provider = Gtk.CssProvider()
provider.load_from_data(css.encode("utf-8"))
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(),
    provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
)


def launch(cmd):
    close_all()
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def close_submenu():
    global qubes_menu

    if qubes_menu is not None:
        qubes_menu.destroy()
        qubes_menu = None


def close_all():
    global root_menu, qubes_menu

    close_submenu()

    if root_menu is not None:
        root_menu.destroy()
        root_menu = None

    Gtk.main_quit()


def pointer_state():
    display = Gdk.Display.get_default()
    seat = display.get_default_seat()
    pointer = seat.get_pointer()
    root_window = Gdk.Screen.get_default().get_root_window()
    _window, x, y, mask = root_window.get_device_position(pointer)
    return x, y, mask


def point_inside_window(window, x, y):
    if window is None:
        return False

    wx, wy = window.get_position()
    ww, wh = window.get_size()

    return wx <= x <= wx + ww and wy <= y <= wy + wh


def watch_outside_click():
    global click_armed

    try:
        x, y, mask = pointer_state()
    except Exception:
        return True

    button_down = bool(
        mask
        & (
            Gdk.ModifierType.BUTTON1_MASK
            | Gdk.ModifierType.BUTTON2_MASK
            | Gdk.ModifierType.BUTTON3_MASK
        )
    )

    if not click_armed:
        if not button_down:
            click_armed = True
        return True

    inside_root = point_inside_window(root_menu, x, y)
    inside_qubes = point_inside_window(qubes_menu, x, y)

    if button_down and not inside_root and not inside_qubes:
        close_all()
        return False

    return True


class Dropdown(Gtk.Window):
    def __init__(self, x, y, width):
        super().__init__(type=Gtk.WindowType.POPUP)

        self.x = x
        self.y = y

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_size_request(width, -1)

        self.get_style_context().add_class("menu-window")

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.get_style_context().add_class("menu-box")
        self.add(self.box)

        self.connect("key-press-event", self.on_key_press)

    def on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            close_all()

    def add_separator(self):
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.box.pack_start(sep, False, False, 0)

    def add_item(self, label, cmd=None, submenu=None, close_submenu_on_hover=False):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_can_focus(False)
        button.set_focus_on_click(False)
        button.get_style_context().add_class("menu-button")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        text = Gtk.Label(label=label)
        text.set_xalign(0)
        row.pack_start(text, True, True, 0)

        if submenu is not None:
            arrow = Gtk.Label(label="›")
            arrow.set_xalign(1)
            row.pack_end(arrow, False, False, 0)

            button.connect("enter-notify-event", lambda *_: submenu(button))
            button.connect("clicked", lambda *_: submenu(button))

        else:
            if close_submenu_on_hover:
                button.connect("enter-notify-event", lambda *_: close_submenu())

            if cmd is not None:
                button.connect("clicked", lambda *_: launch(cmd))

        button.add(row)
        self.box.pack_start(button, False, False, 0)

    def show_menu(self):
        self.move(self.x, self.y)
        self.show_all()

        def force_position():
            self.move(self.x, self.y)
            return False

        GLib.idle_add(force_position)
        GLib.timeout_add(25, force_position)
        GLib.timeout_add(100, force_position)


def open_qubes_menu(parent_button):
    global qubes_menu

    if qubes_menu is not None:
        return

    root_x, root_y = root_menu.get_position()
    root_w, _root_h = root_menu.get_size()

    allocation = parent_button.get_allocation()

    submenu_x = root_x + root_w
    submenu_y = root_y + allocation.y

    qubes_menu = Dropdown(submenu_x, submenu_y, SUBMENU_WIDTH)

    qubes_menu.add_item("🐟  Kuhbs Gui", ["/usr/bin/kuhbs-gui"])
    qubes_menu.add_separator()

    qubes_menu.add_item("🗂️  Qubes Qube Manager", ["qubes-qube-manager"])
    qubes_menu.add_item("➕  Qubes New Qube", ["qubes-new-qube"])
    qubes_menu.add_item("🌐  Qubes Global Config", ["qubes-global-config"])
    qubes_menu.add_separator()

    qubes_menu.add_item("⬆️  Qubes Update Gui", ["qubes-update-gui"])
    qubes_menu.add_item("🛡️  Qubes Policy Editor Gui", ["qubes-policy-editor-gui"])
    qubes_menu.add_item("📦  Qvm Template Gui", ["qvm-template-gui"])
    qubes_menu.add_separator()

    qubes_menu.add_item("💾  Qubes Backup", ["qubes-backup"])
    qubes_menu.add_item("♻️  Qubes Backup Restore", ["qubes-backup-restore"])

    qubes_menu.show_menu()


def build_root_menu():
    global root_menu

    root_menu = Dropdown(MENU_X, MENU_Y, MENU_WIDTH)

    root_menu.add_item("⚙️  Settings", ["xfce4-settings-manager"], close_submenu_on_hover=True)
    root_menu.add_item("🧊  Qubes", submenu=open_qubes_menu)
    root_menu.add_separator()

    root_menu.add_item("💻  Terminal", ["xfce4-terminal"], close_submenu_on_hover=True)
    root_menu.add_separator()

    root_menu.add_item("🚪  Log Out", ["i3-msg", "exit"], close_submenu_on_hover=True)
    root_menu.add_item("🔄  Restart", ["systemctl", "reboot"], close_submenu_on_hover=True)
    root_menu.add_item("⏻  Shutdown", ["systemctl", "poweroff"], close_submenu_on_hover=True)

    root_menu.show_menu()


build_root_menu()
GLib.timeout_add(50, watch_outside_click)
Gtk.main()
