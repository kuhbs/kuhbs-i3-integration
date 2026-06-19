#!/usr/bin/env python3

"""KUHBS GTK control menu for the polybar logo button."""

from __future__ import annotations

import re
import shlex
import subprocess
from math import sqrt
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

# The menu is opened by the Polybar logo at the top-left corner.  Use fixed
# coordinates instead of pointer coordinates so the menu always feels anchored to
# the bar, not to whichever pixel of the logo was clicked.
BAR_HEIGHT = 32
MENU_X = 0
MENU_Y = BAR_HEIGHT
MENU_WIDTH = 250
SUBMENU_WIDTH = 330

PURPLE = "#6400A8"
BG = PURPLE
BG_ALT = "#570092"
BG_HOVER = "#4b007d"
FG = "#f5f2ff"
MUTED = "#e8d9f2"
WINDOW_RADIUS = 14
SQUARE_TOP_LEFT = (0, WINDOW_RADIUS, WINDOW_RADIUS, WINDOW_RADIUS)

FIELD_CODE = re.compile(r"%[fFuUdDnNickvm]")
KUHBS_ICON_WHITE = Path.home() / ".kuhbs/rofi/icons/kuhbs-white.png"
QUBES_ICON = Path.home() / ".kuhbs/rofi/icons/qubes.svg"

QUBES_COMMON_ADMIN_APPS = (
    "/usr/share/applications/qubes-qube-manager.desktop",
    "/usr/share/applications/qubes-new-qube.desktop",
    "/usr/share/applications/qubes-update-gui.desktop",
    "/usr/share/applications/qubes-backup.desktop",
    "/usr/share/applications/qubes-backup-restore.desktop",
)

QUBES_SETTINGS_AND_TOOLS_APPS = (
    "/usr/share/applications/qubes-global-config.desktop",
    "/usr/share/applications/open-qubes-app-menu.desktop",
    "/usr/share/applications/qubes-appmenu-settings.desktop",
    "/usr/share/applications/qubes-template-manager.desktop",
    "/usr/share/applications/qubes-template-switcher.desktop",
    "/usr/share/applications/qubes-policy-editor-gui.desktop",
)

root_menu: Dropdown | None = None
qubes_menu: Dropdown | None = None
click_armed = False

CSS = f"""
window.menu-window {{
  background-color: rgba(0, 0, 0, 0);
  border: 2px solid #6400A8;
  border-radius: 0px 14px 14px 14px;
}}

window.menu-window.submenu {{
  border-radius: 0px 14px 14px 14px;
}}

box.menu-box {{
  background-color: #6400A8;
  border-radius: 0px 12px 12px 12px;
  padding: 8px;
}}

box.menu-box.submenu {{
  border-radius: 0px 12px 12px 12px;
}}

button.menu-button {{
  background-image: none;
  background-color: transparent;
  border: 0;
  border-radius: 8px;
  box-shadow: none;
  text-shadow: none;
  padding: 8px 11px;
  color: {FG};
}}

button.menu-button label {{
  color: {FG};
  text-shadow: none;
  font-weight: 600;
}}

button.menu-button:hover {{
  background-image: none;
  background-color: {BG_HOVER};
}}

button.menu-button:hover label {{
  color: {FG};
}}

separator {{
  background-color: {BG_ALT};
  margin: 5px 8px;
}}
"""

provider = Gtk.CssProvider()
provider.load_from_data(CSS.encode("utf-8"))
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(),
    provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
)


def die(message: str) -> None:
    raise SystemExit(message)


def clean(text: object) -> str:
    return " ".join(str(text).replace("\n", " ").split())


