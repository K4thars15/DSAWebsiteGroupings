from flask import Flask, request, render_template, redirect, url_for, g, jsonify
import sqlite3
import os
import threading
import time
import uuid
from markupsafe import escape

app = Flask(__name__)
DATABASE = "feed.db"

# -------------------------
# SIMPLE NODE / STRUCTURES
# -------------------------
class Node:
    def __init__(self, data):
        self.node = data
        self.left = None
        self.right = None

class Stack:
    def __init__(self):
        self.head = None
        self.length = 0

    def push(self, data):
        n = Node(data)
        n.left = self.head
        self.head = n
        self.length += 1

    def to_list(self):
        items = []
        cur = self.head
        while cur:
            items.append(cur.node)
            cur = cur.left
        return items

class QueueLinked:
    """Linked-list based queue used only locally in some actions."""
    def __init__(self):
        self.head = None
        self.tail = None
        self.length = 0

    def enqueue(self, data):
        n = Node(data)
        if not self.head:
            self.head = n
            self.tail = n
        else:
            self.tail.right = n
            self.tail = n
        self.length += 1

    def dequeue(self):
        if self.length == 0:
            return None
        n = self.head
        self.head = self.head.right
        self.length -= 1
        return n.node

class BST:
    def __init__(self):
        self.root = None

    def insert(self, data):
        # data expected as string
        new = Node(data)
        if not self.root:
            self.root = new
            return

        cur = self.root
        while True:
            if data < cur.node:
                if cur.left:
                    cur = cur.left
                else:
                    cur.left = new
                    return
            else:
                if cur.right:
                    cur = cur.right
                else:
                    cur.right = new
                    return

    def dfs_search(self, word):
        if not word:
            return []
        results = []
        w = word.lower()

        def walk(node):
            if not node:
                return
            try:
                if w in node.node.lower():
                    results.append(node.node)
            except Exception:
                pass
            walk(node.left)
            walk(node.right)

        walk(self.root)
        return results

