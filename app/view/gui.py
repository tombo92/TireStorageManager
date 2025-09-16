import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from app.controller.app_controller import AppController
from app.model.entities import Season
from app.utils.i18n import t, Language, set_language

class AppGUI(tk.Tk):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        # Set language at startup
        self._current_lang = Language.EN
        set_language(self._current_lang)

        self.title(t("title"))
        self.geometry("850x500")

         # Menu for language switching
        menu = tk.Menu(self)
        self.config(menu=menu)
        lang_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Language", menu=lang_menu)
        lang_menu.add_command(label="English", command=lambda: self._set_language(Language.EN))
        lang_menu.add_command(label="Deutsch", command=lambda: self._set_language(Language.DE))

        self._build_widgets()
        self._refresh()

    # --------------------------
    # Language switching
    # --------------------------
    def _set_language(self, lang: Language):
        set_language(lang)
        self._current_lang = lang
        self.title(t("title"))
        self._refresh()

    import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from app.controller.app_controller import AppController
from app.model.entities import Season
from app.utils.i18n import t, Language, set_language

class AppGUI(tk.Tk):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self._current_lang = Language.DE
        set_language(self._current_lang)

        self.title(t("title"))
        self.geometry("850x500")

        # Menu for language switching
        menu = tk.Menu(self)
        self.config(menu=menu)
        lang_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Language", menu=lang_menu)
        lang_menu.add_command(label="English", command=lambda: self._set_language(Language.EN))
        lang_menu.add_command(label="Deutsch", command=lambda: self._set_language(Language.DE))

        self._build_widgets()
        self._refresh()

    # --------------------------
    # Language switching
    # --------------------------
    def _set_language(self, lang: Language):
        set_language(lang)
        self._current_lang = lang
        self.title(t("title"))
        self._refresh()

    # --------------------------
    # Build main widgets
    # --------------------------
    def _build_widgets(self):
        # Top controls
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text=t("search")).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.search_var, width=40)
        e.pack(side=tk.LEFT, padx=6)
        e.bind("<Return>", lambda *_: self._refresh())

        ttk.Button(top, text=t("find"), command=self._refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text=t("add"), command=self._add_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text=t("edit"), command=self._edit_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text=t("delete"), command=self._delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text=t("import_excel"), command=self._import_excel).pack(side=tk.LEFT, padx=12)
        ttk.Button(top, text=t("export_excel"), command=self._export_excel).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text=t("backup_now"), command=self._backup_now).pack(side=tk.RIGHT)

        # Table
        cols = ("id", "customer_name", "location", "season")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=t(c) if c != "id" else "ID")
            self.tree.column(c, width=150 if c != "id" else 60, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    # --------------------------
    # Refresh table
    # --------------------------
    def _refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        records = self.controller.list_records(self.search_var.get().strip())
        for r in records:
            self.tree.insert("", tk.END, values=(r.id, r.customer_name, r.location, r.season.value))

    def _get_selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(t("title"), t("info_select_row"))
            return None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0])

    # --------------------------
    # Add / Edit dialogs
    # --------------------------
    def _add_dialog(self):
        self._record_dialog(title=t("add"))

    def _edit_selected(self):
        rid = self._get_selected_id()
        if rid is None: return
        item = self.tree.item(self.tree.selection()[0], "values")
        self._record_dialog(title=t("edit"), record_id=rid,
                            customer=item[1], location=item[2], season=item[3])

    def _record_dialog(self, title, record_id=None, customer="", location="", season="winter"):
        win = tk.Toplevel(self)
        win.title(title)
        win.grab_set()

        ttk.Label(win, text=t("customer_name")).grid(row=0, column=0, sticky="e", padx=6, pady=6)
        name_var = tk.StringVar(value=customer)
        ttk.Entry(win, textvariable=name_var, width=40).grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(win, text=t("location")).grid(row=1, column=0, sticky="e", padx=6, pady=6)
        loc_var = tk.StringVar(value=location)
        ttk.Entry(win, textvariable=loc_var, width=40).grid(row=1, column=1, padx=6, pady=6)

        ttk.Label(win, text=t("season")).grid(row=2, column=0, sticky="e", padx=6, pady=6)
        season_var = tk.StringVar(value=season or "winter")
        ttk.Combobox(win, textvariable=season_var,
                     values=[t(s.value) for s in Season], state="readonly")\
            .grid(row=2, column=1, padx=6, pady=6)

        def on_ok():
            try:
                if record_id is None:
                    self.controller.add_record(name_var.get(), loc_var.get(), season_var.get())
                else:
                    self.controller.update_record(record_id, name_var.get(), loc_var.get(), season_var.get())
                win.destroy()
                self._refresh()
            except Exception as e:
                messagebox.showerror(t("title"), str(e))

        ttk.Button(win, text=t("save"), command=on_ok).grid(row=3, column=0, padx=6, pady=10)
        ttk.Button(win, text=t("cancel"), command=win.destroy).grid(row=3, column=1, padx=6, pady=10)

    # --------------------------
    # Delete
    # --------------------------
    def _delete_selected(self):
        rid = self._get_selected_id()
        if rid is None: return
        if messagebox.askyesno(t("title"), t("delete_confirm")):
            try:
                self.controller.delete_record(rid)
                self._refresh()
            except Exception as e:
                messagebox.showerror(t("title"), str(e))

    # --------------------------
    # Excel import/export
    # --------------------------
    def _import_excel(self):
        path = filedialog.askopenfilename(title=t("import_excel"), filetypes=[("Excel files","*.xlsx *.xls")])
        if not path: return
        try:
            count = self.controller.import_excel(path)
            messagebox.showinfo(t("title"), f"Imported {count} records.")
            self._refresh()
        except Exception as e:
            messagebox.showerror(t("title"), str(e))

    def _export_excel(self):
        path = filedialog.asksaveasfilename(title=t("export_excel"), defaultextension=".xlsx",
                                            filetypes=[("Excel file","*.xlsx")])
        if not path: return
        try:
            self.controller.export_excel(path, self.search_var.get().strip())
            messagebox.showinfo(t("title"), f"Exported to {path}")
        except Exception as e:
            messagebox.showerror(t("title"), str(e))

    # --------------------------
    # Manual backup
    # --------------------------
    def _backup_now(self):
        try:
            p = self.controller.backup()
            messagebox.showinfo(t("title"), f"Backup created: {p}")
        except Exception as e:
            messagebox.showerror(t("title"), str(e))

