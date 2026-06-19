#!/bin/bash
#
# Install optional KUHBS i3/Polybar/rofi desktop integration for dom0
# KUHBS core does not depend on these files; this repo owns desktop polish only
# The installer is rerunnable and preserves unrelated files in existing dirs

set -o errexit -o nounset -o pipefail
set -o xtrace



# Use paths relative to this installer so it can be run from any directory
cd "$(dirname "$0")"


# Desktop integration packages
sudo qubes-dom0-update \
    brightnessctl \
    gnome-screenshot \
    i3 \
    i3lock \
    i3-settings-qubes \
    polybar \
    python3-cairo \
    python3-gobject \
    python3-pyyaml \
    redshift \
    rofi


# User-owned desktop configuration and launcher assets stay user-owned without sudo
install --verbose --directory --mode=0755 /home/user/.config
install --verbose --directory --mode=0755 /home/user/.config/i3
install --verbose --directory --mode=0755 /home/user/.config/i3/config.d
install --verbose --directory --mode=0755 /home/user/.config/polybar
install --verbose --directory --mode=0755 /home/user/.config/systemd
install --verbose --directory --mode=0755 /home/user/.config/systemd/user
install --verbose --directory --mode=0755 /home/user/.config/xfce4
install --verbose --directory --mode=0755 /home/user/.kuhbs
install --verbose --directory --mode=0755 /home/user/.kuhbs/rofi
install --verbose --directory --mode=0755 /home/user/.local/share/fonts

cp --archive --verbose templates/home/user/.config/i3/. /home/user/.config/i3/
cp --archive --verbose templates/home/user/.config/polybar/. /home/user/.config/polybar/
cp --archive --verbose templates/home/user/.config/systemd/. /home/user/.config/systemd/
cp --archive --verbose templates/home/user/.config/xfce4/. /home/user/.config/xfce4/
cp --archive --verbose templates/home/user/.kuhbs/rofi/. /home/user/.kuhbs/rofi/
cp --archive --verbose templates/home/user/.bashrc /home/user/.bashrc
cp --archive --verbose templates/home/user/.local/share/fonts/. /home/user/.local/share/fonts/


# Refresh the user font cache so Polybar can see the KUHBS logo and Polybar icon fonts
fc-cache --force --verbose /home/user/.local/share/fonts
fc-match 'Kuhbs Icons' | grep --quiet 'kuhbs-icons'
fc-match 'Iosevka Nerd Font' | grep --quiet 'Iosevka'

# Restart i3 so copied config and KUHBS drop-in include rules are active now
i3-msg restart


# User services need the live i3/X environment before they can talk to i3.
systemctl --user import-environment DISPLAY XAUTHORITY I3SOCK DBUS_SESSION_BUS_ADDRESS
systemctl --user daemon-reload
systemctl --user enable --now kuhbs-qvm-autopause.service
systemctl --user restart kuhbs-qvm-autopause.service
systemctl --user enable --now kuhbs-workspace-attention.service
systemctl --user restart kuhbs-workspace-attention.service


# Restart polybar
# killall polybar
# sleep 0.5
# /usr/bin/polybar --quiet main --config=~/.config/polybar/kuhbs/config.ini &


echo 'KUHBS i3 integration install complete.'
