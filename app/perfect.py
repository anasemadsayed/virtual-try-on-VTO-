"""Perfect Corp (YouCam) AI Clothes client: same flow as the notebook."""
import io, os, time, requests
from PIL import Image, ImageOps

BASE = "https://yce-api-01.makeupar.com"
FEATURE = "cloth-v4"


def prepare_jpeg(img, long_side=2048, quality=90):
    if isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(img))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > long_side:
        s = long_side / max(img.size)
        img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _headers():
    return {"Authorization": f"Bearer {os.getenv('PERFECT_API_KEY', '')}", "Content-Type": "application/json"}


def _check(resp, what):
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500]
    if resp.status_code >= 400:
        raise RuntimeError(f"{what} failed [{resp.status_code}]: {body}")
    return body


def upload(jpeg_bytes, name):
    r = requests.post(f"{BASE}/s2s/v2.0/file", headers=_headers(), timeout=60,
                      json={"files": [{"content_type": "image/jpg", "file_name": name, "file_size": len(jpeg_bytes)}]})
    f = _check(r, "File API")["data"]["files"][0]
    req = f["requests"][0]
    hdrs = {k: v for k, v in (req.get("headers") or {}).items() if k.lower() != "content-length"}
    hdrs.setdefault("Content-Type", "image/jpg")
    u = requests.request(req.get("method", "PUT"), req["url"], headers=hdrs, data=jpeg_bytes, timeout=120)
    if u.status_code >= 400:
        raise RuntimeError(f"Upload failed [{u.status_code}]: {u.text[:300]}")
    return f["file_id"]


def run_tryon(person_bytes, product_bytes, category="auto", poll_every=2, timeout=180):
    """Returns (result_png_bytes, task_id, api_seconds). Raises RuntimeError with the API error code."""
    t0 = time.time()
    src = upload(prepare_jpeg(person_bytes), "person.jpg")
    ref = upload(prepare_jpeg(product_bytes), "garment.jpg")
    r = requests.post(f"{BASE}/s2s/v2.0/task/{FEATURE}", headers=_headers(), timeout=60,
                      json={"src_file_id": src, "ref_file_id": ref, "garment_category": category})
    task_id = _check(r, "Create task")["data"]["task_id"]
    while time.time() - t0 < timeout:
        time.sleep(poll_every)
        d = _check(requests.get(f"{BASE}/s2s/v2.0/task/{FEATURE}/{task_id}", headers=_headers(), timeout=60), "Poll")["data"]
        status = d.get("task_status")
        if status == "success":
            res = d["results"]
            url = res["url"] if isinstance(res, dict) else res[0]["url"]
            png = requests.get(url, timeout=120).content
            return png, task_id, round(time.time() - t0, 2)
        if status == "error":
            raise RuntimeError(f"{d.get('error')}: {d.get('error_message')}")
    raise TimeoutError("Task did not finish in time")
