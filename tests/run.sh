#!/bin/bash
# Run the whole regression suite.   ./tests/run.sh
#
# Everything runs against sandboxed copies of the config, statistics and
# runtime state, so your real settings are never touched.
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
# A terminal inside a snap (an editor, say) exports GTK_PATH and GIO_MODULE_DIR
# pointing into that snap, which makes GTK fail to load here and every GUI
# suite collapse for reasons that have nothing to do with the app.
unset GTK_PATH GIO_MODULE_DIR LD_LIBRARY_PATH GDK_PIXBUF_MODULE_FILE

fails=0
run() {
    printf '%-26s' "$1"; shift
    if out=$("$@" 2>&1); then
        echo "PASS"
    else
        echo "FAIL"
        echo "$out" | grep -E '  FAIL|Error|Traceback' | head -8 | sed 's/^/      /'
        fails=$((fails + 1))
    fi
}
run "lib logic"          bash test_lib.sh
run "daemon lifecycle"   bash test_daemon.sh
run "config quoting"     timeout 150 python3 test_quoting.py
run "alert window"       timeout 90  python3 test_alert.py window
run "alert fullscreen"   timeout 90  python3 test_alert.py fullscreen
run "buzzer backoff"     timeout 90  python3 test_alert.py backoff
run "buzzer loop"        timeout 60  python3 test_alert.py loop
run "buzzer once"        timeout 60  python3 test_alert.py once
run "settings config"    timeout 120 python3 test_settings_io.py
run "settings window"    timeout 200 python3 test_settings_ui.py
echo
[ "$fails" = 0 ] && echo "all suites passed" || echo "$fails suite(s) failed"
exit $fails
