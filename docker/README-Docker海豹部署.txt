==============================================================
  3.5 同步桥 —— Linux + Docker 海豹 部署说明
==============================================================

适用情况：
   你的海豹骰子是【装在 Docker 里跑的】（Linux 服务器）。
   比如用「DiceZone 一键脚本」或「MCSManager 面板」部署的那种。

不适用：
   海豹直接装在 Windows 桌面 → 看 windows\README-v3.3.txt


==============================================================
先弄懂一件事：为什么这次跟以前不一样
==============================================================

以前（海豹装在 Windows 上）：
    海豹 ──→ 127.0.0.1:38999（同一个系统，直接连）

现在（海豹在 Docker 里）：
    海豹容器 ──→ 桥容器
    两个容器互相看不见对方，需要「放进同一个网络」才能连。

所以这篇说明的重点就是：让两个容器能互相找到。
其它步骤（填邮箱、绑定、迁移）跟以前完全一样。


==============================================================
准备工作：先找到海豹的数据目录
==============================================================

这一步最关键，找不到就没法继续。

如果你的海豹是用一键脚本装的，数据一般在这些位置之一：

    /opt/sealdice*/data/
    /root/sealdice*/data/
    /www/wwwroot/sealdice*/data/
    /home/*/sealdice*/data/

里面应该有一个叫 default 的文件夹，装着：

    data.db
    data-logs.db

在服务器上执行这条命令，能直接帮你找出来：

    find / -name "data-logs.db" -not -path "*/proc/*" 2>/dev/null

找到后，把它的【上一级目录】记下来，例如结果是：

    /opt/sealdice1/data/default/data-logs.db

那么你要记的目录就是：

    /opt/sealdice1/data/default


【要点】这个目录必须【可写】。
   因为迁移前桥要在这个目录里写备份文件。
   如果后面报权限错误，就执行：
       sudo chmod -R 777 你的数据目录


==============================================================
第 1 步：确认海豹用的是什么网络
==============================================================

在服务器执行：

    docker ps

看输出里海豹容器的 NAMES 那一列，比如：

    sealdice-1
    sealdice-2

再看它所在的网络：

    docker inspect sealdice-1 --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'

会输出一个网络名，例如：

    sealdice_default

【记住这个名字】，第 4 步要用。

  说明：如果你的海豹不是用 compose 起的，网络名可能是
       bridge（默认网络）。这种情况下也可以，只是后面
       要用 IP 而不是容器名（README 末尾有讲）。


==============================================================
第 2 步：把桥的文件传到服务器
==============================================================

【先说结论】
  先把你下载到的「民转官数据3.5（windows+linux）.zip」解压。
  你要传的，是解压后里面的 docker 这个文件夹，一共就这几个东西。
  里面 .py / .yml / .sh 结尾的看起来像代码，但你【一个字都不用改】，
  照抄下面的命令就行。

  解压后长这样：

      民转官数据3.5/
        docker/                      ← 只要这个文件夹
          Dockerfile
          docker-compose.yml
          entrypoint.sh
          bridge.py
          .env.example
          config/
            bridge_port.txt
          OpenQQ-QQ-Sync-v3.5.js
          README-DOCKER.txt
        windows/                     ← Windows 电脑用的，服务器不用管

  传到哪里？
      本文统一用 /opt/bridge33 这个位置。
      你想放别的地方也行（比如 /root/bridge33），
      那样后面所有命令里的 /opt/bridge33 都要跟着改。


