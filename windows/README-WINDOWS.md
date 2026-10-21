# Windows 部署说明

双击即用，不需要装 Python、不需要装 Docker。

## 一、放到哪里

把 `windows/` 里的这些文件，放到**海豹主程序同级目录**（也就是和 `data/` 文件夹平行）：

```
Sealdice/
  Sealdice.exe
  data/
    default/
      data.db
      data-logs.db
  OpenQQ-QQ-Sync-Bridge-v2.0.exe      <- 从 windows/ 拷来
  启动OpenQQ同步桥-v2.0.cmd            <- 从 windows/ 拷来
  bridge_port.txt                     <- 从 windows/ 拷来
```

插件 `OpenQQ-QQ-Sync-v2.0.js` 放到海豹的 js 插件目录，然后在海豹里重载插件。

## 二、启动

双击 `启动OpenQQ同步桥-v2.0.cmd`。看到这样的输出就算成功：

```
OpenQQ QQ Sync Bridge v2.0
Listening: 127.0.0.1:38999
Data dir: ...\Sealdice\data\default
Config dir: ...\Sealdice
```

**保持这个窗口开着，不要关。** 关掉桥就停了，插件会报「无法连接同步桥」。

## 三、在海豹里配置

插件配置里填：

| 配置项 | 填什么 |
| --- | --- |
| 发件邮箱 | 你的 QQ 邮箱，例如 `123456@qq.com` |
| SMTP授权码 | QQ 邮箱的 SMTP **授权码**，不是登录密码 |
| SMTP服务器 | `smtp.qq.com` |
| SMTP端口 | `465` |
| Bridge端口 | `38999`（和 `bridge_port.txt` 一致） |
| Bridge主机 | `127.0.0.1`（本机默认值，不用改） |
| Bridge访问令牌 | 本机使用**留空**即可 |

先执行 `.旧QQ邮箱测试` 确认能收到测试邮件。

## 四、执行迁移

在**目标群**里：

1. `.旧QQ绑定 <旧QQ号> <旧群号>`，例如 `.旧QQ绑定 2522629086 1081354778`
2. 去 `旧QQ号@qq.com` 收验证码（5 分钟内有效）
3. `.旧QQ验证码 <6位验证码>`

验证通过后角色卡、群属性、log 会被复制过来。绑定过的旧 QQ+旧群不能重复绑定到别的账号（防误绑）。

## 五、只监听本机

Windows 版默认只监听 `127.0.0.1`，别的机器访问不到。除非你明确知道风险，否则不要改成对外监听。

## 六、迁移前会自动备份

在 `data/default/` 里生成，两个库各自独立：

- 永久快照：`data.db.snapshot-first.bak`、`data-logs.db.snapshot-first.bak`（首次迁移时生成一次，之后不再改动）
- 滚动备份：`data.db.before-sync-<时间>.bak`、`data-logs.db.before-sync-<时间>.bak`（只留最近 2 份）

出问题可以用这些备份还原（还原前先删掉同名的 `-wal`、`-shm` 文件）。

## 七、常见问题

**双击 cmd 一闪而过 / 报找不到文件**

`OpenQQ-QQ-Sync-Bridge-v2.0.exe`、`bridge_port.txt` 必须和 cmd 在同一个文件夹里。

**插件报「无法连接同步桥 38999」**

cmd 窗口是不是被关了？`bridge_port.txt` 里的端口和插件里的 Bridge端口 是否一致？端口是否被别的程序占用？

**迁移结果显示有 Log 迁移失败**

看同步桥目录下的 `bridge_error.log`，里面有具体是哪几条、什么原因；其余 log 已经正常迁移。

**收不到验证码邮件**

先跑 `.旧QQ邮箱测试`。收不到通常是：SMTP 授权码填成了登录密码、QQ 邮箱没开 SMTP 服务、或邮件进了垃圾箱。

## 八、日志

- `bridge_error.log`：迁移失败详情（只在有失败时生成）
- 控制台窗口：每个 HTTP 请求会打印一行，方便排查