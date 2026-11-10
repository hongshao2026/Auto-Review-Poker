"""Loopback-only application server for the independent preflop research engine."""
from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import re
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .core import ResearchSolver, default_config, icm_equities
from .cards import HAND_LABELS
from .hrc_benchmarks import ENGINE as HRC_ENGINE, public_metadata
from .tournament import ENGINE as TOURNAMENT_ENGINE, public_metadata as tournament_metadata
from .hrc_custom import ENGINE as CUSTOM_ENGINE, public_metadata as custom_metadata

NATIVE_ENGINES = (HRC_ENGINE, TOURNAMENT_ENGINE, CUSTOM_ENGINE, 'hrc_imported')

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
RUN_ROOT = ROOT / ".runs"
MAX_BODY = 512 * 1024
MODEL = {
    "title": "抽样 CFR · 翻前研究模型",
    "continuation": "翻前下注结束后，抽样公共牌并过牌到摊牌；没有翻后下注。",
    "limitations": [
        "范围只覆盖设置的开池、再加注尺度与全下动作；不是连续下注空间。",
        "平跟后采用过牌到摊牌的续局模型，未建模翻后权益实现，结果不等同于 HRC。",
        "采用 169 起手牌类别、真实组合与阻断牌抽样；未访问的手牌和节点显示为未训练。",
        "有限抽样结果会随种子和迭代数变化；迭代完成不代表达到纳什均衡。",
        "多人或 ICM 效用下不提供均衡收敛保证；当前没有计算可利用度。",
    ],
}
EVIDENCE = [
    {"title": "HRC 翻前／翻后树配置", "url": "https://www.holdemresources.net/docs/tree-config/", "note": "HRC 使用抽象翻后树估计权益实现；关闭翻后建树时有过牌到摊牌的假设。"},
    {"title": "HRC v3：翻后模型", "url": "https://www.holdemresources.net/blog/2023-hrc-v3-release/", "note": "用于区分完整求解流程与当前研究模型。"},
    {"title": "Monte Carlo CFR 原始论文", "url": "https://mlanctot.info/files/papers/nips09mccfr.pdf", "note": "本项目独立实现的抽样遗憾最小化方法来源。"},
    {"title": "PokerHandEvaluator", "url": "https://github.com/HenryRLee/PokerHandEvaluator", "note": "开源牌型评估依赖，版本与许可证见项目文档。"},
]


class JobConflict(ValueError):
    pass


def make_solver(config):
    if isinstance(config, dict) and config.get('engine') == 'hrc_imported':
        from .hrc_imported import HRCImportedSolver
        return HRCImportedSolver(config)
    if isinstance(config, dict) and config.get('engine') == CUSTOM_ENGINE:
        from .hrc_custom import HRCCustomSolver
        return HRCCustomSolver(config)
    if isinstance(config, dict) and config.get('engine') == TOURNAMENT_ENGINE:
        from .hrc_tournament import HRCTournamentSolver
        return HRCTournamentSolver(config)
    if isinstance(config, dict) and config.get('engine') == HRC_ENGINE:
        from .hrc_research import HRCResearchSolver
        return HRCResearchSolver(config)
    if isinstance(config, dict) and config.get('engine'):
        raise ValueError('未知求解内核。')
    return ResearchSolver(config)