--------------------------------------------------------------
2.1 方法一：宝塔面板上传（最推荐，不用记命令）
--------------------------------------------------------------

  前提：服务器装了宝塔面板，你能用浏览器打开它。

  1) 浏览器打开宝塔面板 → 左边菜单点【文件】

  2) 点最上面的地址栏，输入 /opt 然后回车
     （进到 /opt 目录了）

  3) 点上传按钮 → 选你电脑上的 docker 文件夹
     如果宝塔不让选文件夹，只能选文件，那就走 2.4 的 zip 办法。

  4) 传完后 /opt 下面会出现 docker 这个文件夹

  5) 右键 docker → 重命名 → 改成 bridge33
     改名字只是让后面的命令短一点，不改也行。

  【如果 /opt 下面已经有一个 bridge33】
    先把旧的删掉再重命名，不然会提示重名：
        rm -rf /opt/bridge33
    （删之前确认那里面没有你还要的东西，删掉了不好找回）

  【容易懵的地方】
    * 宝塔默认【不显示】以点开头的文件，所以你看不到
      .env.example，这是正常的，它其实在里面。
      点右上角的【设置】→ 勾上【显示隐藏文件】就能看见。
    * 用的是 MCSManager 面板也一样，它每个实例有【文件管理】，
      只是上传入口在实例页面里，传完记得路径要对。

  传完跳到 2.5 做检查。


--------------------------------------------------------------
2.2 方法二：scp 命令传（Windows 也能用）
--------------------------------------------------------------

  在你【自己的电脑】上打开命令行：
      Windows：按 Win + R，输入 cmd，回车
      Mac / Linux：打开终端

  Windows 10 / 11 自带的 scp 就能用，不用另外装东西。
  （如果提示“scp 不是内部或外部命令”，去【设置 → 应用 →
  可选功能 → 添加功能】里装上 OpenSSH 客户端。）

  ［第一步］先传到服务器的 /opt（不要直接传到 /opt/bridge33）：

      scp -r "D:\下载\民转官数据3.5\docker" root@你的服务器IP:/opt

  ［第二步］再登录服务器改名字：

      mv /opt/docker /opt/bridge33

  为什么要分两步？
    如果 /opt/bridge33 这个文件夹已经存在，直接 scp 到它里面，
    会变成 /opt/bridge33/docker，所有路径就都错了一层。
    先传到 /opt 再改名，不管原来有没有 bridge33，都不会套错。

  几个说明：
    * 第一次连接会问 yes/no，输入 yes 再回车
    * 接着会要密码，输的时候屏幕上【什么都不显示】，
      这是正常的，凭手感打完回车就行
    * 路径里有中文的话，两边都要加英文双引号
    * 服务器不给用 root 登录的话，换成你的用户名，
      并且传到自己的家目录：

          scp -r "D:\下载\民转官数据3.5\docker" 你的用户名@你的服务器IP:/home/你的用户名
          mv /home/你的用户名/docker /home/你的用户名/bridge33

    * SSH 端口不是 22 的话（注意是大写 P）：

          scp -P 2222 -r "D:\下载\民转官数据3.5\docker" root@你的服务器IP:/opt
          mv /opt/docker /opt/bridge33

    * Mac / Linux 本机的路径写法不一样，比如：

          scp -r ~/Downloads/民转官数据3.5/docker root@你的服务器IP:/opt
          mv /opt/docker /opt/bridge33

  如果提示 Permission denied，就是没权限往 /opt 写，
  改成传到 /home/你的用户名/ 下面就行。

  传完跳到 2.5 做检查。


--------------------------------------------------------------
2.3 方法三：WinSCP / FileZilla（图形界面，鼠标拖）
--------------------------------------------------------------

  1) 下载 WinSCP（免费、有中文界面）或 FileZilla
  2) 新建连接，填四样东西：

         主机名：服务器 IP
         端口：  22        （协议/文件协议选 SSH、SFTP）
         用户名：root
         密码：  服务器密码

  3) 连上后，窗口左边是你自己的电脑，右边是服务器
  4) 右边先双击进到 /opt
  5) 把左边的 docker 文件夹直接【拖】到右边
     拖进去之后，服务器上就是 /opt/docker，正好是我们要的结构。
  6) 右键服务器上的 docker → 重命名 → 改成 bridge33（可选）

  【如果 /opt 下面已经有一个 bridge33】
    先把旧的删掉，不然会重名：
        rm -rf /opt/bridge33

  传完跳到 2.5 做检查。


