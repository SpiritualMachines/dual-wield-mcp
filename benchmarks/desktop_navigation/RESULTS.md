
## 2026-07-27T16:38:15+00:00 -- v1.6.0

- **kwrite_menu_and_about**: FAIL
  - launch_app: ok (10ms) -- launched kwrite
  - wait_for_window: ok (779ms) -- Welcome — KWrite
  - menu_bar_reads_as_one_line: ok (3325ms) -- File Edit Selection View Go Tools Settings Help
  - open_help_menu_via_mnemonic: ok (3333ms) -- 1 raw match(es) on screen, in-window: True
  - click_about_kwrite: ok (549ms) -- About KWrite dialog opened
  - read_about_dialog_content: ok (2928ms) -- 11 line(s) in dialog bounds: '| | | About KWrite | Vax | KWrite | Version 26.04.3 | Thanks To | About Components Authors | KWrite - Text Editor | (0) '
  - close_about_dialog: FAIL (2799ms) -- Close button not found in dialog bounds
- **dolphin_file_listing_and_navigation**: PASS
  - launch_app: ok (1ms) -- /home/whitewizard/Documents/Development/27-dual-wield-mcp/benchmarks/desktop_navigation/fixture_dir
  - wait_for_window: ok (739ms) -- fixture_dir — Dolphin
  - bulk_read_file_listing: ok (3380ms) -- found ['alpha_report.txt', 'charlie_notes.md', 'echo_archive.zip', 'delta_folder'], missing ['bravo_photo.png']
  - navigate_into_folder: ok (3074ms) -- active window title: 'delta_folder — Dolphin'

## 2026-07-27T16:58:09+00:00 -- v1.6.0

- **kwrite_menu_and_about**: FAIL
  - launch_app: ok (3ms) -- launched kwrite
  - wait_for_window: ok (751ms) -- Welcome — KWrite
  - menu_bar_reads_as_one_line: ok (2786ms) -- File Edit Selection View Go Tools Settings Help
  - open_help_menu_via_mnemonic: ok (1925ms) -- 1 in-window match(es)
  - click_about_kwrite: ok (585ms) -- About KWrite dialog opened
  - read_about_dialog_content: FAIL (1320ms) -- 10 line(s) in dialog: '| | | About KWrite | Var | KWrite | Version 26.04.3 | About Components Authors | Thanks To | KWrite - Text Editor | (c) '
  - close_about_dialog: ok (1505ms) -- clicked Close
- **dolphin_file_listing_and_navigation**: PASS
  - launch_app: ok (3ms) -- /home/whitewizard/Documents/Development/27-dual-wield-mcp/benchmarks/desktop_navigation/fixture_dir
  - wait_for_window: ok (855ms) -- fixture_dir — Dolphin
  - bulk_read_file_listing: ok (1722ms) -- found ['alpha_report.txt', 'bravo_photo.png', 'charlie_notes.md', 'echo_archive.zip', 'delta_folder'], missing []
  - navigate_into_folder: ok (2024ms) -- active window title: 'delta_folder — Dolphin'

## 2026-07-27T17:00:38+00:00 -- v1.6.0

- **kwrite_menu_and_about**: PASS
  - launch_app: ok (3ms) -- launched kwrite
  - wait_for_window: ok (757ms) -- Welcome — KWrite
  - menu_bar_reads_as_one_line: ok (3538ms) -- File Edit Selection View Go Tools Settings Help
  - open_help_menu_via_mnemonic: ok (1966ms) -- 1 in-window match(es)
  - click_about_kwrite: ok (525ms) -- About KWrite dialog opened
  - read_about_dialog_content: ok (3724ms) -- 76 total line(s) on screen, dialog content present: True
  - close_about_dialog: ok (1525ms) -- clicked Close
- **dolphin_file_listing_and_navigation**: PASS
  - launch_app: ok (5ms) -- /home/whitewizard/Documents/Development/27-dual-wield-mcp/benchmarks/desktop_navigation/fixture_dir
  - wait_for_window: ok (1180ms) -- fixture_dir — Dolphin
  - bulk_read_file_listing: ok (1782ms) -- found ['alpha_report.txt', 'bravo_photo.png', 'charlie_notes.md', 'echo_archive.zip', 'delta_folder'], missing []
  - navigate_into_folder: ok (1952ms) -- active window title: 'delta_folder — Dolphin'

## 2026-07-27T17:06:48+00:00 -- v1.7.0

- **kwrite_menu_and_about**: PASS
  - launch_app: ok (8ms) -- launched kwrite
  - wait_for_window: ok (776ms) -- Welcome — KWrite
  - menu_bar_reads_as_one_line: ok (3146ms) -- File Edit Selection View Go Tools Settings Help
  - open_help_menu_via_mnemonic: ok (1760ms) -- 1 in-window match(es)
  - click_about_kwrite: ok (558ms) -- About KWrite dialog opened
  - read_about_dialog_content: ok (2828ms) -- 93 total line(s) on screen, dialog content present: True
  - close_about_dialog: ok (1375ms) -- clicked Close
- **dolphin_file_listing_and_navigation**: PASS
  - launch_app: ok (5ms) -- /home/whitewizard/Documents/Development/27-dual-wield-mcp/benchmarks/desktop_navigation/fixture_dir
  - wait_for_window: ok (1123ms) -- fixture_dir — Dolphin
  - bulk_read_file_listing: ok (1553ms) -- found ['alpha_report.txt', 'bravo_photo.png', 'charlie_notes.md', 'echo_archive.zip', 'delta_folder'], missing []
  - navigate_into_folder: ok (1924ms) -- active window title: 'delta_folder — Dolphin'