class Job:
    def __init__(self, solver: ResearchSolver):
        self.id = uuid.uuid4().hex
        self.solver = solver
        self.config = copy.deepcopy(solver.config)
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.started = time.monotonic()
        self.elapsed_seconds = 0.0
        self.status = "running"
        self.progress = {"iteration": 0, "total": self.config["iterations"]}
        self.error = None
        self.result = None
        self.restored = False
        self.parent_job_id = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            elapsed = time.monotonic() - self.started if self.status in ("running", "cancelling") else self.elapsed_seconds
            return {
                "id": self.id, "status": self.status, "created_at": self.created_at,
                "config": self.config, "progress": dict(self.progress),
                "elapsed_seconds": round(elapsed, 2), "error": self.error,
                "summary": self.result.get("summary") if self.result else None,
                "has_source_strategy": self.config.get('engine') == 'hrc_imported',
                "restored": self.restored, "parent_job_id": self.parent_job_id,
                "can_export_archive": self.result is not None and getattr(self.solver, 'output', None) is not None,
                "can_export_hrcz": self.result is not None and self.config.get('engine') in NATIVE_ENGINES
                    and (getattr(self.solver, 'output', None) is not None or getattr(self.solver, 'source', None) is not None),
                "can_resume": self.status in ('completed', 'cancelled') and self.config.get('engine') in NATIVE_ENGINES
                              and getattr(self.solver, 'output', None) is not None and getattr(self.solver, 'training_supported', True),
            }

    def update_progress(self, progress):
        with self.lock:
            self.progress.update(progress)

    def run(self):
        try:
            result = self.solver.run(self.config["iterations"], self.update_progress, self.cancel_event.is_set)
            result["model"] = getattr(self.solver, 'model', MODEL)
            result["job_id"] = self.id
            result["created_at"] = self.created_at
            result['parent_job_id'] = self.parent_job_id
            # Serialize before declaring success: nonfinite/incomplete output is an error.
            text = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            RUN_ROOT.mkdir(exist_ok=True)
            temp = RUN_ROOT / f"{self.id}.json.part"
            temp.write_text(text, encoding="utf-8")
            temp.replace(RUN_ROOT / f"{self.id}.json")
            with self.lock:
                self.result = result
                self.progress["iteration"] = result.get("summary", {}).get("iterations_completed", self.progress["iteration"])
                solver_status = result.get("summary", {}).get("status")
                if solver_status == "resource_limit":
                    self.status = "failed"
                    self.error = "达到研究模型的资源上限；已保留部分结果，可查看或导出。请减少玩家数、下注尺度或加注次数。"
                else:
                    self.status = "cancelled" if solver_status == "cancelled" or self.cancel_event.is_set() else "completed"
        except Exception as error:
            with self.lock:
                self.error = str(error) or type(error).__name__
                self.status = "failed"
            RUN_ROOT.mkdir(exist_ok=True)
            (RUN_ROOT / f"{self.id}.error.log").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            with self.lock:
                self.elapsed_seconds = time.monotonic() - self.started

    def node(self, path):
        # Browsing must not mutate the running trainer's cached tree or consume its budget.
        if self.config.get('engine') in NATIVE_ENGINES:
            # Expose only a completed checkpoint; running writes are never read.
            with self.lock:
                completed = self.result is not None
                if completed and getattr(self.solver, 'output', None) is None and self.config.get('engine') != 'hrc_imported':
                    node = self.solver.describe_node(path)
                    node['strategy'] = self.result.get('nodes', {}).get(node['id'])
                    node['checkpoint_available'] = False
                    return node
            return self.solver.result_node(path) if completed else self.solver.describe_node(path)
        node = make_solver(self.config).describe_node(path)
        with self.lock:
            node["strategy"] = self.result.get("nodes", {}).get(node["id"]) if self.result else None
        return node


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, config, *, resume_job=None, reset_regret=False, reset_average=False, checkpoint_migration='reject'):
        if type(reset_regret) is not bool or type(reset_average) is not bool:
            raise ValueError('reset_regret 与 reset_average 必须为布尔值。')
        if checkpoint_migration not in ('reject', 'preserve', 'reset'):
            raise ValueError('checkpoint_migration 必须为 reject、preserve 或 reset。')
        if (isinstance(config,dict) and config.get('sampling_scope')=='selected_subtree'
            and resume_job is None and config.get('engine')!='hrc_imported'):
            raise ValueError('Selected Subtree 需要先初始化或载入手牌，再从已有结果继续计算。')
        if resume_job is None:
            solver = make_solver(config)
        else:
            from .hrc_restore import restore_solver
            solver = restore_solver(config, resume_job.solver.tree)
            solver.archive = resume_job.solver.archive
        if resume_job is not None:
            if not resume_job.snapshot()['can_resume']:
                raise JobConflict('此任务没有可恢复的原生检查点。')
            completed = resume_job.result['summary'].get('iterations_completed', 0)
            if solver.config['iterations'] <= completed:
                raise ValueError('续跑目标次数必须大于已完成次数。')
            solver.resume_from = resume_job.solver.output / 'checkpoint.bin'
            solver.reset_regret, solver.reset_average = reset_regret, reset_average
            solver.checkpoint_migration = checkpoint_migration
            solver.tree = resume_job.solver.tree
            if hasattr(resume_job.solver, 'resource_dir'):
                solver.resource_dir = resume_job.solver.resource_dir
        with self.lock:
            if any(job.status in ("running", "cancelling") for job in self.jobs.values()):
                raise JobConflict("已有求解任务正在运行，请等待完成或先取消。")
            # Results are also exported to .runs; cap memory retained by this process.
            while len(self.jobs) >= 8:
                del self.jobs[next(iter(self.jobs))]
            job = Job(solver)
            if resume_job is not None:
                job.parent_job_id = resume_job.id
            self.jobs[job.id] = job
            threading.Thread(target=job.run, name=f"solver-{job.id[:8]}", daemon=True).start()
            return job

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                if not isinstance(job_id, str) or not re.fullmatch('[0-9a-f]{32}', job_id):
                    raise KeyError('无效任务 ID。')
                file = RUN_ROOT / f'{job_id}.json'
                if not file.is_file():
                    raise KeyError('找不到此任务。')
                result = json.loads(file.read_text(encoding='utf-8'))
                if result.get('job_id') != job_id:
                    raise ValueError('保存结果的任务 ID 不一致。')
                artifacts = result.get('native_artifacts', {})
                folder = None
                if artifacts and result['config'].get('engine') in NATIVE_ENGINES:
                    from .hrc_benchmarks import CACHE
                    folder = Path(artifacts['checkpoint_path']).resolve().parent
                    if not folder.is_relative_to(CACHE.resolve()) or not (folder / 'checkpoint.bin').is_file() or not (folder / 'index.json').is_file():
                        folder = None
                if folder is not None and (folder / 'tree-snapshot.json').is_file():
                    from .hrc_snapshot import load_tree
                    from .hrc_restore import restore_solver
                    solver = restore_solver(result['config'], load_tree(folder / 'tree-snapshot.json'))
                    if not result.get('imported_archive') and solver.config.get('benchmark'):
                        from .hrc_benchmarks import archive_for
                        try:
                            solver.archive = archive_for(solver.config['benchmark'])
                        except ValueError:
                            pass
                else:
                    solver = make_solver(result['config'])
                if folder is not None:
                        solver.output = folder
                        solver.index = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
                        if (folder / 'tree-snapshot.json').is_file():
                            from .hrc_snapshot import load_tree
                            solver.tree = load_tree(folder / 'tree-snapshot.json')
                        resource_dir = Path(artifacts.get('resources_path', CACHE / 'abstractions')).resolve()
                        if resource_dir.is_relative_to(CACHE.resolve()):
                            solver.resource_dir = resource_dir
                        if (solver.config['engine'] == HRC_ENGINE and not result.get('imported_archive') and solver.archive
                            and not solver.config.get('policies', {}).get('nodes')):
                            from .hrc_research import Reference
                            solver.reference = Reference(solver.archive)
                        elif solver.config['engine'] == TOURNAMENT_ENGINE and not result.get('imported_archive') and solver.archive:
                            from .hrc_tournament_reference import matching_reference
                            solver.reference = matching_reference(solver)
                job = Job(solver)
                job.id, job.result, job.restored = job_id, result, True
                job.created_at = result.get('created_at', job.created_at)
                summary = result['summary']
                job.status = 'cancelled' if summary.get('status') == 'cancelled' else 'failed' if summary.get('status') == 'resource_limit' else 'completed'
                job.elapsed_seconds = summary.get('elapsed_seconds', 0)
                job.progress = {'iteration': summary.get('iterations_completed', 0), 'total': job.config['iterations']}
                job.parent_job_id = result.get('parent_job_id')
                while len(self.jobs) >= 8:
                    removable = next((key for key, item in self.jobs.items() if item.status not in ('running', 'cancelling')), None)
                    if removable is None:
                        break
                    del self.jobs[removable]
                self.jobs[job_id] = job
            return self.jobs[job_id]

    def history(self):
        with self.lock:
            current = {key: job.snapshot() for key, job in self.jobs.items()}
        # Disk history is separate from the bounded resident solver cache.
        files = sorted(RUN_ROOT.glob('*.json'), key=lambda file: file.stat().st_mtime, reverse=True)[:100]
        for file in files:
            if file.stem in current or not re.fullmatch('[0-9a-f]{32}', file.stem):
                continue
            try:
                row = json.loads(file.read_text(encoding='utf-8'))
                summary = row['summary']
                if row['job_id'] != file.stem:
                    continue
                current[file.stem] = {'id': file.stem, 'created_at': row.get('created_at', ''), 'config': row['config'],
                    'status': 'cancelled' if summary.get('status') == 'cancelled' else 'failed' if summary.get('status') == 'resource_limit' else 'completed',
                    'progress': {'iteration': summary.get('iterations_completed', 0), 'total': row['config']['iterations']},
                    'elapsed_seconds': summary.get('elapsed_seconds', 0), 'summary': summary, 'error': None, 'restored': True,
                    'parent_job_id': row.get('parent_job_id'), 'can_resume': False}
            except (OSError, KeyError, TypeError, ValueError):
                continue
        return sorted(current.values(), key=lambda row: row['created_at'], reverse=True)[:100]


