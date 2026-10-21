# OpenQQ QQ Sync Bridge (OpenQQ 与旧 QQ 数据迁移同步桥)

把旧 QQ 的角色卡、群属性和 log 迁移到 OpenQQ 账号上的工具。由两部分组成：

- **同步桥 (bridge)**：一个小型 HTTP 服务，直接读写海豹 (SeaDice) 的 `data.db` 与 `data-logs.db`。
- **海豹插件 (js)**：插件里的指令（`.旧QQ绑定` / `.旧QQ验证码` 等）调用同步桥完成迁移。

本仓库同时提供 **Windows 版** 和 **Linux / Docker 版**，两端共用同一份 `src/bridge.py`。

## 目录

```
src/                       唯一的源码（两端共用，勿单独修改别处副本）
  bridge.py                同步桥本体（纯标准库，无第三方依赖）
  OpenQQ-QQ-Sync-v2.0.js   海豹插件

windows/                   Windows 直接使用（解压即用）
  OpenQQ-QQ-Sync-Bridge-v2.0.exe
  启动OpenQQ同步桥-v2.0.cmd
  OpenQQ-QQ-Sync-v2.0.js
  bridge_port.txt
  email_config.example.json
  README-v2.0.txt

docker/                    Linux / Docker 使用（把这个文件夹拷到服务器即可）
  Dockerfile
  docker-compose.yml
  entrypoint.sh
  build-and-run.sh
  .env.example
  bridge.py                 构建上下文用的副本（由 src 同步而来）
  OpenQQ-QQ-Sync-v2.0.js
  config/                   bridge_port.txt、email_config.example.json

tests/                     回归测试（不需要 docker、不需要真实海豹数据）
  test_bridge.py
  test_docker_layout.py
  seadice_fixture.py
```

## 用它做什么

1. 在海豹里加载 `OpenQQ-QQ-Sync-v2.0.js`，填好发件邮箱和 SMTP 授权码。
2. 启动同步桥（Windows 双击 cmd；Linux 用 docker compose）。
3. 在目标群里执行 `.旧QQ绑定 <旧QQ> <旧群号>`，把收到的 6 位验证码用 `.旧QQ验证码 <验证码>` 提交。
4. 验证通过后，旧 QQ 的角色卡、群属性、log 会被复制到当前 OpenQQ 账号/群。

> 迁移是**一次性快照复制**：只在验证码通过那一刻执行一次。之后两份数据各自独立，不会持续同步。

## Windows 用法

见 [windows/README-v2.0.txt](windows/README-v2.0.txt)。要点：

1. 把 `windows/` 里的文件放到海豹主程序同级目录（和 `data/` 平行）。
2. 双击 `启动OpenQQ同步桥-v2.0.cmd`，保持运行，不要关。
3. 插件加载 `OpenQQ-QQ-Sync-v2.0.js`。

同步桥默认只监听 `127.0.0.1`，即只有本机能访问。

## Linux / Docker 用法

见 [docker/README-DOCKER.md](docker/README-DOCKER.md)。快速上手：

```sh
cd docker
cp .env.example .env      # 填 SEALDICE_DATA_DIR 和 OPENQQ_BRIDGE_TOKEN
./build-and-run.sh        # 或 docker compose up -d --build
curl http://127.0.0.1:38999/health
```

容器里同步桥监听 `0.0.0.0:38999`，通过端口映射让海豹访问。**因为监听范围变大了，务必设置访问令牌**（见下）。

## 访问令牌

- Windows 本地使用：默认无令牌，行为和以前一致。
- Docker / 远程使用：建议设置 `OPENQQ_BRIDGE_TOKEN`，并在海豹插件的 **Bridge访问令牌** 里填同一个值。
- `/health` 永远不校验令牌，方便容器健康检查。

## 备份策略

迁移前会自动备份，角色卡库与 log 库**各自独立**：

- 首次迁移留一份永久快照：`data.db.snapshot-first.bak`、`data-logs.db.snapshot-first.bak`，不会被覆盖或删除。
- 之后每次迁移再留最近 2 份滚动备份 `*.before-sync-<时间>.bak`，多余的自动清理。

## log 迁移的健壮性

- 逐条 log 独立提交：某一条出错只跳过它，其余照常迁移。
- 目标群已有同名 log 时自动改名 `原名 (2)`、`原名 (3)`。
- 重复执行会被识别为「已迁移」并跳过，不会重复复制。
- 失败的条目会写进同步桥目录的 `bridge_error.log`。

## 测试

不需要 docker，也不需要真实数据：

```sh
python tests/test_bridge.py          # 36 项：备份、放行规则、撞名、幂等、父子引用、HTTP 层
python tests/test_docker_layout.py   # 20 项：两端源码一致、Dockerfile/compose、容器参数实跑
```

## 说明

同步桥只读写本机的 sqlite 文件，不上传任何数据。迁移用的验证码通过你自己配置的 SMTP 邮箱发送。