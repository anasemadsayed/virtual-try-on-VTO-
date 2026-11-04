import csv, io, os, secrets, time, uuid
from pathlib import Path
import requests
from dotenv import load_dotenv
from PIL import Image
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()
from . import db, perfect  # noqa: E402

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Try-On Shop")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.mount("/media", StaticFiles(directory=db.DATA), name="media")
tpl = Jinja2Templates(directory=BASE / "templates")
security = HTTPBasic()
db.init()
CATS = ["auto", "upper_body", "lower_body", "full_body"]


def limit():
    return int(os.getenv("MAX_TRYONS_PER_VISITOR", "5"))


def admin(cred: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(cred.password, os.getenv("ADMIN_PASSWORD", "change-me"))
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@app.middleware("http")
async def visitor_cookie(request: Request, call_next):
    vid = request.cookies.get("vid")
    new = not vid
    vid = vid or uuid.uuid4().hex[:12]
    request.state.vid = vid
    resp = await call_next(request)
    if new:
        resp.set_cookie("vid", vid, max_age=31536000, httponly=True, samesite="lax")
    return resp


def used(vid):
    return db.q("SELECT COUNT(*) n FROM tryons WHERE visitor=?", (vid,))[0]["n"]


@app.get("/")
def shop(request: Request):
    return tpl.TemplateResponse(request, "shop.html", {"products": db.q("SELECT * FROM products ORDER BY id DESC")})


@app.get("/p/{pid}")
def product(request: Request, pid: int):
    rows = db.q("SELECT * FROM products WHERE id=?", (pid,))
    if not rows:
        raise HTTPException(404)
    left = max(0, limit() - used(request.state.vid))
    return tpl.TemplateResponse(request, "product.html", {"p": rows[0], "left": left})


@app.post("/api/tryon")
def tryon(request: Request, product_id: int = Form(...), photo: UploadFile = File(...)):
    vid = request.state.vid
    if used(vid) >= limit():
        return JSONResponse({"error": "You have used all your try-ons for this test."}, 429)
    prod = db.q("SELECT * FROM products WHERE id=?", (product_id,))
    if not prod:
        return JSONResponse({"error": "Product not found."}, 404)
    prod = prod[0]
    raw = photo.file.read()
    if len(raw) > 10 * 1024 * 1024:
        return JSONResponse({"error": "Photo is over 10 MB."}, 400)
    try:
        person = perfect.prepare_jpeg(raw)
    except Exception:
        return JSONResponse({"error": "That file is not a readable image."}, 400)
    name = uuid.uuid4().hex
    (db.DATA / "uploads" / f"{name}.jpg").write_bytes(person)
    tid = db.run(
        "INSERT INTO tryons(visitor,product_id,category,person_img,status,ip,user_agent) VALUES(?,?,?,?,?,?,?)",
        (vid, product_id, prod["category"], f"uploads/{name}.jpg", "running",
         request.client.host if request.client else "", request.headers.get("user-agent", "")[:200]))
    t0 = time.time()
    try:
        product_bytes = (db.DATA / prod["image"]).read_bytes()
        png, task_id, secs = perfect.run_tryon(person, product_bytes, prod["category"])
        (db.DATA / "results" / f"{name}.png").write_bytes(png)
        db.run("UPDATE tryons SET status='success',result_img=?,task_id=?,seconds=? WHERE id=?",
               (f"results/{name}.png", task_id, secs, tid))
        return {"id": tid, "result": f"/media/results/{name}.png", "seconds": secs}
    except Exception as e:
        db.run("UPDATE tryons SET status='error',error=?,seconds=? WHERE id=?",
               (str(e)[:500], round(time.time() - t0, 2), tid))
        return JSONResponse({"error": f"Try-on failed: {e}"}, 502)


@app.post("/api/feedback")
def feedback(request: Request, tryon_id: int = Form(...), rating: int = Form(...), comment: str = Form("")):
    rows = db.q("SELECT id FROM tryons WHERE id=? AND visitor=?", (tryon_id, request.state.vid))
    if not rows or rating not in (1, -1):
        raise HTTPException(400)
    db.run("UPDATE tryons SET rating=?, comment=? WHERE id=?", (rating, comment[:1000], tryon_id))
    return {"ok": True}


# ---------- admin ----------
def save_product_image(data: bytes) -> str:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    rel = f"products/{uuid.uuid4().hex}.jpg"
    img.save(db.DATA / rel, "JPEG", quality=90)
    return rel


@app.get("/admin", dependencies=[Depends(admin)])
def dashboard(request: Request):
    rows = db.q("""SELECT t.*, p.name product_name, p.image product_img FROM tryons t
                   LEFT JOIN products p ON p.id=t.product_id ORDER BY t.id DESC""")
    ok = [r for r in rows if r["status"] == "success"]
    secs = [r["seconds"] for r in ok if r["seconds"]]
    rated = [r for r in rows if r["rating"]]
    stats = {
        "total": len(rows), "success": len(ok), "errors": sum(r["status"] == "error" for r in rows),
        "visitors": len({r["visitor"] for r in rows}),
        "avg": round(sum(secs) / len(secs), 1) if secs else 0, "max": max(secs) if secs else 0,
        "up": sum(r["rating"] == 1 for r in rated), "down": sum(r["rating"] == -1 for r in rated),
        "today": db.q("SELECT COUNT(*) n FROM tryons WHERE date(created)=date('now')")[0]["n"],
    }
    visitors = db.q("""SELECT visitor, COUNT(*) n, SUM(status='success') ok, MIN(created) first, MAX(created) last,
                       ROUND(AVG(seconds),1) avg, MAX(ip) ip FROM tryons GROUP BY visitor ORDER BY last DESC""")
    top = db.q("""SELECT p.name, COUNT(*) n, SUM(t.rating=1) up, SUM(t.rating=-1) down FROM tryons t
                  JOIN products p ON p.id=t.product_id GROUP BY p.id ORDER BY n DESC LIMIT 10""")
    errs = db.q("SELECT substr(error,1,60) e, COUNT(*) n FROM tryons WHERE status='error' GROUP BY e ORDER BY n DESC")
    return tpl.TemplateResponse(request, "admin.html", {
        "rows": rows, "stats": stats, "visitors": visitors, "top": top, "errs": errs,
        "products": db.q("SELECT * FROM products ORDER BY id DESC"), "cats": CATS,
        "pexels": bool(os.getenv("PEXELS_API_KEY")), "samples": list(SAMPLES)})


@app.post("/admin/product", dependencies=[Depends(admin)])
def add_product(name: str = Form(...), category: str = Form("auto"), url: str = Form(""),
                file: UploadFile = File(None)):
    if file and file.filename:
        data = file.file.read()
    elif url:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.content
    else:
        raise HTTPException(400, "Give an image URL or a file.")
    db.run("INSERT INTO products(name,category,image,credit) VALUES(?,?,?,?)",
           (name, category, save_product_image(data), url[:300]))
    return RedirectResponse("/admin#products", 303)

SAMPLES = {  # keyless public demo catalogs with clean product photos
    "Men's shirts": ("https://dummyjson.com/products/category/mens-shirts", "products", "title", lambda x: x["images"][0], "upper_body"),
    "Women's tops": ("https://dummyjson.com/products/category/tops", "products", "title", lambda x: x["images"][0], "upper_body"),
    "Women's dresses": ("https://dummyjson.com/products/category/womens-dresses", "products", "title", lambda x: x["images"][0], "full_body"),
    "Men's clothing (Fake Store)": ("https://fakestoreapi.com/products/category/men's%20clothing", None, "title", lambda x: x["image"], "auto"),
    "Women's clothing (Fake Store)": ("https://fakestoreapi.com/products/category/women's%20clothing", None, "title", lambda x: x["image"], "auto"),
}


@app.post("/admin/import-sample", dependencies=[Depends(admin)])
def import_sample(group: str = Form(...)):
    url, key, namek, imgf, cat = SAMPLES[group]
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    items = r.json()[key] if key else r.json()
    have = {p["name"] for p in db.q("SELECT name FROM products")}
    for it in items:
        name = it[namek][:80]
        if name in have:
            continue
        data = requests.get(imgf(it), timeout=30, headers={"User-Agent": "Mozilla/5.0"}).content
        db.run("INSERT INTO products(name,category,image,credit) VALUES(?,?,?,?)",
               (name, cat, save_product_image(data), "Demo catalog image"))
    return RedirectResponse("/admin#products", 303)

@app.post("/admin/import", dependencies=[Depends(admin)])
def import_pexels(query: str = Form(...), category: str = Form("auto"), count: int = Form(8)):
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        raise HTTPException(400, "Set PEXELS_API_KEY in .env")
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=30,
                     params={"query": query, "per_page": min(count, 30), "orientation": "portrait"})
    r.raise_for_status()
    for i, ph in enumerate(r.json().get("photos", []), 1):
        data = requests.get(ph["src"]["large"], timeout=30).content
        db.run("INSERT INTO products(name,category,image,credit) VALUES(?,?,?,?)",
               (f"{query.title()} {i}", category, save_product_image(data), f"Photo by {ph['photographer']} on Pexels"))
    return RedirectResponse("/admin#products", 303)


@app.post("/admin/product/{pid}/delete", dependencies=[Depends(admin)])
def del_product(pid: int):
    db.run("DELETE FROM products WHERE id=?", (pid,))
    return RedirectResponse("/admin#products", 303)


@app.get("/admin/export.csv", dependencies=[Depends(admin)])
def export():
    rows = db.q("""SELECT t.id, t.created, t.visitor, t.ip, p.name product, t.category, t.status, t.error,
                   t.seconds, t.rating, t.comment, t.person_img, t.result_img, t.task_id, t.user_agent
                   FROM tryons t LEFT JOIN products p ON p.id=t.product_id ORDER BY t.id""")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["id"])
    w.writeheader(); w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=tryons.csv"})
