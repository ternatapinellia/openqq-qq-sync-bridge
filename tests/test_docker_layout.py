# -*- coding: utf-8 -*-
"""Docker 版布局与行为测试（不需要 docker，本机 python 即可跑）。

检查：
  1. docker/bridge.py 与 src/bridge.py 完全一致（避免两份源码走偏）
  2. Dockerfile / docker-compose.yml / .dockerignore 的关键设置
  3. entrypoint.sh 的关键逻辑
  4. docker/bridge.py 在「容器参数」下真的能跑：监听 0.0.0.0、令牌校验、/health 开放
"""
import io, json, os, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from seadice_fixture import make_data_db, make_logs_db  # noqa: E402

DOCKER = os.path.join(ROOT, "docker")
FAILURES = []
CHECKS = [0]


def check(cond, label, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  PASS  %s" % label)
    else:
        print("  FAIL  %s   %s" % (label, detail))
    if not cond:
        FAILURES.append(label)


def read(p):
    return io.open(p, encoding="utf-8").read()


print("=== 1. 源码一致性 ===")
a = read(os.path.join(ROOT, "src", "bridge.py"))
b = read(os.path.join(DOCKER, "bridge.py"))
check(a == b, "docker/bridge.py 与 src/bridge.py 一致")
js_a = read(os.path.join(ROOT, "src", "OpenQQ-QQ-Sync-v2.0.js"))
for folder in ("docker", "windows"):
    check(read(os.path.join(ROOT, folder, "OpenQQ-QQ-Sync-v2.0.js")) == js_a,
          "%s/OpenQQ-QQ-Sync-v2.0.js 与 src 一致" % folder)

print("\n=== 2. Dockerfile / compose ===")
df = read(os.path.join(DOCKER, "Dockerfile"))
check("FROM python:" in df, "Dockerfile 有基础镜像")
check("COPY bridge.py" in df and "COPY entrypoint.sh" in df, "Dockerfile 会拷入桥代码与入口脚本")
check("OPENQQ_BRIDGE_ROOT=/config" in df, "Dockerfile 设置配置目录 /config")
check("OPENQQ_BRIDGE_DATA_DIR=/data" in df, "Dockerfile 设置数据目录 /data")
check("HEALTHCHECK" in df and "/health" in df, "Dockerfile 带 /health 健康检查")
check("USER " in df, "Dockerfile 使用非 root 用户运行")
check("EXPOSE 38999" in df, "Dockerfile 暴露 38999")

compose = read(os.path.join(DOCKER, "docker-compose.yml"))
check("/data" in compose and "/config" in compose, "compose 挂载 /data 与 /config")
check("127.0.0.1:38999:38999" in compose, "compose 默认只映射到宿主机回环")
check("OPENQQ_BRIDGE_TOKEN" in compose, "compose 强制要求令牌")

checks = read(os.path.join(DOCKER, "entrypoint.sh"))
check("data.db" in checks and "data-logs.db" in checks, "entrypoint 会检查海豹数据库是否存在")
check("0.0.0.0" in checks, "entrypoint 让桥监听 0.0.0.0")
check("OPENQQ_BRIDGE_TOKEN" in checks, "entrypoint 会提示未设置令牌")

print("\n=== 2b. entrypoint 端口优先级 ===")
# bridge_port.txt 必须优先于 OPENQQ_BRIDGE_PORT，且非法值要回退到环境变量。
import subprocess as _sp
_epcase = os.path.join(tempfile.gettempdir(), "openqq_ep_case")
if os.path.isdir(_epcase):
    shutil.rmtree(_epcase, ignore_errors=True)
os.makedirs(os.path.join(_epcase, "cfg"))
os.makedirs(os.path.join(_epcase, "data"))
os.makedirs(os.path.join(_epcase, "bin"))
open(os.path.join(_epcase, "data", "data.db"), "wb").close()
open(os.path.join(_epcase, "data", "data-logs.db"), "wb").close()
io.open(os.path.join(_epcase, "bin", "python"), "w", encoding="utf-8", newline="\n").write(
    "#!/bin/sh\necho \"ARGS: [$*]\"\n")
os.chmod(os.path.join(_epcase, "bin", "python"), 0o755)

_bash = None
for cand in (r"C:\Program Files\Git\bin\bash.exe", "/bin/sh"):
    if os.path.exists(cand):
        _bash = cand
        break


def _win2sh(p):
    p = p.replace("\\", "/")
    return "/" + p[0].lower() + p[2:]


if _bash and os.path.exists(_bash):
    def _run_ep(txt, env_port):
        tf = os.path.join(_epcase, "cfg", "bridge_port.txt")
        if os.path.exists(tf):
            os.remove(tf)
        if txt is not None:
            io.open(tf, "w", encoding="utf-8", newline="\n").write(txt + "\n")
        env = dict(os.environ)
        env["OPENQQ_BRIDGE_DATA_DIR"] = _win2sh(os.path.join(_epcase, "data"))
        env["OPENQQ_BRIDGE_ROOT"] = _win2sh(os.path.join(_epcase, "cfg"))
        env["OPENQQ_BRIDGE_PORT"] = str(env_port)
        env["OPENQQ_BRIDGE_TOKEN"] = "tok"
        env["PATH"] = _win2sh(os.path.join(_epcase, "bin")) + ":" + env.get("PATH", "")
        r = _sp.run([_bash, _win2sh(os.path.join(DOCKER, "entrypoint.sh"))],
                    capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        line = ""
        for l in r.stdout.splitlines():
            if l.startswith("ARGS:"):
                line = l
        return line

    got = _run_ep("39777", 39999)
    check("--port 39777" in got, "bridge_port.txt 优先于环境变量", got)
    got = _run_ep(None, 39999)
    check("--port 39999" in got, "无 txt 时使用环境变量端口", got)
    got = _run_ep("abc", 39999)
    check("--port 39999" in got, "txt 非法时回退到环境变量", got)
    got = _run_ep("99999", 39999)
    check("--port 39999" in got, "txt 超范围时回退到环境变量", got)
    shutil.rmtree(_epcase, ignore_errors=True)
else:
    print("  SKIP  bash 不可用，跳过 entrypoint 测试")

print("\n=== 3. docker/bridge.py 容器参数实测 ===")
W = os.path.join(tempfile.gettempdir(), "openqq_docker_probe")
if os.path.isdir(W):
    for r, d, fs in os.walk(W):
        for f in fs:
            try: os.chmod(os.path.join(r, f), 0o666)
            except Exception: pass
    shutil.rmtree(W, ignore_errors=True)
cfg, data, port = os.path.join(W, "cfg"), os.path.join(W, "data"), 39555
os.makedirs(cfg, exist_ok=True); os.makedirs(data, exist_ok=True)
make_data_db(os.path.join(data, "data.db"))
make_logs_db(os.path.join(data, "data-logs.db"), [])

env = dict(os.environ, OPENQQ_BRIDGE_ROOT=cfg, OPENQQ_BRIDGE_TOKEN="tok-abc-123")
logp = os.path.join(W, "b.log")
log = io.open(logp, "w", encoding="utf-8")
p = subprocess.Popen([sys.executable, os.path.join(DOCKER, "bridge.py"),
                      "--host", "0.0.0.0", "--port", str(port), "--data-dir", data],
                     stdout=log, stderr=subprocess.STDOUT, text=True, env=env)
def get(path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
try:
    booted = False
    for _ in range(60):
        time.sleep(0.4)
        if p.poll() is not None:
            break
        try:
            st, body = get("/health"); booted = True; break
        except Exception:
            pass
    check(booted, "服务在容器参数下启动成功", read(logp)[-400:] if os.path.exists(logp) else "")
    if booted:
        check(st == 200 and json.loads(body).get("ok") is True, "/health 无需令牌即可访问", "%s %s" % (st, body))
        st, body = get("/lookup?old=1721175359")
        check(st == 401, "无令牌访问 /lookup -> 401", "%s %s" % (st, body))
        st, body = get("/lookup?old=1721175359&token=tok-abc-123")
        check(st == 200 and json.loads(body).get("character_count") == 3, "带正确令牌 -> 200", "%s %s" % (st, body))
finally:
    p.terminate()
    try: p.wait(timeout=10)
    except Exception: p.kill()
    log.close()
shutil.rmtree(W, ignore_errors=True)

print("\n" + "=" * 56)
print("checks: %d   failures: %d" % (CHECKS[0], len(FAILURES)))
if FAILURES:
    for f in FAILURES:
        print("  - %s" % f)
    sys.exit(1)
print("ALL DOCKER LAYOUT TESTS PASSED")