--------------------------------------------------------------
2.4 如果只能传一个 zip（宝塔 / MCSManager 常见）
--------------------------------------------------------------

  有些面板不让传文件夹，只让传单个文件，那就这样：

  1) 在自己电脑上，右键 docker 文件夹 → 压缩成 docker.zip
     （注意是【只压缩 docker 这一个文件夹】，不要把整个
       民转官数据3.5 都压进去，不然路径会多一层）

  2) 通过面板把 docker.zip 上传到 /opt

  3) 登录服务器（宝塔的【终端】，或者 SSH），先解压到临时目录：

         cd /opt
         unzip -o docker.zip -d unpacked

     如果提示 unzip: command not found，先装一下：

         apt install -y unzip      # Ubuntu / Debian
         yum install -y unzip      # CentOS

     不想装也行，用 python 解压：

         cd /opt
         python3 -c "import zipfile;zipfile.ZipFile('docker.zip').extractall('unpacked')"

  4) 看看解压出来是什么结构：

         ls -la /opt/unpacked

     会出现两种情况之一：

         情况 A：里面有一个 docker 文件夹
             执行：
                 mv /opt/unpacked/docker /opt/bridge33

         情况 B：Dockerfile 等文件直接散在 unpacked 里
             执行：
                 mv /opt/unpacked /opt/bridge33

     不确定是哪种，就照着 ls 的输出看：
     只要【最终 /opt/bridge33 里面能直接看到 Dockerfile】就对了，
     不要出现 /opt/bridge33/docker/Dockerfile 这种多一层的结构。

  5) 传完跳到 2.5 做检查。


