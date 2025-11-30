from flask import Flask, request, render_template, redirect, url_for, g, jsonify
import sqlite3
import os
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

        return jsonify([
            {"id": r["id"], "title": r["title"], "caption": r["caption"]}
            for r in sql_results
        ])

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

    results = [
        {"id": r["id"], "title": r["title"], "caption": r["caption"]}
        for r in rows
    ]

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

# ---------------------------
# IN-MEM DATA STRUCTURES FOR INTERACTIVES (simple JS APIs)
# ---------------------------
queue = []
stack = []

tree = {"root": None}
bt = {"root": None}
bst = {"root": None}

def new_id():
    return str(uuid.uuid4())

# Small helper: render a general tree to nested UL for direct assignment to innerHTML
def render_tree_html(node):
    if not node:
        return ""
    # escape to avoid injection from client-provided values
    label = escape(node.get("value", ""))
    children = node.get("children", [])
    if not children:
        return f"<div data-id='{node.get('id')}' class='tree-node'>{label}</div>"
    inner = "".join(render_tree_html(c) for c in children)
    return f"<div class='tree-node' data-id='{node.get('id')}'>{label}<div class='tree-children' style='margin-left:16px'>{inner}</div></div>"

# QUEUE API
@app.post("/queue/enqueue")
def q_enqueue():
    value = request.json.get("value")
    queue.append(value)
    return jsonify(queue=queue)

@app.post("/queue/dequeue")
def q_dequeue():
    if queue:
        queue.pop(0)
    return jsonify(queue=queue)

# STACK API
@app.post("/stack/push")
def s_push():
    value = request.json.get("value")
    stack.append(value)
    return jsonify(stack=stack)

@app.post("/stack/pop")
def s_pop():
    if stack:
        stack.pop()
    return jsonify(stack=stack)

# GENERAL TREE API
@app.post("/tree/add_root")
def t_root():
    value = request.json.get("value")
    tree["root"] = {"id": new_id(), "value": value, "children": []}
    return jsonify(render=render_tree_html(tree["root"]))

@app.post("/tree/add_child")
def t_child():
    # front-end should pass "target" id; if not provided, do nothing
    target = request.json.get("target")
    value  = request.json.get("value")

    def add(node):
        if node["id"] == target:
            node["children"].append({"id": new_id(), "value": value, "children": []})
            return True
        for child in node["children"]:
            if add(child):
                return True
        return False

    if tree["root"] and target:
        add(tree["root"])

    return jsonify(render=render_tree_html(tree["root"]) if tree["root"] else "")

# BINARY TREE API
def render_bt_html(node):
    if not node:
        return ""
    val = escape(str(node.get("value", "")))
    left_html = render_bt_html(node.get("left"))
    right_html = render_bt_html(node.get("right"))
    # simple visual: node value followed by child container
    return f"<div class='bt-node' data-id='{node.get('id')}' style='margin:6px 0;'><div class='bt-val'>{val}</div><div class='bt-children' style='margin-left:16px'>{left_html}{right_html}</div></div>"

def find_node_by_id(node, target):
    if not node:
        return None
    if node.get("id") == target:
        return node
    left = find_node_by_id(node.get("left"), target)
    if left:
        return left
    return find_node_by_id(node.get("right"), target)

@app.post("/bt/add_left")
def bt_left():
    parent = request.json.get("parent")  # optional
    value = request.json.get("value")

    if not bt["root"]:
        bt["root"] = {"id": new_id(), "value": value, "left": None, "right": None}
    else:
        # if parent provided, find and attach; otherwise attach to root's left if empty
        if parent:
            node = find_node_by_id(bt["root"], parent)
            if node and node.get("left") is None:
                node["left"] = {"id": new_id(), "value": value, "left": None, "right": None}
        else:
            # attach to root.left if empty, else try to attach to first available left-most node
            if bt["root"].get("left") is None:
                bt["root"]["left"] = {"id": new_id(), "value": value, "left": None, "right": None}
            else:
                # fallback: attach as left-most available
                cur = bt["root"]
                while cur.get("left"):
                    cur = cur["left"]
                cur["left"] = {"id": new_id(), "value": value, "left": None, "right": None}

    return jsonify(render=render_bt_html(bt["root"]))

@app.post("/bt/add_right")
def bt_right():
    parent = request.json.get("parent")  # optional
    value = request.json.get("value")

    if not bt["root"]:
        bt["root"] = {"id": new_id(), "value": value, "left": None, "right": None}
    else:
        if parent:
            node = find_node_by_id(bt["root"], parent)
            if node and node.get("right") is None:
                node["right"] = {"id": new_id(), "value": value, "left": None, "right": None}
        else:
            if bt["root"].get("right") is None:
                bt["root"]["right"] = {"id": new_id(), "value": value, "left": None, "right": None}
            else:
                cur = bt["root"]
                while cur.get("right"):
                    cur = cur["right"]
                cur["right"] = {"id": new_id(), "value": value, "left": None, "right": None}

    return jsonify(render=render_bt_html(bt["root"]))

@app.post("/bt/reset")
def bt_reset():
    bt["root"] = None
    return jsonify(render="")

# BST API
def render_bst_html(node):
    if not node:
        return ""
    val = escape(str(node.get("value", "")))
    left = render_bst_html(node.get("left"))
    right = render_bst_html(node.get("right"))
    # represent BST using nested lists for clarity
    inner = ""
    if left or right:
        inner = f"<div style='margin-left:16px'>{left}{right}</div>"
    return f"<div class='bst-node' data-value='{val}' style='margin:6px 0;'><div class='bst-val'>{val}</div>{inner}</div>"

@app.post("/bst/insert")
def bst_insert():
    raw = request.json.get("value")
    try:
        value = int(raw)
    except Exception:
        # ignore invalid inserts
        return jsonify(error="value must be integer"), 400

    def insert(node, v):
        if not node:
            return {"value": v, "left": None, "right": None}
        if v < node["value"]:
            node["left"] = insert(node["left"], v)
        else:
            node["right"] = insert(node["right"], v)
        return node

    bst["root"] = insert(bst["root"], value)
    return jsonify(render=render_bst_html(bst["root"]))

@app.post("/bst/reset")
def bst_reset():
    bst["root"] = None
    return jsonify(render="")

# RUN
if __name__ == "__main__":
    init_db()
    app.run(debug=True)