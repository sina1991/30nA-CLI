def show(session):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise RuntimeError("Tk is required for -gui (Ubuntu: python3-tk).") from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError("Cannot open a graphical display: " + str(exc)) from exc
    root.title("30nA · Directory browser")
    root.geometry("640x440")
    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)
    title = ttk.Label(frame)
    title.grid(row=0, column=0, sticky="w", pady=6)
    tree = ttk.Treeview(frame, show="tree", selectmode="browse")
    tree.grid(row=1, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(frame, command=tree.yview)
    scroll.grid(row=1, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    status = ttk.Label(frame)
    status.grid(row=2, column=0, sticky="w")
    buttons = ttk.Frame(frame)
    buttons.grid(row=3, column=0, sticky="e", pady=6)

    def refresh():
        title.configure(text=session.title)
        status.configure(text=session.error)
        tree.delete(*tree.get_children())
        for index, item in enumerate(session.items):
            tree.insert("", "end", iid=str(index), text=item.title)
        if session.items:
            tree.selection_set("0")
            tree.focus("0")
        tree.focus_set()

    def activate(event=None):
        if event and event.type == tk.EventType.ButtonPress:
            row = tree.identify_row(event.y)
            if not row:
                return
        else:
            row = tree.focus()
        if row:
            session.select(session.items[int(row)])
            refresh()
        return "break"

    def back(event=None):
        session.back()
        if session.done:
            root.destroy()
        else:
            refresh()
        return "break"

    ttk.Button(buttons, text="Back", command=back).pack(side="left", padx=4)
    ttk.Button(buttons, text="Open", command=activate).pack(side="left")
    tree.bind("<Double-1>", activate)
    tree.bind("<Return>", activate)
    root.bind("<Escape>", back)
    refresh()
    root.mainloop()
