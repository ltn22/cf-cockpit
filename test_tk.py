import tkinter as tk

root = tk.Tk()
root.title("Tkinter Test")
tk.Label(root, text="Test").pack()
# Just close immediately after 1 second
root.after(1000, root.destroy)
root.mainloop()
EOF
./.venv/bin/python3 test_tk.py
