import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from app.controller.app_controller import AppController
from app.model.entities import Season

class AppGUI(tk.Tk):
    def __init__(self, controller: AppController):
        super().__init__()
        self.title("Tire Storage Manager")
        self.geometry("850x500")
        self.controller = controller
        self._build_widgets()
        self._refresh()

    def _build_widgets(self):
        # --- top controls ---
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.search_var, width=40)
        e.pack(side=tk.LEFT, padx=6)
        e.bind("<Return>", lambda *_: self._refresh())

        ttk.Button(top, text="Find", command=self._refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Add", command=self._add_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Edit", command=self._edit_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Delete", command=self._delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Import Excel", command=self._import_excel).pack(side=tk.LEFT, padx=12)
        ttk.Button(top, text="Export Excel", command=self._export_excel).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Backup Now", command=self._backup_now).pack(side=tk.RIGHT)

        # --- table ---
        cols = ("id", "customer_name", "location", "season")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=150 if c != "id" else 60, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    # --- refresh table ---
    def _refresh(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        records = self.controller.list_records(self.search_var.get().strip())
        for r in records:
            self.tree.insert("", tk.END, values=(r.id, r.customer_name, r.location, r.season.value))

    def _get_selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Please select a row first.")
            return None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0])

    # --- add/edit dialog ---
    def _add_dialog(self):
        self._record_dialog(title="Add Record")

    def _edit_selected(self):
        rid = self._get_selected_id()
        if rid is None: return
        item = self.tree.item(self.tree.selection()[0], "values")
        self._record_dialog("Edit Record", rid, item[1], item[2], item[3])

    def _record_dialog(self, title, record_id=None, customer="", location="", season="winter"):
        win = tk.Toplevel(self)
        win.title(title)
        win.grab_set()

        ttk.Label(win, text="Customer Name").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        name_var = tk.StringVar(value=customer)
        ttk.Entry(win, textvariable=name_var, width=40).grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(win, text="Location").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        loc_var = tk.StringVar(value=location)
        ttk.Entry(win, textvariable=loc_var, width=40).grid(row=1, column=1, padx=6, pady=6)

        ttk.Label(win, text="Season").grid(row=2, column=0, sticky="e", padx=6, pady=6)
        season_var = tk.StringVar(value=season or "winter")
        ttk.Combobox(win, textvariable=season_var, values=[s.value for s in Season], state="readonly")\
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
                messagebox.showerror("Error", str(e))

        ttk.Button(win, text="Save", command=on_ok).grid(row=3, column=0, padx=6, pady=10)
        ttk.Button(win, text="Cancel", command=win.destroy).grid(row=3, column=1, padx=6, pady=10)

    # --- delete ---
    def _delete_selected(self):
        rid = self._get_selected_id()
        if rid is None: return
        if messagebox.askyesno("Confirm", "Delete the selected record?"):
            try:
                self.controller.delete_record(rid)
                self._refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # --- import/export ---
    def _import_excel(self):
        path = filedialog.askopenfilename(title="Import Excel", filetypes=[("Excel files","*.xlsx *.xls")])
        if not path: return
        try:
            count = self.controller.import_excel(path)
            messagebox.showinfo("Import", f"Imported {count} records.")
            self._refresh()
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    def _export_excel(self):
        path = filedialog.asksaveasfilename(title="Export Excel", defaultextension=".xlsx",
                                            filetypes=[("Excel file","*.xlsx")])
        if not path: return
        try:
            self.controller.export_excel(path, self.search_var.get().strip())
            messagebox.showinfo("Export", f"Exported to {path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    # --- manual backup ---
    def _backup_now(self):
        try:
            p = self.controller.backup()
            messagebox.showinfo("Backup", f"Backup created: {p}")
        except Exception as e:
            messagebox.showerror("Backup Error", str(e))