# -------------------------
# DATABASE HELPERS
# -------------------------
def get_db():
    if "db" not in g:
        # enable check_same_thread False for dev single-process
        g.db = sqlite3.connect(DATABASE, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    if not os.path.exists(DATABASE):
        conn = sqlite3.connect(DATABASE)
        if not os.path.exists("schema.sql"):
            # Avoid crashing if schema.sql missing; create minimal schema for posts
            conn.execute("""
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                caption TEXT,
                author TEXT,
                post_type TEXT,
                up INTEGER DEFAULT 0,
                down INTEGER DEFAULT 0
            );
            """)
        else:
            with open("schema.sql", "r") as f:
                conn.executescript(f.read())
        conn.commit()
        conn.close()

# -------------------------
# FEED / SEARCH LOGIC
# -------------------------
def get_feed_stack():
    db = get_db()
    # return newest-first so front-end loop.first behaves predictably if you prepend interatives
    rows = db.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
    stack = Stack()
    for r in rows:
        # convert sqlite Row to regular dict to avoid sqlite Row quirks in templates/JS
        stack.push({
            "id": r["id"],
            "title": r["title"],
            "caption": r["caption"],
            "author": r["author"],
            "post_type": r["post_type"],
            "up": r["up"] if r["up"] is not None else 0,
            "down": r["down"] if r["down"] is not None else 0,
        })
    return stack.to_list()

def perform_bst_search(keyword):
    posts = get_feed_stack()
    bst = BST()
    for post in posts:
        title = post.get("title", "") or ""
        bst.insert(title)
    return bst.dfs_search(keyword)

# -------------------------
# ROUTES
# -------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        keyword = request.form.get("search", "") or ""

        db = get_db()
        sql_results = db.execute("""
            SELECT id, title, caption 
            FROM posts
            WHERE title LIKE ? OR caption LIKE ?
            ORDER BY id DESC
        """, (f"%{keyword}%", f"%{keyword}%")).fetchall()

        results = []
        for r in sql_results:
            cid = r["id"]
            title = r["title"] or ""
            caption = r["caption"] or ""
            max_value = caption if caption.strip() else "None"

            # related_count: naive heuristic using first word of title
            related_count = 0
            if title.strip():
                first_word = title.strip().split()[0]
                q = db.execute(
                    "SELECT COUNT(*) as c FROM posts WHERE (title LIKE ? OR caption LIKE ?) AND id != ?",
                    (f"%{first_word}%", f"%{first_word}%", cid)
                ).fetchone()
                related_count = q["c"] if q is not None else 0

            results.append({
                "id": cid,
                "title": title,
                "caption": caption,
                "max_value": max_value,
                "related_count": related_count
            })

        return jsonify(results)

    # default homepage load
    posts = get_feed_stack()
    return render_template("index.html", posts=posts)


@app.route("/search_posts")
def search_posts():
    q = request.args.get("q", "").strip()

    db = get_db()
    rows = db.execute("""
        SELECT id, title, caption 
        FROM posts
        WHERE title LIKE ? OR caption LIKE ?
        ORDER BY id DESC
    """, (f"%{q}%", f"%{q}%")).fetchall()

    results = []
    for r in rows:
        cid = r["id"]
        title = r["title"] or ""
        caption = r["caption"] or ""
        max_value = caption if caption.strip() else "None"

        related_count = 0
        if title.strip():
            first_word = title.strip().split()[0]
            rr = db.execute(
                "SELECT COUNT(*) as c FROM posts WHERE (title LIKE ? OR caption LIKE ?) AND id != ?",
                (f"%{first_word}%", f"%{first_word}%", cid)
            ).fetchone()
            related_count = rr["c"] if rr is not None else 0

        results.append({
            "id": cid,
            "title": title,
            "caption": caption,
            "max_value": max_value,
            "related_count": related_count
        })

    return jsonify(results)

@app.route("/lectures", methods=["GET", "POST"])
def lectures():
    if request.method == "POST":
        db = get_db()
        db.execute("""
            INSERT INTO posts(title, caption, author, post_type, up, down)
            VALUES (?, ?, ?, ?, 0, 0)
        """, (
            request.form.get("title"),
            request.form.get("caption"),
            request.form.get("author", "Anonymous"),
            request.form.get("post_type", "regular")
        ))
        db.commit()
        return redirect(url_for("lectures"))

    db_posts = get_feed_stack()

    interactive_posts = [
        {
            "id": -1,
            "title": "Queue Interactive Demo",
            "caption": "Real-time enqueue/dequeue visualization.",
            "up": 0,
            "down": 0
        },
        {
            "id": -2,
            "title": "Stack Interactive Demo",
            "caption": "Push/pop to see LIFO behavior.",
            "up": 0,
            "down": 0
        },
        {
            "id": -3,
            "title": "Tree Interactive Demo",
            "caption": "Add nodes to grow a general tree.",
            "up": 0,
            "down": 0
        },
        {
            "id": -4,
            "title": "Binary Tree Interactive Demo",
            "caption": "Insert left/right nodes manually.",
            "up": 0,
            "down": 0
        },
        {
            "id": -5,
            "title": "Binary Search Tree Interactive Demo",
            "caption": "Automatic BST insertion.",
            "up": 0,
            "down": 0
        }
    ]

    final_posts = interactive_posts + db_posts
    # Enrich regular posts with two helper fields:
    # - max_value: show the post's caption (or 'None')
    # - related_count: number of other posts that share a keyword from this title
    db = get_db()
    for post in final_posts:
        try:
            if post.get("id", 0) > 0:
                # max_value: use caption or 'None'
                post["max_value"] = post.get("caption") or "None"

                # related_count: use the first word of the title to find related posts
                title = (post.get("title") or "").strip()
                if title:
                    first_word = title.split()[0]
                    q = db.execute(
                        "SELECT COUNT(*) as c FROM posts WHERE (title LIKE ? OR caption LIKE ?) AND id != ?",
                        (f"%{first_word}%", f"%{first_word}%", post["id"]) 
                    ).fetchone()
                    post["related_count"] = q["c"] if q is not None else 0
                else:
                    post["related_count"] = 0
            else:
                # interactive placeholders: show N/A
                post["max_value"] = "N/A"
                post["related_count"] = 0
        except Exception:
            post["max_value"] = post.get("caption") or "None"
            post["related_count"] = 0

    return render_template("lectures.html", posts=final_posts)

@app.route("/create_post", methods=["POST"])
def create_post():
    db = get_db()
    db.execute("""
        INSERT INTO posts(title, caption, author, post_type, up, down)
        VALUES (?, ?, ?, ?, 0, 0)
    """, (
        request.form.get("title"),
        request.form.get("caption"),
        request.form.get("author", "Anonymous"),
        request.form.get("post_type", "regular")
    ))
    db.commit()
    return redirect(url_for("lectures"))

@app.route("/vote/<int:id>/<string:way>", methods=["GET"])
def vote(id, way):
    db = get_db()
    if way == "up":
        db.execute("UPDATE posts SET up = up + 1 WHERE id=?", (id,))
    else:
        db.execute("UPDATE posts SET down = down + 1 WHERE id=?", (id,))
    db.commit()
    return redirect(url_for("lectures"))

# accept POST from fetch in your UI (was GET previously)
@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    # demonstrate queue-based delete: enqueue & dequeue then delete
    q = QueueLinked()
    q.enqueue(id)
    post_id = q.dequeue()
    if post_id is None:
        return jsonify(status="no-op"), 200

    db = get_db()
    db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    db.commit()
    return jsonify(status="deleted"), 200

def delayed_delete(post_id, delay=5):
    time.sleep(delay)
    db = get_db()
    db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    db.commit()

@app.route("/delete/<int:id>", methods=["POST"])
def delete_post(post_id):
    threading.Thread(target=delayed_delete, args=(post_id,5)).start()
    return jsonify({"ok": True})

# Edit should accept the same form fields used by your modal (title, caption, author)
@app.route("/edit/<int:id>", methods=["POST"])
def edit(id):
    # Your modal sets the form to post title, caption, author (same names)
    title = request.form.get("title")
    caption = request.form.get("caption")
    author = request.form.get("author")

    db = get_db()
    # Only update fields that were provided
    if title is not None:
        db.execute("UPDATE posts SET title=? WHERE id=?", (title, id))
    if caption is not None:
        db.execute("UPDATE posts SET caption=? WHERE id=?", (caption, id))
    if author is not None:
        db.execute("UPDATE posts SET author=? WHERE id=?", (author, id))
    db.commit()
    return redirect(url_for("lectures"))

@app.route("/collaborators")
def collaborators_page():
    return render_template("collaborators.html")
# ----------------------
# In-memory storage
# ----------------------
queue = []
stack = []
tree_root = None
bst_root = None

# ----------------------
# Tree / BST classes
# ----------------------
class TreeNode:
    def __init__(self, val):
        self.val = val
        self.left = None
        self.right = None

# ----------------------
# Helpers
# ----------------------
def escape_text(text):
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))

