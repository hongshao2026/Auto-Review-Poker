"""Real loopback API integration: validation, isolation, jobs, and cancellation."""
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from preflop_lab import server


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "JOBS", server.JobManager())
    monkeypatch.setattr(server, "RUN_ROOT", tmp_path)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def request(path, data=None, headers=None, raw=None):
        encoded = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        req = Request(base + path, data=encoded, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(req, timeout=15) as response:
                return response.status, json.loads(response.read())
        except HTTPError as response:
            return response.code, json.loads(response.read())

    yield request
    with server.JOBS.lock:
        for job in server.JOBS.jobs.values():
            job.cancel_event.set()
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def hu_config(app, iterations=100):
    cfg = app("/api/meta")[1]["default_config"]
    cfg.update(players=[{"name": "SB", "stack": 4, "range": "AA"}, {"name": "BB", "stack": 4, "range": "KK"}],
               iterations=iterations, utility="chips", max_raises=1, payouts=[1, 0])
    return cfg


def await_job(app, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        _, job = app(f"/api/jobs/{job_id}")
        if job["status"] not in ("running", "cancelling"):
            return job
        time.sleep(0.02)
    pytest.fail("Small test job did not terminate within 20 seconds")


def test_meta_tree_and_bad_range(app):
    status, meta = app("/api/meta")
    assert status == 200 and len(meta["hand_labels"]) == 169
    cfg = hu_config(app)
    status, node = app("/api/tree", {"config": cfg, "path": []})
    assert status == 200 and node["actor"] == 0 and node["strategy"] is None
    assert {a["kind"] for a in node["actions"]} >= {"fold", "call"}
    cfg["players"][0]["range"] = "not-a-hand"
    status, error = app("/api/tree", {"config": cfg})
    assert status == 400 and error["error"]


def test_cross_site_post_and_private_files_are_blocked(app):
    status, _ = app("/api/jobs", {"config": hu_config(app)}, headers={"Origin": "https://unrelated.invalid"})
    assert status == 403
    assert app("/../research/HRC-FINDINGS.md")[0] == 404
    assert app("/%2e%2e/research/HRC-FINDINGS.md")[0] == 404
    assert app("/api/jobs", raw=b'{"config":{"ante":NaN}}')[0] == 400
    assert app("/api/jobs", {}, headers={"Content-Type": "text/plain"})[0] == 400


def test_real_job_export_and_node(app):
    status, created = app("/api/jobs", {"config": hu_config(app)})
    assert status == 202
    done = await_job(app, created["id"])
    assert done["status"] == "completed", done
    status, result = app(f"/api/jobs/{created['id']}/export")
    assert status == 200 and result["nodes"] and result["model"]["continuation"]
    status, root = app(f"/api/jobs/{created['id']}/node")
    assert status == 200 and root["strategy"]["hands"]["AA"]["visits"] > 0
    assert sum(root["strategy"]["hands"]["AA"]["frequencies"]) == pytest.approx(1)
    assert app("/api/jobs")[1]["jobs"][0]["id"] == created["id"]


def test_cancel_stops_background_computation(app):
    cfg = hu_config(app, 20000)
    cfg["players"][0]["range"] = cfg["players"][1]["range"] = "all"
    _, created = app("/api/jobs", {"config": cfg})
    assert app("/api/jobs", {"config": cfg})[0] == 409
    status, cancel = app(f"/api/jobs/{created['id']}/cancel", {})
    assert status == 200 and cancel["status"] in ("cancelling", "cancelled")
    done = await_job(app, created["id"])
    assert done["status"] == "cancelled", done


def test_icm_conserves_prize_pool(app):
    status, result = app("/api/icm", {"stacks": [10, 10, 10], "payouts": [50, 30, 20]})
    assert status == 200 and result["equities"] == pytest.approx([100 / 3] * 3)


def test_budget_stop_keeps_partial_result_without_claiming_completion(app):
    cfg = hu_config(app, 1000)
    cfg["players"][0]["range"] = cfg["players"][1]["range"] = "all"
    cfg["max_infosets"] = 100
    _, created = app("/api/jobs", {"config": cfg})
    done = await_job(app, created["id"])
    assert done["status"] == "failed" and done["error"]
    assert done["summary"]["status"] == "resource_limit"
    assert done["summary"]["iterations_completed"] < cfg["iterations"]
    assert done["progress"]["iteration"] == done["summary"]["iterations_completed"]
    status, result = app(f"/api/jobs/{created['id']}/export")
    assert status == 200 and result["summary"]["status"] == "resource_limit"
