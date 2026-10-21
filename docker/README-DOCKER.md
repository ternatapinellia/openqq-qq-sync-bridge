# OpenQQ QQ Sync Bridge —— Linux / Docker 版使用说明

在 Linux 服务器上用 Docker 跑同步桥。适合海豹跑在服务器上、或者你希望同步桥长期挂着的情况。

Windows 用户请直接看 [../windows/README-WINDOWS.md](../windows/README-WINDOWS.md)，不需要看这个。

---

## 一、先理解这套东西怎么连起来的

```
海豹（SeaDice）
   │  插件发 HTTP 请求
   ▼
http://<桥的地址>:38999
   │
   ▼
同步桥容器 ──读取/写入──> 海豹的 data.db / data-logs.db
```

关键点：**同步桥必须能直接访问海豹那两个 sqlite 文件**，所以要把海豹的数据目录挂载进容器。迁移前还要在同一目录写备份，所以这个目录必须是**可写**的。

---

## 二、准备

需要两样东西：

**1. 一台装了 Docker 的 Linux 机器**

确认这两条命令能用：

```sh
docker --version
docker compose version
```

**2. 找到海豹的数据目录**

就是同时含有 `data.db` 和 `data-logs.db` 的那个 `data/default`：

```
Sealdice/
└─ data/
   └─ default/
      ├─ data.db
      └─ data-logs.db
```

把它的**绝对路径**记下来，例如 `/opt/Sealdice/data/default`。

然后把本仓库的 `docker/` 整个文件夹拷到服务器上，随便放哪都行：

```sh
scp -r docker/ user@server:/opt/openqq-bridge/
```

---

## 三、配置

```sh
cd /opt/openqq-bridge
cp .env.example .env
```

编辑 `.env`，只需要改两个值：

```ini
# 海豹 data/default 的绝对路径（必须可写）
SEALDICE_DATA_DIR=/opt/Sealdice/data/default

# 访问令牌，必填。生成一个：
OPENQQ_BRIDGE_TOKEN=换成你生成的随机串
```

生成随机令牌：

```sh
openssl rand -hex 16
```

**这个令牌一定要记住**，后面要在海豹插件里填同一个值。

> 为什么一定要令牌？因为容器里同步桥监听 `0.0.0.0`（否则宿主机访问不到）。没有令牌就等于这个迁移接口对能访问到它的人开放。

---

## 四、启动

```sh
./build-and-run.sh
```

等它构建完（第一次大概 1～2 分钟），然后检查是否健康：

```sh
curl http://127.0.0.1:38999/health
```

正常会返回：

```json
{"ok": true, "version": "2.0", "port": 38999, "data_dir": "/data"}
```

看日志：

```sh
docker compose logs -f openqq-bridge
```

启动正常时日志里会有：

```
[init] data dir   : /data
[init] config dir : /config
[init] port       : 38999
OpenQQ QQ Sync Bridge v2.0
Listening: 0.0.0.0:38999
```

---

## 五、让海豹连上同步桥

分两种情况，**选你符合的那一种**。

### 情况 A：海豹和同步桥在**同一台机器**上

默认配置就是这样，不用改任何东西。海豹插件里填：

| 配置项 | 填什么 |
| --- | --- |
| Bridge主机 | `127.0.0.1` |
| Bridge端口 | `38999` |
| Bridge访问令牌 | `.env` 里那个值 |

### 情况 B：海豹在**另一台机器**（或另一个容器里）

**第一步**，打开 `docker-compose.yml`，把端口映射改掉：

```yaml
    ports:
      # 原来： - "127.0.0.1:38999:38999"
      - "38999:38999"
```

**第二步**，`docker compose up -d` 重启。

**第三步**，海豹插件里：

| 配置项 | 填什么 |
| --- | --- |
| Bridge主机 | 同步桥服务器的 IP 或域名 |
| Bridge端口 | `38999` |
| Bridge访问令牌 | `.env` 里那个值 |

**第四步**，服务器防火墙放行 38999 端口。

> ⚠️ 这种情况下 38999 是暴露在网络上的。**令牌绝对不能留空**，也建议只对海豹所在机器的 IP 开放，别对公网敞开。

> 更安全的做法：如果海豹也是 Docker 跑的，把两个容器放进同一个 docker network，用容器名 `openqq-bridge` 互访，就不用暴露端口了。

---

## 六、执行迁移

配置好之后，操作和 Windows 版完全一样，在**目标群**里：

**第 1 步**

```
.旧QQ绑定 <旧QQ号> <旧群号>
```

例如 `.旧QQ绑定 2522629086 1081354778`

**第 2 步**

去 `旧QQ号@qq.com` 收 6 位验证码（5 分钟内有效）。

**第 3 步**

```
.旧QQ验证码 123456
```

成功后会返回角色卡数量、群属性数量、log 数量和记录条数。

---

## 七、全部指令

