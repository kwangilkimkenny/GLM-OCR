"""One-shot OCR smoke driver — uploads a sample doc, polls to completion, prints result.

Usage: ocr_smoke.py <image_path> [document_type] [table_structure(true|false)]
Runs against a backend already listening on 127.0.0.1:8000. Validates the
provisioned models + pipeline end-to-end (not a unit test).
"""
import json
import os
import sys
import time

import requests

BASE = os.environ.get("OCR_BASE", "http://127.0.0.1:8000")
POLL_DEADLINE_S = 300


def wait_healthy() -> bool:
    for _ in range(60):
        try:
            if requests.get(f"{BASE}/health", timeout=3).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def main() -> int:
    sample = sys.argv[1] if len(sys.argv) > 1 else "/home/kyle-777/문서/ocr/examples/source/page.png"
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "auto"
    table = sys.argv[3] if len(sys.argv) > 3 else "false"
    masking_level = sys.argv[4] if len(sys.argv) > 4 else "partial"

    if not wait_healthy():
        print("ERROR: server never became healthy")
        return 2
    print(f"server healthy | sample={sample.split('/')[-1]} document_type={doc_type} "
          f"table={table} masking_level={masking_level}")

    fname = sample.split("/")[-1]
    with open(sample, "rb") as fh:
        files = {"file": (fname, fh, "image/jpeg" if fname.lower().endswith((".jpg", ".jpeg")) else "image/png")}
        data = {
            "engine": "qwen",
            "document_type": doc_type,
            "auto_quality": "true",
            "table_structure": table,
            "masking_level": masking_level,
            "output_format": "markdown",
        }
        r = requests.post(f"{BASE}/api/v1/tasks/upload", files=files, data=data, timeout=120)
    print("upload HTTP", r.status_code)
    r.raise_for_status()
    task_id = r.json()["data"]["task_id"]
    print("task_id:", task_id)

    last = None
    deadline = time.time() + POLL_DEADLINE_S
    final = {}
    while time.time() < deadline:
        d = requests.get(f"{BASE}/api/v1/tasks/{task_id}", timeout=10).json().get("data", {})
        st = d.get("status")
        if (st, d.get("current_step")) != last:
            print(f"  status={st} progress={d.get('progress')} step={d.get('current_step')}")
            last = (st, d.get("current_step"))
        if st in ("completed", "failed"):
            final = d
            break
        time.sleep(2)
    else:
        print("ERROR: timed out")
        return 3

    print("\n=== FINAL status:", final.get("status"))
    if final.get("status") == "failed":
        print("error_message:", final.get("error_message"))
        return 4

    meta = final.get("metadata") or {}
    cls = meta.get("classified") or final.get("classified")
    if cls:
        print("classified document_type:", cls.get("document_type") if isinstance(cls, dict) else cls)

    md = final.get("full_markdown") or ""
    print(f"\n=== full_markdown ({len(md)} chars) — first 1500 ===")
    print(md[:1500])

    ef = final.get("extracted_fields")
    print("\n=== extracted_fields ===")
    print(json.dumps(ef, ensure_ascii=False, indent=2)[:1500] if ef else "none")

    cv = final.get("cross_validation")
    if cv:
        print("\n=== cross_validation ===")
        print(json.dumps(cv, ensure_ascii=False)[:600])

    pii = final.get("pii")
    print("\n=== pii ===")
    print(json.dumps(pii, ensure_ascii=False, indent=2)[:800] if pii else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