def rounded_region(width: int, height: int, radii: tuple[int, int, int, int]) -> cairo.Region:
    region = cairo.Region()
    if width <= 0 or height <= 0:
        return region

    top_left, top_right, bottom_right, bottom_left = [min(radius, width // 2, height // 2) for radius in radii]
    for y in range(height):
        # Build a shaped X11 window from one-pixel horizontal bands
        # This gives real rounded corners without needing a compositor
        left_inset = 0
        right_inset = 0
        if top_left and y < top_left:
            dy = top_left - y - 0.5
            left_inset = round(top_left - sqrt(max(0, top_left * top_left - dy * dy)))
        elif bottom_left and y >= height - bottom_left:
            dy = y - (height - bottom_left) + 0.5
            left_inset = round(bottom_left - sqrt(max(0, bottom_left * bottom_left - dy * dy)))

        if top_right and y < top_right:
            dy = top_right - y - 0.5
            right_inset = round(top_right - sqrt(max(0, top_right * top_right - dy * dy)))
        elif bottom_right and y >= height - bottom_right:
            dy = y - (height - bottom_right) + 0.5
            right_inset = round(bottom_right - sqrt(max(0, bottom_right * bottom_right - dy * dy)))

        band_width = max(0, width - left_inset - right_inset)
        if band_width > 0:
            region.union(cairo.RectangleInt(left_inset, y, band_width, 1))
    return region


def desktop_id(path: Path) -> str:
    return path.name.removesuffix(".desktop")


def read_desktop(path: Path) -> dict[str, str]:
    # Qubes tools already ship .desktop files.  Reading them keeps labels/icons in
    # sync with the installed system instead of duplicating every command here.
    if not path.is_file():
        die(f"missing desktop file: {path}")

    values: dict[str, str] = {}
    in_entry = False
    for raw_line in path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if line == "[Desktop Entry]":
            in_entry = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_entry = False
            continue
        if not in_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"Name", "Exec", "Icon"} and key not in values:
            values[key] = value

    if "Name" not in values:
        die(f"missing Name in desktop file: {path}")
    if "Exec" not in values:
        die(f"missing Exec in desktop file: {path}")
    return values


def command_from_exec(exec_line: str) -> list[str]:
    # Desktop Exec lines can contain placeholders like %f and %u.  This menu is not
    # opening files/URLs, so strip those field codes before shlex parses the command.
    cleaned = FIELD_CODE.sub("", exec_line).strip()
    try:
        parts = [part for part in shlex.split(cleaned) if part]
    except ValueError as exc:
        die(f"could not parse desktop Exec line: {exec_line}\n{exc}")
    if not parts:
        die(f"empty desktop Exec line after cleanup: {exec_line}")
    return parts


def desktop_command(path: Path, entry: dict[str, str]) -> list[str]:
    gtk_launch = Path("/usr/bin/gtk-launch")
    if gtk_launch.exists():
        return [str(gtk_launch), desktop_id(path)]
    return command_from_exec(entry["Exec"])


def launch(cmd: list[str]) -> None:
    close_all()
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        die(f"missing required command: {cmd[0]}")


def close_submenu() -> None:
    global qubes_menu
    if qubes_menu is not None:
        qubes_menu.destroy()
        qubes_menu = None


def close_all() -> None:
    global root_menu
    close_submenu()
    if root_menu is not None:
        root_menu.destroy()
        root_menu = None
    Gtk.main_quit()


def pointer_state() -> tuple[int, int, Gdk.ModifierType]:
    display = Gdk.Display.get_default()
    seat = display.get_default_seat()
    pointer = seat.get_pointer()
    root_window = Gdk.Screen.get_default().get_root_window()
    _window, x, y, mask = root_window.get_device_position(pointer)
    return x, y, mask


def point_inside_window(window: Gtk.Window | None, x: int, y: int) -> bool:
    if window is None:
        return False
    wx, wy = window.get_position()
    ww, wh = window.get_size()
    return wx <= x <= wx + ww and wy <= y <= wy + wh


def watch_outside_click() -> bool:
    global click_armed
    try:
        x, y, mask = pointer_state()
    except Exception:
        return True

    button_down = bool(mask & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON2_MASK | Gdk.ModifierType.BUTTON3_MASK))

    # The click that opened the menu may still be held down when this timeout first
    # runs.  Do not close immediately; wait until all mouse buttons are released once.
    if not click_armed:
        if not button_down:
            click_armed = True
        return True

    # After arming, any click outside both the root menu and submenu closes the UI.
    if button_down and not point_inside_window(root_menu, x, y) and not point_inside_window(qubes_menu, x, y):
        close_all()
        return False
    return True