| 指令 | 作用 |
| --- | --- |
| `.旧QQ绑定 <旧QQ> <旧群>` | 申请验证码 |
| `.旧QQ验证码 <6位数字>` | 提交验证码并开始迁移 |
| `.旧QQ邮箱测试` | 发测试邮件 |
| `.旧QQ桥状态` | 检查同步桥状态 |
| `.旧QQ角色 [旧QQ]` | 查看该旧 QQ 的角色卡 |
| `.旧QQ绑定信息` | 查看当前绑定 |
| `.旧QQ解绑` | 解除绑定 |

---

## 八、备份在哪里

迁移前自动备份，写进你挂载的 `SEALDICE_DATA_DIR`（也就是海豹的 `data/default/`）：

| 文件 | 说明 |
| --- | --- |
| `data.db.snapshot-first.bak` | 角色卡库首次快照，**永久保留** |
| `data-logs.db.snapshot-first.bak` | 日志库首次快照，永久保留 |
| `*.before-sync-<时间>.bak` | 最近 2 份滚动备份 |

两个库**各自独立**计数、各自独立清理，互不影响。

**出错的详情**写在 `docker/config/bridge_error.log`（这个目录已挂载到宿主机，容器删了也不会丢）。

---

## 九、改端口

如果你想用别的端口（比如 38999 被占用）：

1. 改 `config/bridge_port.txt`，例如写成 `39000`
2. 改 `docker-compose.yml` 里的端口映射，两边数字保持一致：

   ```yaml
   ports:
     - "127.0.0.1:39000:39000"
   ```

3. 改 `.env` 里的 `OPENQQ_BRIDGE_PORT=39000`
4. `docker compose up -d`
5. 海豹插件里的「Bridge端口」也改成 `39000`

> `config/bridge_port.txt` 的优先级高于环境变量，所以改完 txt 就能生效，不用改 `Dockerfile`。

---

## 十、常见问题

**容器起不来，日志里说找不到 data.db**

`.env` 里的 `SEALDICE_DATA_DIR` 写错了，或者没写绝对路径。用下面的命令确认这个路径下确实有文件：

```sh
ls -l /opt/Sealdice/data/default/data.db
ls -l /opt/Sealdice/data/default/data-logs.db
```

**容器报权限错误 / 写入失败**

海豹的数据目录要可写（迁移前要写备份）。容器以 uid `10001` 运行，如果海豹数据目录归 root 所有，需要放开权限：

```sh
sudo chown -R 10001:10001 /opt/Sealdice/data/default
```

**插件报「无法连接同步桥」**

按顺序排查：

```sh
docker compose ps                              # 容器在跑吗
curl http://127.0.0.1:38999/health             # 宿主机能访问吗
docker compose logs --tail 50 openqq-bridge    # 日志里有报错吗
```

再检查插件的「Bridge主机 / 端口 / 令牌」是否和 `.env` 一致。

**插件报 401 unauthorized**

令牌不一致。`.env` 里的 `OPENQQ_BRIDGE_TOKEN` 必须和插件「Bridge访问令牌」**完全一样**（注意别多了空格）。

**迁移结果显示有 log 失败**

其余 log 已正常迁移。看 `docker/config/bridge_error.log`，里面有具体是哪几条、什么原因。

**容器重启后绑定记录还在吗**

在。绑定记录存在 `docker/config/bridge_bindings.json`，这个目录是挂载到宿主机的，容器删了重建也不丢。

**能同时迁移多个 QQ 吗**

可以。绑定关系按「旧QQ + 旧群」记录，互不冲突。

---

## 十一、升级 / 停止 / 卸载

```sh
docker compose logs -f openqq-bridge   # 看日志
docker compose restart                 # 重启
docker compose down                    # 停止并删除容器
docker compose up -d --build           # 重新构建并启动（升级用）
```

数据都保存在挂载目录里，`down` 不会删除任何数据。

彻底清理：

```sh
docker compose down
docker image rm openqq-qq-sync-bridge:2.0   # 删镜像
```

---

## 十二、完全手动跑（不用 compose）

如果你不想用 compose，等价的手动命令：

```sh
cd /opt/openqq-bridge
docker build -t openqq-qq-sync-bridge:2.0 .

docker run -d \
  --name openqq-bridge \
  --restart unless-stopped \
  -p 127.0.0.1:38999:38999 \
  -e OPENQQ_BRIDGE_TOKEN=你的令牌 \
  -v /opt/Sealdice/data/default:/data \
  -v /opt/openqq-bridge/config:/config \
  openqq-qq-sync-bridge:2.0
```

---

## 十三、安全说明

- 同步桥只读写挂载进来的 sqlite 文件，**不上传任何数据**。
- 验证码通过**你自己配置的 SMTP 邮箱**发出，不经过第三方。
- 容器以非 root 用户（uid 10001）运行。
- 默认只把端口映射到宿主机 `127.0.0.1`，外网访问不到。
- 如果必须对外暴露，务必设置强令牌，并尽量用防火墙限制来源 IP。