# KUHBS i3 integration

WORK IN PROGRESS

Optional Qubes dom0 desktop integration for KUHBS: i3, Polybar, rofi launcher/menu assets, terminal styling, fonts, and X resources.

This repo is intentionally separate from KUHBS core. KUHBS can create/manage kuhs without requiring i3, Polybar, or rofi.

## Install

Run from dom0:

```bash
bash install.sh
```

The installer copies files from `templates/` into the matching dom0 locations under `/home/user`, `/etc/X11`, and refreshes the user font cache when available.