class Dropdown(Gtk.Window):
    def __init__(self, x: int, y: int, width: int, is_submenu: bool = False) -> None:
        # POPUP windows avoid normal window-manager decorations and taskbar entries.
        # i3 still lets us position them manually with move() in show_menu().
        super().__init__(type=Gtk.WindowType.POPUP)
        self.x = x
        self.y = y
        self.corner_radii = SQUARE_TOP_LEFT
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_size_request(width, -1)
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)
        self.get_style_context().add_class("menu-window")
        if is_submenu:
            self.get_style_context().add_class("submenu")
        self.connect("draw", self.on_draw)
        self.connect("size-allocate", self.on_size_allocate)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.get_style_context().add_class("menu-box")
        if is_submenu:
            self.box.get_style_context().add_class("submenu")
        self.add(self.box)
        self.connect("key-press-event", self.on_key_press)

    def on_draw(self, _widget: Gtk.Widget, cr) -> bool:
        # Clear the popup before GTK paints the purple menu content
        # The shaped window below removes the corner pixels on non-composited i3
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False

    def on_size_allocate(self, _widget: Gtk.Widget, _allocation: Gdk.Rectangle) -> None:
        self.apply_window_shape()

    def apply_window_shape(self) -> bool:
        width, height = self.get_size()
        if width > 0 and height > 0:
            self.shape_combine_region(rounded_region(width, height, self.corner_radii))
        return False

    def on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> None:
        if event.keyval == Gdk.KEY_Escape:
            close_all()

    def add_separator(self) -> None:
        self.box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

    def add_item(self, label: str, cmd: list[str] | None = None, icon: str | None = None, submenu=None, close_submenu_on_hover: bool = False) -> None:
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_can_focus(False)
        button.set_focus_on_click(False)
        button.get_style_context().add_class("menu-button")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        if icon:
            # Accept both absolute/custom icon files and regular themed icon names.
            # Qubes desktop files usually provide themed names; KUHBS assets use paths.
            icon_path = Path(icon).expanduser()
            if icon_path.is_file():
                image = Gtk.Image.new_from_file(str(icon_path))
                image.set_pixel_size(16)
            else:
                image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
            row.pack_start(image, False, False, 0)

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

    def add_desktop_item(self, path_text: str) -> None:
        path = Path(path_text)
        entry = read_desktop(path)
        self.add_item(clean(entry["Name"]), desktop_command(path, entry), entry.get("Icon", "qubes"))

    def show_menu(self) -> None:
        self.move(self.x, self.y)
        self.show_all()
        self.apply_window_shape()

        def force_position() -> bool:
            self.move(self.x, self.y)
            self.apply_window_shape()
            return False

        GLib.idle_add(force_position)
        GLib.timeout_add(25, force_position)
        GLib.timeout_add(100, force_position)


def open_qubes_menu(parent_button: Gtk.Button) -> None:
    global qubes_menu
    if qubes_menu is not None:
        return

    if root_menu is None:
        die("root menu is not open")

    # The submenu should line up with the hovered Qubes row, not with the pointer.
    # GTK gives the row allocation relative to the root menu, so add it to the menu
    # window position and place the submenu directly to the right.
    root_x, root_y = root_menu.get_position()
    root_w, _root_h = root_menu.get_size()
    allocation = parent_button.get_allocation()

    qubes_menu = Dropdown(root_x + root_w, root_y + allocation.y, SUBMENU_WIDTH, is_submenu=True)
    qubes_menu.add_item("Kuhbs Gui", ["/usr/bin/kuhbs-gui"], str(KUHBS_ICON_WHITE))
    qubes_menu.add_separator()

    for path in QUBES_COMMON_ADMIN_APPS:
        qubes_menu.add_desktop_item(path)
    qubes_menu.add_separator()
    for path in QUBES_SETTINGS_AND_TOOLS_APPS:
        qubes_menu.add_desktop_item(path)

    qubes_menu.show_menu()


def build_root_menu() -> None:
    global root_menu
    root_menu = Dropdown(MENU_X, MENU_Y, MENU_WIDTH)
    root_menu.add_item("Settings", ["xfce4-settings-manager"], "preferences-system", close_submenu_on_hover=True)
    root_menu.add_item("Qubes", icon=str(QUBES_ICON), submenu=open_qubes_menu)
    root_menu.add_separator()
    root_menu.add_item("Terminal in dom0", ["xfce4-terminal"], "utilities-terminal", close_submenu_on_hover=True)
    root_menu.add_separator()
    root_menu.add_item("Log Out", ["i3-msg", "exit"], "system-log-out", close_submenu_on_hover=True)
    root_menu.add_item("Reboot", ["systemctl", "reboot"], "system-reboot", close_submenu_on_hover=True)
    root_menu.add_item("Shutdown", ["systemctl", "poweroff"], "system-shutdown", close_submenu_on_hover=True)
    root_menu.show_menu()


build_root_menu()
GLib.timeout_add(50, watch_outside_click)
Gtk.main()