# ----------------------
# SVG renderers
# ----------------------
def render_queue_svg():
    width = max(300, 120 * max(1, len(queue)))
    height = 120
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    for i, val in enumerate(queue):
        x = 20 + i * 120
        parts.append(f'<rect x="{x}" y="30" width="100" height="60" rx="8" fill="#4cc9ff" stroke="#fff"/>')
        parts.append(f'<text x="{x+50}" y="65" font-size="18" text-anchor="middle" fill="#000">{escape_text(val)}</text>')
    parts.append('</svg>')
    return "".join(parts)

def render_stack_svg():
    width = 200
    height = max(120, 80 * len(stack) + 20)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    for i, val in enumerate(reversed(stack)):
        y = 20 + i * 80
        parts.append(f'<rect x="40" y="{y}" width="120" height="60" rx="8" fill="#90f1a9" stroke="#fff"/>')
        parts.append(f'<text x="100" y="{y+36}" font-size="18" text-anchor="middle" fill="#000">{escape_text(val)}</text>')
    parts.append('</svg>')
    return "".join(parts)

def render_generic_tree_svg(root):
    if not root:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200"></svg>'

    width, height = 1000, 500
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']

    def traverse(node, x, y, level):
        if not node:
            return
        offset = 200 / level
        if node.left:
            parts.append(f'<line x1="{x}" y1="{y}" x2="{x-offset*2}" y2="{y+80}" stroke="#fff"/>')
        if node.right:
            parts.append(f'<line x1="{x}" y1="{y}" x2="{x+offset*2}" y2="{y+80}" stroke="#fff"/>')
        parts.append(f'<circle cx="{x}" cy="{y}" r="25" fill="#f8c537" stroke="#fff"/>')
        parts.append(f'<text x="{x}" y="{y+5}" font-size="20" text-anchor="middle" fill="#000">{escape_text(node.val)}</text>')
        traverse(node.left, x-offset*2, y+80, level+1)
        traverse(node.right, x+offset*2, y+80, level+1)

    traverse(root, 500, 40, 1)
    parts.append('</svg>')
    return "".join(parts)

