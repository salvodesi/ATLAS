import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from arcadia_tool import APP_NAME
from arcadia_tool.ui.accounts import require_login
from arcadia_tool.ui.branding import app_icon
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.theme import apply_theme


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("RFI")
    app.setWindowIcon(app_icon())
    apply_theme(app)
    window = MainWindow()
    window.showMaximized()  # the default size (1440x880) is used when the window is restored
    app.processEvents()  # maximized before the login window is centered on it
    # A local account is mandatory: every published change is associated with a user, and the account holds
    # the credentials for the Git remotes. Without it the tool closes.
    account = require_login(window)
    if account is None:
        return 0
    window.set_user(account)
    if len(sys.argv) > 1:
        window.open_project(sys.argv[1])
    else:
        # After the window is shown: offers to restore the edits of a session that ended unexpectedly.
        QTimer.singleShot(0, window.check_interrupted_sessions)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
