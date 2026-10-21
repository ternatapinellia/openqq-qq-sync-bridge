# Docker / Linux 部署说明

在 Linux 服务器（或任何装了 Docker 的机器）上运行同步桥。适合海豹跑在服务器/容器里、或者想长期挂着的场景。

## 一、准备

1. 服务器已安装 Docker 与 Docker Compose（`docker compose version` 能跑）。
2. 找到海豹的数据目录，也就是含有 `data.db` 和 `data-logs.db` 的那个 `data/default`：

   ```
   Sealdice/
     data/
       default/
         data.db
         data-logs.db
   ```

   把 `docker/` 整个文件夹拷到服务器上任意位置。

## 二、配置

```sh
cd docker
cp .env.example .env
```

编辑 `.env`：

| 变量 | 说明 |
| --- | --- |
| `SEALDICE_DATA_DIR` | 海豹 `data/default` 目录的**绝对路径**。必须可写，因为迁移前要在同目录写备份。 |
| `OPENQQ_BRIDGE_TOKEN` | 访问令牌，必填。生成方法：`openssl rand -hex 16` |

也可以直接编辑 `config/bridge_port.txt` 改端口（默认 38999）。

## 三、启动

```sh
./build-and-run.sh
# 等价于：docker compose up -d --build
```

查看日志与状态：

```sh
docker compose logs -f openqq-bridge
curl http://127.0.0.1:38999/health
```

健康时返回：

```json
{"ok": true, "version": "2.0", "port": 38999, "data_dir": "/data"}
```

## 四、接入海豹

用桥所在机器的地址访问。分两种常见情况：

**A. 海豹和桥在同一台机器上**

`docker-compose.yml` 默认把端口映射到 `127.0.0.1:38999`，海豹插件里：

- Bridge主机：`127.0.0.1`
- Bridge端口：`38999`
- Bridge访问令牌：`.env` 里那个值

**B. 海豹在另一台机器 / 另一个容器里**

1. 把 `docker-compose.yml` 里的端口映射改成 `"38999:38999"`（对外暴露）。
2. 插件里的 Bridge主机 填桥所在机器的 IP 或域名。
3. **一定要设置令牌**，否则等于把迁移接口对网络开放。

> 更稳妥的做法是把容器加进海豹所在的 docker network，用容器名互访，不往公网暴露端口。

## 五、备份在哪里

迁移前会在 `SEALDICE_DATA_DIR` 里生成：

- `data.db.snapshot-first.bak` / `data-logs.db.snapshot-first.bak`：首次迁移的永久快照。
- `data.db.before-sync-<时间>.bak` / `data-logs.db.before-sync-<时间>.bak`：最近 2 份滚动备份。

出错详情写在 `config/bridge_error.log`（已挂载到宿主机 `docker/config/`）。

## 六、常见问题

**容器起不来，日志说找不到 data.db**

`SEALDICE_DATA_DIR` 指错了，或者路径没写绝对路径。用 `docker compose logs openqq-bridge` 看具体路径。

**插件报「无法连接同步桥」**

按顺序查：容器是否在跑（`docker compose ps`）→ 宿主 `curl http://127.0.0.1:38999/health` 是否正常 → 插件的 主机/端口/令牌 是否和 `.env` 一致。

**插件报 401 unauthorized**

令牌不一致。`.env` 里的 `OPENQQ_BRIDGE_TOKEN` 必须和插件里填的完全一样。

**迁移后 log 有失败条目**

看 `docker/config/bridge_error.log`，里面有具体 log 名和报错原因（其余 log 已正常迁移）。

**端口 38999 被占用**

改 `config/bridge_port.txt` 和 `docker-compose.yml` 的端口映射，两边保持一致。

## 七、升级 / 卸载

```sh
git pull                       # 或替换 docker/ 文件夹
docker compose up -d --build   # 重新构建
docker compose down            # 停止并移除容器
```

数据不会被删：海豹数据在你的 `SEALDICE_DATA_DIR`，桥的配置在 `docker/config/`。