--------------------------------------------------------------
2.5 传完之后，必须做的三件事
--------------------------------------------------------------

  (1) 确认文件都在（特别注意不要多套一层 docker 目录）

          ls -la /opt/bridge33

      【必须】直接看到 Dockerfile。如果看到的是一个 docker 文件夹，
      说明多套了一层，执行下面这条把它提上来：

          mv /opt/bridge33/docker/* /opt/bridge33/
          rmdir /opt/bridge33/docker

      然后再 ls 一次，应该能看到这几样：

          Dockerfile
          docker-compose.yml
          entrypoint.sh
          bridge.py
          config/            （里面有 bridge_port.txt）
          OpenQQ-QQ-Sync-v3.5.js

      看不到 .env.example 是正常的（隐藏文件），
      用 ls -la 就能看到。

  (2) 处理换行符（一般不用做，出问题再回来做）

      压缩包里的 entrypoint.sh、docker-compose.yml 本来就是
      Linux 换行，直接传上去没问题。
      只有在【你自己用 Windows 记事本之类的工具编辑过】它们之后，
      才会多出一个多余的 \r 字符，让启动时报一堆看不懂的错。

      真遇到 exec format error、not found、$'\r' 这类怪报错，
      执行下面两行即可（某个文件提示不存在就跳过，没关系）：

          cd /opt/bridge33
          sed -i 's/\r$//' entrypoint.sh .env.example docker-compose.yml
          chmod +x entrypoint.sh

  (3) 确认路径记住了，下一步要用

      第 3 步要往 .env 里填两个值：
          你的海豹数据目录（准备工作里找到的）
          你自己定的令牌
      把这两个先想好，免得来回翻。


--------------------------------------------------------------
2.6 传文件时的常见问题
--------------------------------------------------------------

  Q：提示 Permission denied
  A：没权限写那个目录。两个办法：
       一是直接传到自己家目录 /home/你的用户名/ 下面；
       二是先传到 /tmp，再登录服务器用 sudo 挪过去：
           scp -r "D:\下载\民转官数据3.5\docker" 你的用户名@你的服务器IP:/tmp
           # 然后在服务器上执行：
           sudo mv /tmp/docker /opt/bridge33
           sudo chown -R root:root /opt/bridge33

  Q：宝塔上传文件夹卡住、进度不动
  A：文件夹里小文件多的时候宝塔会卡。改用 2.4 传 zip 的办法。

  Q：传完了，在服务器上找不到 .env.example
  A：以点开头的是隐藏文件。用 ls -la 能看到；
     宝塔要在【设置】里打开【显示隐藏文件】。

  Q：不知道服务器 IP 是多少
  A：就是你平时连宝塔面板或 SSH 用的那个地址。
     腾讯云 / 阿里云在控制台的【实例】列表里能看到公网 IP。

  Q：没有 SSH 账号密码，只有宝塔面板
  A：那就用 2.1 的宝塔上传，完全够用。

  Q：传上去的文件是"只读"，或者后面报写入失败
  A：改成可读写即可：

         chmod -R 755 /opt/bridge33

  Q：ls 看到的文件是乱码、中文名变成 ??
  A：说明传输工具把文件名编码搞坏了。改用 scp（2.2）
     或 WinSCP（2.3）重传一次，这两个不会出这个问题。

==============================================================
第 3 步：改配置文件
==============================================================

进入目录：

    cd /opt/bridge33

把示例配置复制成正式配置：

    cp .env.example .env

用编辑器打开 .env（不会用 vim 就用宝塔面板的文件管理编辑）：

    nano .env

改这两行：

    SEALDICE_DATA_DIR=/opt/sealdice1/data/default
    OPENQQ_BRIDGE_TOKEN=自己定一串字母数字

举例：

    SEALDICE_DATA_DIR=/opt/sealdice1/data/default
    OPENQQ_BRIDGE_TOKEN=a7f3c9e12b4d8065

说明：
  * SEALDICE_DATA_DIR = 准备工作里找到的那个目录，写完整路径
  * OPENQQ_BRIDGE_TOKEN = 你自己定的密码，随便打，但要记住
    后面在海豹插件里要填一模一样的内容

保存退出（nano 是按 Ctrl+O 回车，再按 Ctrl+X）。


==============================================================
第 4 步：改 docker-compose.yml（关键，让两个容器能互访）
==============================================================

还是在这个目录，编辑：

    nano docker-compose.yml

找到文件末尾，在 services 下面【追加】一段网络配置。
改完后整个文件长这样（注意缩进，空格要对齐）：

----------------------------------------------------------------
services:
  openqq-bridge:
    build:
      context: .
      dockerfile: Dockerfile
    image: openqq-qq-sync-bridge:3.5
    container_name: openqq-bridge
    restart: unless-stopped
    environment:
      OPENQQ_BRIDGE_PORT: "38999"
      OPENQQ_BRIDGE_TOKEN: "${OPENQQ_BRIDGE_TOKEN:?请先在 .env 里设置 OPENQQ_BRIDGE_TOKEN}"
    volumes:
      - "${SEALDICE_DATA_DIR:-./sealdice-data}:/data"
      - "./config:/config"
    networks:
      - sealdice_net

networks:
  sealdice_net:
    external: true
    name: sealdice_default      # ← 改成第 1 步查到的那个网络名
----------------------------------------------------------------

两个重点：

  1. ports 那段【删掉】了。
     因为桥和海豹在同一个 Docker 网络里，直接内部通信就行，
     不需要把端口暴露到服务器外面（更安全）。

  2. name 一定要填【第 1 步查到的真实网络名】。
     填错会报 "network sealdice_default not found"。


==============================================================
第 5 步：构建并启动
==============================================================

    cd /opt/bridge33
    docker compose up -d --build

【如果提示 docker: 'compose' is not a docker command】
   说明你这台的 Docker 版本旧，命令要加个横杠，改成：

       docker-compose up -d --build

   两个命令作用完全一样，哪个能跑通就用哪个。
   注意：后面所有 docker compose 开头的命令都要跟着加横杠。

第一次会下载 Python 镜像，等 1-3 分钟。

看到这两行就成功了一半：

    ✔ Container openqq-bridge  Started
    ✔ Network ...


==============================================================
第 6 步：验证桥是否正常
==============================================================

查看状态：

    docker compose ps

应该看到 openqq-bridge 状态是 Up。

看日志：

    docker compose logs --tail 30 openqq-bridge

正常会看到：

    [init] data dir   : /data
    [init] config dir : /config
    [init] port       : 38999
    OpenQQ QQ Sync Bridge v3.5
    Listening: 0.0.0.0:38999
    Incremental sync worker: started

如果看到【ERROR 找不到 /data/data.db】，说明第 3 步的
SEALDICE_DATA_DIR 填错了，回去重新检查。

健康检查：

    docker exec openqq-bridge python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:38999/health').read().decode())"

应该返回：

    {"ok": true, "version": "3.4", ...}


==============================================================
第 7 步：把插件放进海豹
==============================================================

把 OpenQQ-QQ-Sync-v3.5.js 放进海豹的 scripts 目录。

如果是 docker 海豹，宿主机上的路径通常在：

    /opt/sealdice1/data/default/scripts/

复制过去：

    cp /opt/bridge33/OpenQQ-QQ-Sync-v3.5.js /opt/sealdice1/data/default/scripts/

然后重启海豹容器，或者在 WebUI 里重载插件：

    docker restart sealdice-1


==============================================================
第 8 步：在海豹插件里填配置（最重要的一步）
==============================================================

打开海豹 WebUI → 插件 → OpenQQ旧QQ完整数据迁移 → 配置

填这几项：

  发件邮箱        ： 你的 QQ 邮箱，如 123456@qq.com
  SMTP授权码      ： QQ 邮箱的 SMTP 授权码（不是 QQ 密码！）
  SMTP服务器      ： smtp.qq.com（默认，不用改）
  SMTP端口        ： 465（默认，不用改）

  Bridge端口      ： 38999
  Bridge主机      ： openqq-bridge          ← 【关键，填容器名】
  Bridge访问令牌  ： 第 3 步 .env 里那串（要一模一样）


--------------------------------------------------------------
8.1 SMTP 授权码怎么拿（这一步最常卡住）
--------------------------------------------------------------

  授权码属于【发件邮箱】，也就是你填在“发件邮箱”里的那个 QQ 邮箱。
  收验证码的是 旧QQ号@qq.com ，那个邮箱什么都不用设置。

  1) 电脑浏览器打开 https://mail.qq.com ，登录你要当发件箱的 QQ 邮箱
  2) 左上角 设置 → 账号（有的版本叫“账户”）
  3) 往下找到“POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务”
  4) 在“IMAP/SMTP服务”那一行点【开启】
     （开 POP3/SMTP 也行，两个开一个就够，推荐 IMAP/SMTP）
  5) 按提示用绑定手机发一条短信，发完点“我已发送”
  6) 通过后会显示一串 16 位授权码，形如  abcd efgh ijkl mnop
     【只显示这一次】，先复制下来
  7) 填回插件配置：
       发件邮箱   → 你刚才登录的那个邮箱，如 123456@qq.com
       SMTP授权码 → 那 16 位，【去掉空格】，变成 abcdefghijklmnop
       SMTP服务器 → smtp.qq.com（不用改）
       SMTP端口   → 465（不用改）
  8) 保存后在群里发 .旧QQ邮箱测试 ，能收到测试邮件就说明配好了

  【容易踩的坑】
    * 填成 QQ 登录密码 → 一定失败，必须用授权码
    * 授权码里的空格没去掉
    * 找不到授权码了：回到第 4 步点“生成授权码”可重新生成，旧的会失效
    * 改过 QQ 密码后授权码通常也会失效，需要重新生成
    * 同一个发件邮箱可以给多个海豹实例共用
    * 收不到邮件时，让对方检查 QQ 邮箱的 设置 → 反垃圾 ，
      必要时把发件邮箱加进白名单

为什么 Bridge主机要填 openqq-bridge？
    因为海豹容器里访问 127.0.0.1 是它自己，不是桥。
    在同一 Docker 网络里，用【容器名】就能互相访问。


==============================================================
第 9 步：测试能不能通
==============================================================

在 QQ 群里（或私聊）执行：

    .旧QQ桥状态

如果能回复类似「桥正常。端口：38999 版本：3.4」，
说明全通了，可以去迁移数据了。

如果回复「无法连接同步桥」，跳到下面「排查」一节。


==============================================================
怎么用（迁移流程，和以前一样）
==============================================================

在【目标群】里依次执行：

  1) .旧QQ绑定 <旧QQ号> <旧群号>
     例如：.旧QQ绑定 2522629086 1081354778

  2) 去旧 QQ 邮箱收 6 位验证码（5 分钟内有效）

  3) .旧QQ验证码 <6位验证码>

完成后会显示迁移了多少角色卡、群属性、log。

【可以绑多个 OpenQQ 账号，不需要先解绑】
    绑定身份是「旧QQ号 + 旧群号 + OpenQQ账号 + 目标群」，
    所以同一个旧 QQ 可以分别绑到多个不同的 OpenQQ 账号，
    每个组合各记一份，互不冲突。
    想再绑一个：直接在新账号的新群里重跑上面 3 步即可。
    只有【完全相同的组合】重复绑定才会被提示已绑定。
    .旧QQ解绑 是「清理/停用这条绑定」，不是重新绑定的前置步骤。


其它常用指令：

    .旧QQ邮箱测试      先测邮箱配置对不对
    .旧QQ同步状态      看自动同步是否开启、上次结果
    .旧QQ立刻同步      马上跑一次增量同步
    .旧QQ同步开关 开/关  开关本群自动同步
    .旧QQ角色 [旧QQ]    查看旧 QQ 有哪些角色卡
    .旧QQ绑定信息       查看当前群绑定
    .旧QQ解绑           解除绑定


==============================================================
排查：连不上怎么办
==============================================================

【情况 1】插件提示「无法连接同步桥」

按顺序查：

  a) 桥容器活着吗？
       docker ps | grep openqq-bridge

  b) 桥日志有报错吗？
       docker compose logs --tail 50 openqq-bridge

  c) 两个容器在同一个网络吗？
       docker network inspect sealdice_default | grep -A3 openqq-bridge
       应该能看到 openqq-bridge 在里面

  d) 从海豹容器里能不能访问桥？
       docker exec sealdice-1 python3 -c "import urllib.request;print(urllib.request.urlopen('http://openqq-bridge:38999/health').read())"

       如果要的是 python 而不是 python3，换成 python 再试一次。

【情况 0】日志/面板出现 failure; status=1

  这句话只代表「容器启动脚本非正常退出」，不是具体原因。
  桥的启动脚本会主动 exit 1 的地方只有下面这几处，
  先看日志里最后几行，对着下面找：

  A. 出现 [ERROR] 找不到 /data/data.db 或 /data/data-logs.db
     → 海豹数据目录填错了。见【情况 2】。

  B. 出现 chmod / mkdir / Permission denied / Read-only file system
     → 没有权限。见【情况 3】。

  C. 出现 network xxx not found（这是 docker compose 自己报的，
     不是容器内的日志）
     → 网络名写错了。见【情况 4】。

  D. 出现 exec format error、not found、$'\r'
     → 文件换行符被 Windows 记事本改坏了。执行：
           cd /opt/bridge33
           sed -i 's/\r$//' entrypoint.sh docker-compose.yml
           chmod +x entrypoint.sh

  E. 日志里只有 Invalid port
     → config/bridge_port.txt 里不是 1-65535 的数字。
       直接改成：
           echo 38999 > /opt/bridge33/config/bridge_port.txt

  F. 日志里是 Address already in use
     → 38999 端口被别的程序占了。改成 39000：

           echo 39000 > /opt/bridge33/config/bridge_port.txt
           docker compose restart

       同时把插件里的【Bridge端口】也改成 39000。

  先把日志原文发出来，就能确定是哪一种：
       docker compose logs --tail 60 openqq-bridge

  容器可能因为 restart: unless-stopped 一直重启，
  如果看不清，可以临时停掉再看：
       docker compose stop
       docker compose logs --tail 80 openqq-bridge

  也可以直接一条命令看退出码和状态：
       docker inspect openqq-bridge --format '{{.State.Status}} exit={{.State.ExitCode}}'

【情况 2】桥启动就退出，日志说「找不到 data.db」

  SEALDICE_DATA_DIR 填错了。
  在服务器执行确认路径对不对：
       ls /你的路径/data.db
       ls /你的路径/data-logs.db

【情况 3】报 permission denied / 写入失败 / Read-only file system

  桥容器用 uid 10001 运行。海豹的 data/default 目录如果归 root，
  它就写不了配置文件和迁移备份。

  先把这两个目录交给 10001（把路径换成你自己的）：
       sudo chown -R 10001:10001 /opt/bridge33/config
       sudo chown -R 10001:10001 /opt/sealdice1/data/default

  如果还不行（有些同步盘/挂载盘不认 chown），再放宽权限：
       sudo chmod -R 775 /opt/sealdice1/data/default

  注意：不要对整个 /opt 执行 chmod/chown，只改上面这两个目录。

【情况 4】docker compose 报 network not found

  docker-compose.yml 里 networks 的 name 写错了。
  重新用第 1 步的命令查一次网络名。

【情况 5】插件报 401 unauthorized

  令牌不一致。.env 里的 OPENQQ_BRIDGE_TOKEN 和插件里
  「Bridge访问令牌」必须完全一样。


==============================================================
补充：海豹用的是默认 bridge 网络怎么办
==============================================================

如果第 1 步查出来的网络名是 bridge（而不是 sealdice_default），
那就不能用容器名互访了，要改成用 IP：

  1) 查到桥的 IP：
       docker inspect openqq-bridge --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'

     比如得到 172.17.0.3

  2) docker-compose.yml 里删掉 networks 那两段（保持默认网络即可）

  3) 插件配置里 Bridge主机 填那个 IP：172.17.0.3

  【注意】容器重启后 IP 可能会变。如果变了，重新查一次改配置。
  长期使用建议改用自定义网络（就是第 4 步的方式）。


==============================================================
日常维护
==============================================================

  查看状态：
      cd /opt/bridge33 && docker compose ps

  看日志：
      docker compose logs -f openqq-bridge

  重启：
      docker compose restart

  停止：
      docker compose down

  升级（换了新版本文件后）：
      docker compose up -d --build

  数据在哪：
      海豹数据：  SEALDICE_DATA_DIR（你的海豹目录）
      桥配置：    /opt/bridge33/config/
      迁移备份：  海豹目录里，文件名带 .bak


==============================================================
安全提醒
==============================================================

1. 桥只监听在 Docker 内部网络，没有暴露到公网
   —— 所以不需要开防火墙端口，也不要手贱加 ports。

2. Bridge访问令牌一定要设置，而且要够长够随机。

3. 验证码走你自己的 SMTP 邮箱，不经过第三方服务器。

4. 桥只读写本机 sqlite 文件，不上传任何数据。


==============================================================
速查清单（照着做就行）
==============================================================

  □ 1. find / -name "data-logs.db" 找到海豹数据目录
  □ 2. docker ps 和 docker inspect 查到海豹网络名
  □ 3. docker 文件夹传到 /opt 后改名为 /opt/bridge33（里面直接有 Dockerfile）
  □ 4. cp .env.example .env，改两行
  □ 5. docker-compose.yml 加 networks（name 填海豹的网络）
  □ 6. docker compose up -d --build
  □ 7. docker compose logs 看没有报错
  □ 8. js 放进海豹 scripts 目录，重启海豹
  □ 9. 插件配置：Bridge主机=openqq-bridge，端口=38999，令牌=.env 里那串
  □ 10. 群里发 .旧QQ桥状态 测试

==============================================================
附：本次实际部署记录（2590156487 实例，可直接照抄）
==============================================================

真实环境：Ubuntu 26.04 + Docker 29.8.1，海豹与 NapCat 都是容器，
数据目录 /opt/SealDice-Docker/<实例ID>/data/default。

【踩到的坑 1】status=1 / exit=2 的真正原因
    容器以 uid 10001 运行，而宿主机的 config 目录归 root，
    导致 /app/entrypoint.sh 写 bridge_bindings.json 失败：
        cannot create /config/bridge_bindings.json: Permission denied
    容器随即退出并被 restart 策略无限重启。
    验证方式：
        docker inspect openqq-bridge-2590156487 --format '{{.State.ExitCode}}'
        docker compose logs --tail 40

【踩到的坑 2】桥读不了海豹数据库
    海豹容器以 root 跑，数据库文件是 root:root 644。
    桥用 uid 10001 就写不了（迁移/备份都需要写）。

    最省事的做法：让桥也用 root，和海豹保持一致。
    在 docker-compose.yml 的 container_name 下面加一行：

        user: "0:0"

    然后 docker compose up -d 重建容器即可。
    （这台上就是这么做的，之后不需要再 chown 海豹的数据目录。）

【本次使用的 compose（/opt/openqq-bridge-2590156487/docker-compose.yml）】

services:
  openqq-bridge:
    build:
      context: .
      dockerfile: Dockerfile
    image: openqq-qq-sync-bridge:3.5
    container_name: openqq-bridge-2590156487
    user: "0:0"
    restart: unless-stopped
    environment:
      OPENQQ_BRIDGE_PORT: "38999"
      OPENQQ_BRIDGE_TOKEN: "${OPENQQ_BRIDGE_TOKEN:?请先在 .env 里设置 OPENQQ_BRIDGE_TOKEN}"
    volumes:
      - "${SEALDICE_DATA_DIR:-./sealdice-data}:/data"
      - "./config:/config"
    networks:
      - sealdice_net

networks:
  sealdice_net:
    external: true
    name: 2590156487_sealdice

【插件配置可以免手工填】
    海豹的插件配置存在
        data/default/configs/plugin-configs.json
    里面按插件名分组。插件名是 openqq_qq_realtime_sync_v20，
    可以先把配置写进去，再启动海豹，海豹注册配置时会保留已写入的
    value（只有类型变了才重置），于是桥地址/端口/令牌自动就位。

    关键顺序：
        1) 把 OpenQQ-QQ-Sync-v3.5.js 放进 scripts/
        2) docker stop sealdice-<ID>
        3) 写入 plugin-configs.json 里该插件的配置
        4) docker start sealdice-<ID>

    桥的主机名填【容器名】openqq-bridge-<ID>，
    而不是 127.0.0.1，也不是宿主机 IP。

【本次实例的插件配置值】
    bridge_host  = openqq-bridge-2590156487
    bridge_port  = 38999
    bridge_token = <和 .env 里一致>
    sender_email = （留空，由使用者自己填）
    smtp_password= （留空）
    smtp_host    = smtp.qq.com
    smtp_port    = 465

【验证命令（照抄可用）】
    从海豹容器里直接问桥：
        docker exec sealdice-<ID> sh -c 'wget -qO- http://openqq-bridge-<ID>:38999/health'

    查某个旧 QQ 的角色卡：
        docker exec sealdice-<ID> sh -c 'wget -qO- "http://openqq-bridge-<ID>:38999/lookup?token=<TOKEN>&old=<旧QQ号>"'

    确认桥没有暴露到公网：
        ss -lntp | grep 38999     # 应该没有输出

    确认插件已被海豹加载：
        grep -a "正在读取脚本.*OpenQQ" /opt/SealDice-Docker/<ID>/data/main.log | tail -3
