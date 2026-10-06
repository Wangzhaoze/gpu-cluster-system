针对admin管理界面和member管理界面做一下改进：

admin界面：
    1. admin不提交训练任务，不提交调试申请，只监控/编辑/管理/停止/删除训练任务和调试会话，admin不需要额外创建这些
    2. admin任然保留“宿主机”选项卡，可以打开一个vscode界面来远程控制整个宿主机，只保留开始的一些说明和”打开宿主机vscode“按钮（改名为”远程vscode“），其他的操作例如打开集群项目，以及后面的操作教程都不需要，删除
    3. 登陆成为admin之后web颜色主题绿色部分改为对应的蓝色，深浅仍保持一致，和member的界面区分开
    4. 环境变量部分逻辑我还没有尝试，但是需要能为所有人统一/某个人单独设置一个变量+值，并且admin可以编辑/新增/删除/更新环境变量，”密钥“和”启用”是干什么的我不清楚，没什么必要存在的话就删掉
    5. （admin+member）远程访问界面里面只显示上半部分即可，下半部分说明去掉，看上去不够简洁
    6. （admin+member）各个界面都有一些说明性文字和注释，这确实挺好，但是让整个界面看上去有点不够简约，可以新增一个帮助界面，把所有教程/说明相关的内容按照章节或者顺序放在里面，甚至可以画一个系统架构说明图放在里面，帮助菜单放在导航栏最后一个


member界面：
    1. 工作区：算力已经显示了，但是下方有一些乱码显示“GPU 由
Debug
或
Training
分配
”之类的。优化一下；宿主机文件位置这个目录整个删掉，member成员不需要知道具体path也无权进入宿主机，只把每个member的workspace地址放到admin版本的web界面的存储里面就够了，每个成员新增一列workspace在宿主机上的绝对地址，方便admin直接进入帮忙调试。 “从宿主机导入项目
在宿主机终端把下面的 /path/to/project/ 替换成项目源目录后执行。命令会把文件复制到工作区的 project 子目录， 并设置为你的工作区用户所有，确保 Web 中可以继续编辑。已在使用的文件请先保存；如文件树尚未更新，点击 VS Code 资源管理器的刷新按钮。

sudo rsync -a --chown=2006:2006 -- /path/to/project/ /home/local/gpu-cluster-system/runtime/users/chenlinlang/workspace/project/
复制导入命令
导入后在 VS Code 中打开 /workspace/project，再新建终端继续开发。”以及“开始你的实验
点击「启动」，等待运行中后打开 VS Code。在菜单中选择 Terminal → New Terminal。 首次打开时，请自行确认工作目录可信，再选择 Trust Folder & Continue。
点击「启动」，等待运行中后打开 VS Code。在菜单中选择 Terminal → New Terminal。 首次打开时，请自行确认工作目录可信，再选择 Trust Folder & Continue。

编写代码
/workspace
工作目录，持续保存
读取数据
/datasets
共享数据集，只读
保存输出
/results
训练结果，持续保存
python -c "import sys; print(sys.executable)"
pip install rich
python -c "import rich; print('PERSIST_OK')"”这两部分也没有必要显示，暂时去掉，只保留第一个选项卡
    2. member可以新增调试和训练，同时应该可以看到所有member的会话和队列信息，而不是只看到自己的，信息公开，只不过member没有权限编辑其他人的调试会话和训练，也无法访问，只能看到member的简略信息
    3. member可以给自己增加/编辑/删除环境变量，且信息同步到admin版本界面上
    4. 远程访问和帮助菜单和admin版本一致

