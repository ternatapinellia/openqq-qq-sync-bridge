# OpenQQ QQ Sync Bridge v3.0

**旧 QQ → OpenQQ 数据迁移工具**

把旧 QQ 的角色卡、PC 数据、log 搬到你的 OpenQQ 账号。

---

## 选一个版本

| 你的海豹在哪 | 用哪个 | 说明 |
| --- | --- | --- |
| **Windows 电脑上** | Windows 版 | [windows/README-WINDOWS.txt](windows/README-WINDOWS.txt) |
| **Linux 服务器上** | Linux 版 | [docker/README-DOCKER.txt](docker/README-DOCKER.txt) |

两版功能一样，选一个就行。

---

## 三步上手

**1. 装插件**

把 `OpenQQ-QQ-Sync-v3.0.js` 放进海豹的 js 插件目录，重载插件。

**2. 启动同步桥**

- Windows：把 `OpenQQ-QQ-Sync-Bridge-v3.0.exe`、`启动OpenQQ同步桥-v3.0.cmd`、`bridge_port.txt` 放到海豹主程序目录（和 `data` 文件夹平级），双击 cmd，**窗口保持开着**。
- Linux：按 [docker/README-DOCKER.txt](docker/README-DOCKER.txt) 里的 4 步操作。

**3. 在群里迁移**

```
.旧QQ绑定 <旧QQ号> <旧群号>      → 去旧QQ邮箱收验证码
.旧QQ验证码 <6位验证码>          → 完成
```

---

## 插件配置填什么

| 配置项 | 填什么 |
| --- | --- |
| 发件邮箱 | 你的 QQ 邮箱，如 `123456@qq.com` |
| SMTP授权码 | QQ 邮箱的 **SMTP授权码**（不是登录密码） |
| SMTP服务器 | `smtp.qq.com` |
| SMTP端口 | `465` |
| Bridge端口 | `38999` |
| Bridge主机 | Windows 填 `127.0.0.1`；Linux 同机也填 `127.0.0.1` |
| Bridge访问令牌 | Windows 留空；Linux 填 `.env` 里设的那串 |

先跑一次 `.旧QQ邮箱测试` 确认能收到邮件。

---

## 全部指令

| 指令 | 作用 |
| --- | --- |
| `.旧QQ绑定 <旧QQ> <旧群>` | 申请验证码 |
| `.旧QQ验证码 <6位数字>` | 提交验证码并开始迁移 |
| `.旧QQ邮箱测试` | 发测试邮件 |
| `.旧QQ桥状态` | 检查同步桥是否正常 |
| `.旧QQ角色 [旧QQ]` | 查看该旧 QQ 的角色卡 |
| `.旧QQ绑定信息` | 查看当前群的绑定 |
| `.旧QQ解绑` | 解除绑定 |

---

## 要注意的

- **迁移只做一次**，之后旧群的新消息不会跟过来。
- **同一个旧QQ+旧群只能绑一次**，要重绑先 `.旧QQ解绑`。
- 验证码 **5 分钟**有效，最多输错 5 次。
- 迁移前会自动备份，备份就在海豹的 `data/default` 里。

---

## 从 v2.0 升级

**这是原地升级**：配置和绑定记录都会保留，不用重新绑定。

1. 关掉旧的同步桥窗口
2. 用 v3.0 的文件替换旧的（**旧的 `OpenQQ-QQ-Sync-v2.0.js` 一定要删掉**）
3. 重启同步桥，重载插件

> v3.0 的插件沿用 v2.0 的插件标识，所以能被海豹识别为同一个插件。
> 但如果两个 js 文件同时存在，海豹只会加载先读到的那个，可能导致
> 「看起来升级了、实际还是旧代码」。所以务必删掉旧 js。

详细步骤见 [windows/升级说明-v2到v3.txt](windows/升级说明-v2到v3.txt)。

---

## v3.0 改了什么

**修了一个会导致角色卡显示为空的问题。**

之前版本在迁移时会检查"群属性绑定的角色卡是不是自己的"，
不是就清空绑定。但海豹允许同一个群共用角色卡，
清空后面板就没东西显示，看起来就是"角色卡全空了"。

v3.0 改成：**保留原来的绑定**；如果这张卡本次一起被复制了，
就指向新复制的那张。数据本身一直没丢，只是显示的问题。

其它改进：
- 源群属性只认属于该旧QQ自己的记录，不会误用别人的
- 目标群已有真实数据时不再覆盖
- 数据库索引损坏时自动绕过，不会整个迁移失败

---

## 目录

```
src/                          源码（两版共用）
  bridge.py                   同步桥
  OpenQQ-QQ-Sync-v3.0.js      海豹插件

windows/                      Windows 版
  OpenQQ-QQ-Sync-Bridge-v3.0.exe
  启动OpenQQ同步桥-v3.0.cmd
  OpenQQ-QQ-Sync-v3.0.js
  bridge_port.txt
  email_config.example.json
  README-WINDOWS.txt
  README-v3.0.txt
  升级说明-v2到v3.txt

docker/                       Linux 版
  Dockerfile
  docker-compose.yml
  .env.example
  entrypoint.sh
  bridge.py
  OpenQQ-QQ-Sync-v3.0.js
  README-DOCKER.txt

tests/                        自动测试
  test_bridge.py
  test_docker_layout.py
```

---

## 安全

- 同步桥只读写本机的海豹数据库文件，**不上传任何数据**。
- 验证码通过你自己配置的邮箱发出，不经过第三方。
- Windows 版只监听 `127.0.0.1`，别的机器访问不到。
- Linux 版必须设访问令牌。