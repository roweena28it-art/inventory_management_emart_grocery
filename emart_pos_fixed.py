"""
EMart POS System - Fixed Version

This script implements a simple grocery point‑of‑sale (POS) application
for a hypothetical EMart enterprise.  It closely replicates the layout
and functionality of the user‑supplied GUI, while addressing several
issues that caused buttons to malfunction in the original code.  The
primary improvements include:

* Proper handling of Treeview selections when adding items to the cart.
* Graceful handling of missing ER diagram images.
* User authentication against the database rather than hard‑coded
  credentials.
* Defensive coding around quantity parsing and stock checks.
* Simplified view logic for sales, users and audit logs.

The code creates a SQLite database on first run with four tables:
```
Users(username TEXT PRIMARY KEY, password TEXT)
Products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL, stock INTEGER)
Sales(sale_id INTEGER PRIMARY KEY AUTOINCREMENT, total REAL, items_count INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
Audit_Log(log_id INTEGER PRIMARY KEY AUTOINCREMENT, msg TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```
and a trigger that automatically writes to the audit log whenever a new
sale is inserted.  A default administrator account (``admin``/``admin123``)
and a handful of sample products are pre‑populated so that the
application can be used immediately.

To run the application simply execute this file with Python 3.  On
start‑up a login window is presented; upon successful authentication
the main POS window appears.  From there you can browse inventory,
add items to the cart, checkout purchases, view sales/users/logs,
compute end‑of‑day totals and display the optional ER diagram if
available.
"""

import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

try:
    # PIL is used to display the ER diagram image when available.  If
    # Pillow is not installed, the diagram button will still show a
    # helpful error instead of crashing.
    from PIL import Image, ImageTk  # type: ignore
except ImportError:
    Image = None
    ImageTk = None


