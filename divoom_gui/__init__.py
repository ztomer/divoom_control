"""divoom_gui — the desktop Control Center (pywebview) presentation layer.

Pure presentation: the window launcher (`gui_main`), the Python<->JS bridge
(`gui_api`), and the web UI (`web_ui/`). Background device-driving lives in
`divoom_client`; the protocol/device library is `divoom_lib`. See
docs/PLANNING_ROUND17.md for the 3-way split.
"""