JOBS = JobManager()


def checked_path(value):
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(a, str) or len(a) > 80 for a in value):
        raise ValueError("动作路径必须是最多 100 项的动作 ID 数组。")
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "PreflopLab/0.1"

    def log_message(self, fmt, *args):
        print(f"[http] {self.command} {self.path.split('?')[0]} {fmt % args}", flush=True)

    def common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")

    def send_json(self, body, status=200, filename=None):
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(encoded)

    def check_local(self, mutation=False):
        host = urlsplit("http://" + self.headers.get("Host", ""))
        if host.hostname not in ("127.0.0.1", "localhost", "::1") or host.port != self.server.server_port:
            raise PermissionError("此应用只接受本机地址。")
        origin = self.headers.get("Origin")
        if mutation and origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.port != self.server.server_port:
                raise PermissionError("拒绝其他网站发起的求解请求。")

    def body(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求必须使用 application/json。")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY:
            raise ValueError("请求体为空或超过 512 KB。")
        def invalid_constant(value):
            raise ValueError(f"不支持数值 {value}。")
        body = json.loads(self.rfile.read(length), parse_constant=invalid_constant)
        if not isinstance(body, dict):
            raise ValueError("请求内容必须是 JSON 对象。")
        return body

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, mutation):
        try:
            self.check_local(mutation)
            if mutation:
                if urlsplit(self.path).path == '/api/import':
                    self.import_calculation()
                else:
                    self.post(urlsplit(self.path).path, self.body())
            else:
                self.get(urlsplit(self.path))
        except PermissionError as error:
            self.send_json({"error": str(error)}, 403)
        except JobConflict as error:
            self.send_json({"error": str(error)}, 409)
        except (ValueError, TypeError, IndexError) as error:
            self.send_json({"error": str(error)}, 400)
        except KeyError as error:
            self.send_json({"error": str(error).strip("'\"")}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            self.send_json({"error": "应用遇到内部错误，请查看服务器日志。"}, 500)

    def import_calculation(self):
        from .hrc_hrcz import MAX_ARCHIVE, import_calculation
        if self.headers.get_content_type() not in ('application/octet-stream', 'application/zip'):
            raise ValueError('完整存档需要 application/octet-stream 二进制文件。')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= MAX_ARCHIVE:
            raise ValueError('存档为空或超过 1 GiB 上限。')
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='upload-', dir=RUN_ROOT) as temp:
            path = Path(temp) / 'calculation.plabz'
            with path.open('wb') as stream:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('存档上传未完成。')
                    stream.write(chunk)
                    remaining -= len(chunk)
            try:
                identity = import_calculation(path, RUN_ROOT)
            except Exception as error:
                raise ValueError(f'无法导入完整存档：{error}') from error
        return self.send_json(JOBS.get(identity).snapshot(), 201)

    def send_file(self, file, media_type, filename):
        self.send_response(200)
        self.common_headers()
        self.send_header('Content-Type', media_type)
        self.send_header('Content-Length', str(file.stat().st_size))
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        with file.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                self.wfile.write(chunk)

    def post(self, path, body):
        if path == '/api/strategy-table':
            from .hrc_strategy_table import strategy_branch
            branch_path = checked_path(body.get('path', []))
            if body.get('job_id'):
                job = JOBS.get(body['job_id'])
                return self.send_json(strategy_branch(job.solver, branch_path, read_node=job.node))
            return self.send_json(strategy_branch(make_solver(body.get('config', {})), branch_path))
        if path == "/api/tree":
            solver = make_solver(body.get("config", {}))
            node = solver.describe_node(checked_path(body.get("path", [])))
            node["strategy"] = None
            return self.send_json(node)
        if path == "/api/jobs":
            return self.send_json(JOBS.start(body.get("config", {})).snapshot(), 202)
        if path == "/api/icm":
            return self.send_json({"equities": icm_equities(body.get("stacks", []), body.get("payouts", []))})
        if path == '/api/tournament-analysis':
            from .hrc_analysis import analyze_solver
            return self.send_json(analyze_solver(make_solver(body.get('config', {}))))
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
            job = JOBS.get(parts[2])
            with job.lock:
                if job.status == "running":
                    job.status = "cancelling"
                    job.cancel_event.set()
            return self.send_json(job.snapshot())
        if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'resume':
            previous = JOBS.get(parts[2])
            config = copy.deepcopy(body.get('config', previous.config))
            if not isinstance(config, dict):
                raise ValueError('续跑 config 必须为对象。')
            from .hrc_sampling import RUN_CONTROLS, MAX_SAMPLES
            if 'stopping_mode' in body:
                config.pop('target_ci',None);config.pop('stop_after_seconds',None)
            if body.get('sampling_scope')=='entire_tree':config['sampling_path']=[]
            config.update({key:copy.deepcopy(body[key]) for key in RUN_CONTROLS if key in body})
            config['sampling_stage']=body.get('sampling_stage','calculation')
            config['iterations'] = body.get('iterations', MAX_SAMPLES if config.get('stopping_mode') in ('ci','time') else None)
            return self.send_json(JOBS.start(config, resume_job=previous,
                                           reset_regret=body.get('reset_regret', False),
                                           reset_average=body.get('reset_average', False),
                                           checkpoint_migration=body.get('checkpoint_migration', 'reject')).snapshot(), 202)
        raise KeyError("接口不存在。")

    def get(self, parsed):
        path = parsed.path
        if path == "/api/health":
            return self.send_json({"app": "preflop-lab", "version": "0.1.0", "status": "ready"})
        if path == "/api/meta":
            from .hrc_fgs_config import DEFAULTS as FGS_DEFAULTS, LIMITATIONS as FGS_LIMITATIONS
            from .hrc_rake import DEFAULTS as RAKE_DEFAULTS
            return self.send_json({"default_config": default_config(), "hand_labels": HAND_LABELS, "model": MODEL, "evidence": EVIDENCE, "research": public_metadata(), "tournament": tournament_metadata(), "custom_native": custom_metadata(),
                "persistence": {"archive_export": True, "archive_import": True, "hrcz_import": True, "hrcz_export": True, "max_import_bytes": 1024*1024*1024},
                "imported": {"engine": "hrc_imported", "model": {"title": "HRC 存档", "limitations": ["原档未保存随机数与逐手访问历史；导入后新增采样单独计数。"]}},
                "training": {"solver_modes": ["v3", "v4"], "max_threads":32, "track_ci": True, "policies": True,
                             "stopping_modes": ["samples", "ci", "time"], "default_stopping_mode": "ci", "default_ci": 10.0,
                             "sampling_scopes": ["entire_tree", "selected_subtree"], "selected_subtree_streets": [0],
                             "initialization_samples": 10_000_000,
                             "ci_semantics": "recent_strategy_drift_not_error_percent", "sampling_dialog": True,
                             "constant_scalar_shortcuts": {"default": True, "utility": "chip_ev_only"},
                             "reset_regret": True, "reset_average": True,
                             "street_formats": [25, 27, 31], "checkpoint_migration": ["reject", "preserve", "reset"]},
                "fgs": {"defaults": FGS_DEFAULTS, "limitations": FGS_LIMITATIONS},
                "rake": {"defaults": RAKE_DEFAULTS, "modes": ["none", "nfnd", "gg", "full"]},
                "tournament_analysis": {"bubble_factors": True, "risk_premiums": True}})
        if path == "/api/jobs":
            return self.send_json({"jobs": JOBS.history()})
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'tournament-analysis':
            from .hrc_analysis import analyze_solver
            return self.send_json(analyze_solver(JOBS.get(parts[2]).solver))
        if len(parts) in (3, 4) and parts[:2] == ["api", "jobs"]:
            job = JOBS.get(parts[2])
            if len(parts) == 3:
                return self.send_json(job.snapshot())
            if parts[3] == "node":
                action_path = json.loads(parse_qs(parsed.query).get("path", ["[]"])[0])
                return self.send_json(job.node(checked_path(action_path)))
            if parts[3] == "export":
                with job.lock:
                    result = job.result
                if result is None:
                    raise JobConflict("此任务尚未产生可导出的结果。")
                return self.send_json(result, filename=f"preflop-{job.id[:8]}.json")
            if parts[3] == 'hrcz':
                from .hrc_hrcz import export_hrcz
                option = parse_qs(parsed.query).get('resources', ['0'])[0]
                if option not in ('0', '1'):
                    raise ValueError('resources 必须为 0 或 1。')
                file = export_hrcz(job, option == '1')
                return self.send_file(file, 'application/zip', f'preflop-{job.id[:8]}.hrcz')
            if parts[3] == 'archive':
                from .hrc_archive import export_archive
                option = parse_qs(parsed.query).get('resources', ['0'])[0]
                if option not in ('0', '1'):
                    raise ValueError('resources 必须为 0 或 1。')
                file = export_archive(job, option == '1')
                return self.send_file(file, 'application/zip', f'preflop-{job.id[:8]}.plabz')
        if path.startswith("/api/"):
            raise KeyError("接口不存在。")
        requested = "index.html" if path == "/" else unquote(path).lstrip("/")
        file = (WEB_ROOT / requested).resolve()
        if not file.is_relative_to(WEB_ROOT.resolve()) or not file.is_file():
            raise KeyError("页面不存在。")
        payload = file.read_bytes()
        media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.common_headers()
        self.send_header("Content-Type", media_type + ("; charset=utf-8" if media_type.startswith("text/") or file.suffix == ".js" else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Preflop Lab: http://127.0.0.1:{args.port}", flush=True)
    if args.open_browser:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        with JOBS.lock:
            for job in JOBS.jobs.values():
                job.cancel_event.set()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
