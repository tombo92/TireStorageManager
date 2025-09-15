from app.controller.app_controller import AppController
from app.view.gui import AppGUI
from app.config import DB_PATH, __version__
from app.utils import auto_update
import tkinter.messagebox as mb


def main():
    # Check for updates on startup
    update = auto_update.check_for_update()
    if update:
        latest, url = update
        if mb.askyesno("Update Available", f"A new version {latest} is available. Update now?"):
            auto_update.download_and_schedule_update(url)

    # Initialize controller and GUI
    controller = AppController(DB_PATH)
    app = AppGUI(controller)
    app.mainloop()
    controller.close()


if __name__ == "__main__":
    main()
