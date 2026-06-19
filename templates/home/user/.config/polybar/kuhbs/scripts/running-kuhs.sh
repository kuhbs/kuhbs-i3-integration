#!/bin/bash
# Show running and paused qube counts as: running paused
# Use --raw-data because plain qvm-ls prints 'Please wait...' as the first line, which breaks Polybar output.

running_count="$(qvm-ls --raw-data --running | wc -l)"
paused_count="$(qvm-ls --raw-data | grep --count 'Paused')"

printf '%s %s\n' "$running_count" "$paused_count"
