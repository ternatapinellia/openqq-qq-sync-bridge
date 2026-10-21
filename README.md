# OpenQQ QQ Sync Bridge

**OpenQQ 与旧 QQ 数据迁移同步桥** —— 把旧 QQ 的角色卡、群属性、log 迁移到你的 OpenQQ 账号。

有两种用法，按你的情况选一个：

| 你的情况 | 用哪个 | 文档 |
| --- | --- | --- |
| 海豹跑在**自己的 Windows 电脑**上 | **Windows 版**（双击即用） | [windows/README-WINDOWS.md](windows/README-WINDOWS.md) |
| 海豹跑在**Linux 服务器** / 容器里 / 想长期挂着 | **Docker 版** | [docker/README-DOCKER.md](docker/README-DOCKER.md) |

两版功能完全一样，共用同一份源码，选一个就行。

---

## 三分钟快速上手

### Windows

1. 把 `windows/` 里的 **exe + cmd + bridge_port.txt** 放到海豹主程序目录（和 `data/` 平行）
2. 把 **`OpenQQ-QQ-Sync-v2.0.js`** 放进海豹的 js 插件目录并重载
3. 双击 `启动OpenQQ同步桥-v2.0.cmd`，**窗口保持开着**
4. 插件配置里填发件邮箱 + SMTP 授权码，先执行 `.旧QQ邮箱测试`
5. 在目标群执行：
   - `.旧QQ绑定 <旧QQ号> <旧群号>`
   - 去旧 QQ 邮箱收验证码
   - `.旧QQ验证码 <6位验证码>`
6. 完成，`.st` / `.pc` / `.log` 就能看到迁移过来的数据

详细步骤和排错：[windows/README-WINDOWS.md](windows/README-WINDOWS.md)

### Linux / Docker

```sh
cd docker
cp .env.example .env          # 填 SEALDICE_DATA_DIR 和 OPENQQ_BRIDGE_TOKEN
./build-and-run.sh
curl http://127.0.0.1:38999/health
```

然后把插件里的 **Bridge主机 / 端口 / 令牌** 填好，后续迁移步骤和 Windows 一样。

详细步骤和排错：[docker/README-DOCKER.md](docker/README-DOCKER.md)

---

## 它由哪两部分组成

| 部分 | 是什么 | 在哪 |
| --- | --- | --- |
| **同步桥** | 一个小 HTTP 服务，直接读写海豹的 sqlite 文件 | `windows/*.exe` 或 `docker/` 容器 |
| **海豹插件** | 提供 `.旧QQ绑定` / `.旧QQ验证码` 等指令 | `OpenQQ-QQ-Sync-v2.0.js` |

工作流程：插件收到指令 → 调用本地/远程的同步桥 → 同步桥读写 `data.db` 与 `data-logs.db`。

**迁移是一次性的**：验证码通过那一刻复制一次，之后两边各自独立，不会持续同步。

---

## 全部指令

| 指令 | 作用 |
| --- | --- |
| `.旧QQ绑定 <旧QQ> <旧群>` | 申请验证码（往旧 QQ 邮箱发信） |
| `.旧QQ验证码 <6位数字>` | 提交验证码，通过后开始迁移 |
| `.旧QQ邮箱测试` | 往发件邮箱发测试邮件 |
| `.旧QQ桥状态` | 检查同步桥是否正常 |
| `.旧QQ角色 [旧QQ]` | 查看该旧 QQ 的角色卡 |
| `.旧QQ绑定信息` | 查看当前群的绑定 |
| `.旧QQ解绑` | 解除绑定 |

---

## 目录结构

```
src/                          唯一源码，两版共用
  bridge.py                   同步桥本体（纯 Python 标准库，无第三方依赖）
  OpenQQ-QQ-Sync-v2.0.js      海豹插件

windows/                      Windows 版（单独一个文件夹，直接拿走用）
  OpenQQ-QQ-Sync-Bridge-v2.0.exe
  启动OpenQQ同步桥-v2.0.cmd
  OpenQQ-QQ-Sync-v2.0.js
  bridge_port.txt
  email_config.example.json
  README-WINDOWS.md           <- Windows 使用说明
  README-v2.0.txt             旧版说明（历史遗留）

docker/                       Docker 版（把这个文件夹拷到服务器）
  Dockerfile
  docker-compose.yml
  entrypoint.sh
  build-and-run.sh
  .env.example
  bridge.py                   构建上下文里的副本（内容与 src 一致）
  OpenQQ-QQ-Sync-v2.0.js
  config/
  README-DOCKER.md            <- Docker 使用说明

tests/                        回归测试（不需要 Docker，也不需要真实数据）
  test_bridge.py              36 项
  test_docker_layout.py       24 项
  seadice_fixture.py
```

---

## 主要特性

**备份**：迁移前自动备份，角色卡库与日志库各备各的。

- 首次迁移留一份**永久快照** `*.snapshot-first.bak`，永不覆盖
- 之后保留最近 2 份滚动备份

**log 迁移足够健壮**：

- 逐条独立提交，一条坏不影响其他条（不会整批失败）
- 重名自动改名 `原名 (2)`，不丢内容
- 重复执行自动识别并跳过，不会复制两份
- 失败原因写进 `bridge_error.log`

**无角色卡也能迁移**：只要角色卡或 log 有一边有数据就放行。

**访问控制**：Windows 默认只听 `127.0.0.1`；Docker 必须配令牌。

---

## 跑测试

不需要 Docker，也不需要真实海豹数据：

```sh
python tests/test_bridge.py          # 36 项
python tests/test_docker_layout.py   # 24 项
```

---

## 说明

- 同步桥只读写本机的 sqlite 文件，**不上传任何数据**。
- 验证码通过你自己配置的 SMTP 邮箱发出，不经过第三方服务器。
- 迁移结果以实际返回为准；失败条目详见 `bridge_error.log`。