# ----------------------
# BST helpers
# ----------------------
def bst_insert(node, val):
    if not node:
        return TreeNode(val)
    if val < node.val:
        node.left = bst_insert(node.left, val)
    else:
        node.right = bst_insert(node.right, val)
    return node

# ----------------------
# MANUAL BINARY TREE
# ----------------------
bt_root = None

def render_binary_tree_svg(root):
    if not root:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="400"></svg>'

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="500">']

    def walk(node, x, y, spread):
        if not node:
            return

        if node.left:
            parts.append(f'<line x1="{x}" y1="{y}" x2="{x-spread}" y2="{y+100}" stroke="white"/>')
            walk(node.left, x-spread, y+100, spread//2)

        if node.right:
            parts.append(f'<line x1="{x}" y1="{y}" x2="{x+spread}" y2="{y+100}" stroke="white"/>')
            walk(node.right, x+spread, y+100, spread//2)

        parts.append(f'<circle cx="{x}" cy="{y}" r="25" fill="#ff6b6b" stroke="white"/>')
        parts.append(f'<text x="{x}" y="{y+6}" text-anchor="middle" font-size="18" fill="black">{escape_text(node.val)}</text>')

    walk(root, 500, 50, 200)
    parts.append('</svg>')
    return "".join(parts)

@app.route("/bt/add-left", methods=["POST"])
def bt_add_left():
    global bt_root
    val = request.json.get("value", "").strip()
    if not val:
        return jsonify({"ok": False})

    if not bt_root:
        bt_root = TreeNode(val)
    else:
        if not bt_root.left:
            bt_root.left = TreeNode(val)

    return jsonify({"ok": True, "svg": render_binary_tree_svg(bt_root)})


@app.route("/bt/add-right", methods=["POST"])
def bt_add_right():
    global bt_root
    val = request.json.get("value", "").strip()
    if not val:
        return jsonify({"ok": False})

    if not bt_root:
        bt_root = TreeNode(val)
    else:
        if not bt_root.right:
            bt_root.right = TreeNode(val)

    return jsonify({"ok": True, "svg": render_binary_tree_svg(bt_root)})


@app.route("/bt/reset", methods=["POST"])
def bt_reset():
    global bt_root
    bt_root = None
    return jsonify({"ok": True, "svg": render_binary_tree_svg(bt_root)})

def bst_search(node, val):
    if not node:
        return False
    if node.val == val:
        return True
    elif val < node.val:
        return bst_search(node.left, val)
    else:
        return bst_search(node.right, val)


def bst_find_max(node):
    if not node:
        return None
    while node.right:
        node = node.right
    return node.val


def bst_height(node):
    if not node:
        return 0
    return 1 + max(bst_height(node.left), bst_height(node.right))


def bst_delete(node, val):
    if not node:
        return None

    if val < node.val:
        node.left = bst_delete(node.left, val)
    elif val > node.val:
        node.right = bst_delete(node.right, val)
    else:
        # ✅ Case 1: No child
        if not node.left and not node.right:
            return None

        # ✅ Case 2: One child
        if not node.left:
            return node.right
        if not node.right:
            return node.left

        # ✅ Case 3: Two children
        temp = bst_find_max(node.left)
        node.val = temp
        node.left = bst_delete(node.left, temp)

    return node

# ----------------------
# Routes
# ----------------------
# Queue endpoints
@app.route("/queue/enqueue", methods=["POST"])
def queue_enqueue():
    val = request.json.get("value", "").strip()
    if not val:
        return jsonify({"ok": False})
    queue.append(val)
    return jsonify({"ok": True, "svg": render_queue_svg()})

@app.route("/queue/dequeue", methods=["POST"])
def queue_dequeue():
    if queue:
        queue.pop(0)
    return jsonify({"ok": True, "svg": render_queue_svg()})

# Stack endpoints
@app.route("/stack/push", methods=["POST"])
def stack_push():
    val = request.json.get("value", "").strip()
    if not val:
        return jsonify({"ok": False})
    stack.append(val)
    return jsonify({"ok": True, "svg": render_stack_svg()})

@app.route("/stack/pop", methods=["POST"])
def stack_pop():
    if stack:
        stack.pop()
    return jsonify({"ok": True, "svg": render_stack_svg()})

# Generic tree endpoints
@app.route("/tree/insert", methods=["POST"])
def tree_insert_route():
    global tree_root
    val = request.json.get("value", "").strip()
    if not val:
        return jsonify({"ok": False})

    new_node = TreeNode(val)
    if not tree_root:
        tree_root = new_node
    else:
        # level order insertion
        q = [tree_root]
        while q:
            node = q.pop(0)
            if not node.left:
                node.left = new_node
                break
            elif not node.right:
                node.right = new_node
                break
            q.append(node.left)
            q.append(node.right)
    return jsonify({"ok": True, "svg": render_generic_tree_svg(tree_root)})

# BST endpoints
@app.route("/bst/insert", methods=["POST"])
def bst_insert_route():
    global bst_root
    val = request.json.get("value", "").strip()
    if not val:
        return jsonify({"ok": False})
    try:
        num = int(val)
    except:
        return jsonify({"ok": False, "error": "numeric only"})
    bst_root = bst_insert(bst_root, num)
    return jsonify({"ok": True, "svg": render_generic_tree_svg(bst_root)})

@app.route("/bst/search", methods=["POST"])
def bst_search_route():
    global bst_root
    val = request.json.get("value")
    try:
        num = int(val)
    except:
        return jsonify({"ok": False})

    found = bst_search(bst_root, num)
    return jsonify({"ok": True, "found": found})


@app.route("/bst/max", methods=["GET"])
def bst_max_route():
    global bst_root
    m = bst_find_max(bst_root)
    return jsonify({"ok": True, "max": m})


@app.route("/bst/height", methods=["GET"])
def bst_height_route():
    global bst_root
    h = bst_height(bst_root)
    return jsonify({"ok": True, "height": h})


@app.route("/bst/delete", methods=["POST"])
def bst_delete_route():
    global bst_root
    val = request.json.get("value")
    try:
        num = int(val)
    except:
        return jsonify({"ok": False})

    bst_root = bst_delete(bst_root, num)
    return jsonify({"ok": True, "svg": render_generic_tree_svg(bst_root)})

# RUN
if __name__ == "__main__":
    init_db()
    app.run(debug=True)