def init_db(db_path: str = "emart_enterprise.db") -> None:
    """Initialise the SQLite database with required tables, data and triggers.

    Args:
        db_path: path to the SQLite database file.  Defaults to
        ``emart_enterprise.db`` in the current working directory.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Enforce foreign key constraints
    cur.execute("PRAGMA foreign_keys = ON")

    # Core tables
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS Users (
            username TEXT PRIMARY KEY,
            password TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS Products (
            id INTEGER PRIMARY KEY,
            name TEXT,
            category TEXT,
            price REAL,
            stock INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS Sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            total REAL,
            items_count INTEGER,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS Audit_Log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg TEXT,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # ------------------------------------------------------------------
    # Ensure backwards compatibility: if the Sales table was created in a
    # previous version of the application without the items_count column,
    # add it.  SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS,
    # so we first inspect the current columns and then add the missing
    # column if necessary.
    cur.execute("PRAGMA table_info(Sales)")
    cols = [row[1] for row in cur.fetchall()]
    if "items_count" not in cols:
        cur.execute("ALTER TABLE Sales ADD COLUMN items_count INTEGER")

    # Trigger to automatically log sales
    cur.execute(
        """
        CREATE TRIGGER IF NOT EXISTS auto_audit
        AFTER INSERT ON Sales
        BEGIN
            INSERT INTO Audit_Log (msg)
            VALUES ('Sale \u20B9' || NEW.total || ' completed');
        END;
        """
    )

    # Seed a default admin user (idempotent)
    cur.execute(
        "INSERT OR IGNORE INTO Users(username, password) VALUES(?, ?)",
        ("admin", "admin123"),
    )

    # Seed some products if they do not already exist
    sample_products = [
        (1, "Milk", "Dairy", 66.0, 100),
        (2, "Bread", "Bakery", 45.0, 8),
        (3, "Rice", "Grains", 550.0, 5),
        (4, "Maggi", "Snacks", 60.0, 50),
        (5, "Salt", "Essentials", 25.0, 3),
        (6, "Boost", "Health", 350.0, 2),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Products(id, name, category, price, stock) VALUES (?, ?, ?, ?, ?)",
        sample_products,
    )
    cur.execute("DROP VIEW IF EXISTS Sales_Summary")
    cur.execute("""
    CREATE VIEW Sales_Summary AS
    SELECT sale_id, total, items_count, date FROM Sales
    """)
    
    conn.commit()
    conn.close()


class LoginWindow:
    """Simple login window prompting for username/password.

    The login form is displayed at application start.  On successful
    authentication the main POS window is launched.
    """

    def __init__(self, master: tk.Tk, db_path: str = "emart_enterprise.db") -> None:
        self.master = master
        self.db_path = db_path
        master.title("EMart Login")
        master.geometry("400x300")
        master.configure(bg="#1a237e")

        # Card frame to centre the login form
        frame = tk.Frame(master, bg="white", padx=30, pady=30)
        frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Title and subtitle
        tk.Label(frame, text="EMART INDIA", font=("Arial", 16, "bold"), bg="white", fg="#1a237e").pack()
        tk.Label(frame, text="Enterprise Portal", bg="white").pack(pady=10)

        # Username and password fields
        self.u_entry = tk.Entry(frame, width=25)
        self.u_entry.pack(pady=5)
        self.p_entry = tk.Entry(frame, show="*", width=25)
        self.p_entry.pack(pady=5)

        # Login button
        tk.Button(
            frame,
            text="LOGIN",
            bg="#1a237e",
            fg="white",
            width=20,
            command=self.check_credentials,
        ).pack(pady=10)

        # Bind Enter key to login
        self.p_entry.bind("<Return>", lambda _: self.check_credentials())

    def check_credentials(self) -> None:
        """Check the entered username/password against the Users table."""
        username = self.u_entry.get().strip()
        password = self.p_entry.get().strip()
        if not username or not password:
            messagebox.showerror("Error", "Please enter both username and password")
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM Users WHERE username = ? AND password = ?",
            (username, password),
        )
        result = cur.fetchone()
        conn.close()

        if result:
            # Close login window and open main POS
            self.master.destroy()
            open_main(self.db_path)
        else:
            messagebox.showerror("Error", "Invalid login credentials")


class EMartApp:
    """Main POS application window.

    Displays the inventory on the left, a cart/bill on the right, and
    a sidebar for navigation and reporting.  Implements all
    functional requirements from the original GUI with several fixes
    and improvements.
    """

    def __init__(self, master: tk.Tk, db_path: str = "emart_enterprise.db") -> None:
        self.master = master
        self.db_path = db_path
        self.master.title("EMart POS")
        self.master.geometry("1200x650")

        # Initialize an empty shopping cart.  Each entry is a dict with
        # id, name, quantity and subtotal.
        self.cart: list[dict[str, object]] = []

        # Header
        header = tk.Label(
            master,
            text="EMART POS SYSTEM",
            bg="#1a237e",
            fg="white",
            font=("Arial", 16, "bold"),
            pady=10,
        )
        header.pack(fill=tk.X)

        # Main content frame containing sidebar, inventory and bill
        main_frame = tk.Frame(master)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Sidebar with navigation buttons
        sidebar = tk.Frame(main_frame, bg="#eeeeee", width=180)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        # Each button triggers its respective callback
        tk.Button(sidebar, text="Products", command=self.refresh_inventory).pack(fill=tk.X)
        tk.Button(sidebar, text="Sales", command=self.view_sales).pack(fill=tk.X)
        tk.Button(sidebar, text="Users", command=self.view_users).pack(fill=tk.X) 
        tk.Button(sidebar, text="Audit Logs", command=self.view_logs).pack(fill=tk.X)
        tk.Button(sidebar, text="Sales Summary", command=lambda: self._show_table("SELECT * FROM Sales_Summary", "Sales Summary")).pack(fill=tk.X)
        tk.Button(sidebar, text="ER Diagram", command=self.show_er).pack(fill=tk.X)

        # Centre panel: Treeview listing products
        center = tk.Frame(main_frame)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(
            center,
            columns=("ID", "Name", "Category", "Price", "Stock"),
            show="headings",
        )
        for col in ("ID", "Name", "Category", "Price", "Stock"):
            self.tree.heading(col, text=col)
            # Give each column a reasonable width
            if col == "Name":
                self.tree.column(col, width=150)
            else:
                self.tree.column(col, width=80)
        self.tree.pack(fill=tk.BOTH, expand=True)
        # Configure a tag for low stock items
        self.tree.tag_configure("low", background="#ffcccc")

        # Right panel: Bill summary
        right = tk.Frame(main_frame, bg="#f5f5f5", width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        tk.Label(right, text="BILL", font=("Arial", 14, "bold"), bg="#f5f5f5").pack(pady=10)

        self.bill_tree = ttk.Treeview(
            right,
            columns=("Name", "Qty", "Total"),
            show="headings",
        )
        for col in ("Name", "Qty", "Total"):
            self.bill_tree.heading(col, text=col)
            self.bill_tree.column(col, width=90)
        self.bill_tree.pack(pady=5)

        # Total label
        self.total_lbl = tk.Label(
            right, text="TOTAL: \u20B90", font=("Arial", 14, "bold"), bg="#f5f5f5"
        )
        self.total_lbl.pack(pady=10)

        # Checkout button
        tk.Button(
            right,
            text="CHECKOUT",
            bg="green",
            fg="white",
            width=20,
            command=self.checkout,
        ).pack(pady=10)

        # Bottom bar: quantity entry, Add to cart and EOD buttons
        bottom = tk.Frame(master)
        bottom.pack(fill=tk.X, pady=5)
        tk.Label(bottom, text="Qty").pack(side=tk.LEFT, padx=10)
        self.qty_entry = tk.Entry(bottom, width=5)
        self.qty_entry.pack(side=tk.LEFT)
        self.qty_entry.insert(0, "1")
        tk.Button(
            bottom,
            text="ADD",
            bg="#1a237e",
            fg="white",
            command=self.add_to_cart,
        ).pack(side=tk.LEFT, padx=10)
        tk.Button(
            bottom, text="EOD", bg="orange", command=self.eod
        ).pack(side=tk.LEFT)

        # Populate the inventory
        self.refresh_inventory()

    # Inventory functions
    def refresh_inventory(self) -> None:
        """Refresh the product list from the database."""
        # Clear existing rows
        for item in self.tree.get_children():
            self.tree.delete(item)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM Products")
        for row in cur.fetchall():
            # row = (id, name, category, price, stock)
            if row[4] < 5:
                self.tree.insert("", tk.END, values=row, tags=("low",))
            else:
                self.tree.insert("", tk.END, values=row)
        conn.close()

    def add_to_cart(self) -> None:
        """Add the selected product and quantity to the cart."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showerror("Error", "Please select a product from the list")
            return
        # Use the first selected item (Treeview returns a tuple of IDs)
        item_id = selection[0]
        data = self.tree.item(item_id, "values")
        # data returns a tuple of strings: (id, name, category, price, stock)
        try:
            qty = int(self.qty_entry.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Quantity must be a positive integer")
            return
        stock = int(data[4])
        if qty > stock:
            messagebox.showerror("Error", "Insufficient stock for the selected item")
            return
        # Calculate subtotal
        price = float(data[3])
        subtotal = qty * price
        # Append to cart
        self.cart.append({
            "id": int(data[0]),
            "name": data[1],
            "qty": qty,
            "sub": subtotal,
        })
        self.update_bill()

    def update_bill(self) -> None:
        """Update the bill Treeview and total amount."""
        # Clear bill tree
        for item in self.bill_tree.get_children():
            self.bill_tree.delete(item)
        total = 0.0
        for item in self.cart:
            self.bill_tree.insert(
                "", tk.END, values=(item["name"], item["qty"], f"\u20B9{item['sub']:.2f}")
            )
            total += float(item["sub"])
        self.total_lbl.config(text=f"TOTAL: \u20B9{total:.2f}")

    def checkout(self) -> None:
        """Process the sale: update stock, record the sale and clear the cart."""
        if not self.cart:
            messagebox.showerror("Error", "Your cart is empty")
            return
        # Compute total
        total_amount = sum(item["sub"] for item in self.cart)
        # Begin database transaction
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            # Update product stock
            for item in self.cart:
                cur.execute(
                    "UPDATE Products SET stock = stock - ? WHERE id = ?",
                    (item["qty"], item["id"]),
                )
            # Insert into Sales table
            cur.execute(
                "INSERT INTO Sales(total, items_count) VALUES(?, ?)",
                (total_amount, len(self.cart)),
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            messagebox.showerror("Database error", f"Checkout failed: {exc}")
            conn.close()
            return
        conn.close()
        messagebox.showinfo("Success", f"Payment of \u20B9{total_amount:.2f} received. Thank you!")
        # Clear cart and refresh views
        self.cart.clear()
        self.update_bill()
        self.refresh_inventory()

    def eod(self) -> None:
        """Perform an end‑of‑day summary showing total sales."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT SUM(total) FROM Sales")
        total_sales = cur.fetchone()[0] or 0.0
        conn.close()
        messagebox.showinfo(
            "End of Day",
            f"Total Sales: \u20B9{total_sales:.2f}",
        )

    # View functions
    def view_sales(self) -> None:
        self._show_table("SELECT * FROM Sales", title="Sales History")

    def view_users(self) -> None:
        self._show_table("SELECT * FROM Users", title="User Accounts")

    def view_logs(self) -> None:
        self._show_table("SELECT * FROM Audit_Log", title="Audit Log")

    def _show_table(self, query: str, title: str = "Table") -> None:
        """Display the results of a SQL query in a new window."""
        win = tk.Toplevel(self.master)
        win.title(title)
        tree = ttk.Treeview(win)
        tree.pack(fill=tk.BOTH, expand=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(query)
        # Extract column names
        cols = [desc[0] for desc in cur.description]
        tree["columns"] = cols
        tree["show"] = "headings"
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=100)
        for row in cur.fetchall():
            tree.insert("", tk.END, values=row)
        conn.close()

    def show_er(self) -> None:
        """Display the ER diagram image if available."""
        # Path to the diagram image.  Accept common extensions.
        diagram_path = None
        for ext in ("er_diagram.png", "er_diagram.jpeg", "er_diagram.jpg", "er_diagram.png.jpeg"):
            if os.path.exists(ext):
                diagram_path = ext
                break
        if diagram_path is None:
            messagebox.showinfo("ER Diagram", "ER diagram image not found.")
            return
        if Image is None or ImageTk is None:
            messagebox.showerror(
                "Error",
                "Pillow library not installed. Cannot display images.",
            )
            return
        # Create a new window and display the image
        win = tk.Toplevel(self.master)
        win.title("ER Diagram")
        img = Image.open(diagram_path)
        # Resize to fit nicely if it's very large
        max_width, max_height = 800, 600
        if img.width > max_width or img.height > max_height:
            ratio = min(max_width / img.width, max_height / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size)
        photo = ImageTk.PhotoImage(img)
        label = tk.Label(win, image=photo)
        # Keep a reference to avoid garbage collection
        label.image = photo
        label.pack()


def open_main(db_path: str = "emart_enterprise.db") -> None:
    """Create and run the main EMart POS window."""
    root = tk.Tk()
    EMartApp(root, db_path=db_path)
    root.mainloop()


if __name__ == "__main__":
    # Initialise the database and launch login screen
    init_db()
    root = tk.Tk()
    LoginWindow(root)
    root.mainloop()