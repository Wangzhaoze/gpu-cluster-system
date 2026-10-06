import React from "react";

export function HelpPage({ admin }: { admin: boolean }) {
  return <div className="help-page">
    <section className="panel">
      <h2>系统如何工作</h2>
      <div className="architecture-wrap">
        <svg className="architecture" viewBox="0 0 930 300" role="img" aria-labelledby="architecture-title architecture-desc">
          <title id="architecture-title">GPU Lab 系统架构</title>
          <desc id="architecture-desc">浏览器经过 Cloudflare 访问门户。管理员连接原生宿主机 VS Code；成员任务由调度器分配到隔离容器和 GPU，文件保存在持久化存储中。</desc>
          <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" /></marker></defs>
          <g className="architecture-lines" markerEnd="url(#arrow)">
            <path d="M135 130 H170" /><path d="M300 130 H335" />
            <path d="M470 130 H495 V55 H520" /><path d="M470 130 H495 V205 H520" />
            <path d="M665 55 H705" /><path d="M665 205 H705" /><path d="M780 175 V85" /><path d="M780 235 V260" />
          </g>
          <g className="architecture-nodes">
            <rect x="10" y="100" width="125" height="60" rx="8"/><rect x="170" y="100" width="130" height="60" rx="8"/>
            <rect x="335" y="100" width="135" height="60" rx="8"/><rect x="520" y="25" width="145" height="60" rx="8"/>
            <rect x="520" y="175" width="145" height="60" rx="8"/><rect x="705" y="25" width="160" height="60" rx="8"/>
            <rect x="705" y="175" width="160" height="60" rx="8"/>
          </g>
          <g className="architecture-labels" textAnchor="middle">
            <text x="72" y="135">浏览器</text><text x="235" y="135">Cloudflare</text><text x="402" y="135">门户 / 权限验证</text>
            <text x="592" y="50">宿主机 VS Code</text><text x="592" y="70" className="architecture-caption">管理员 · local 用户</text>
            <text x="592" y="201">任务调度器</text><text x="592" y="221" className="architecture-caption">队列 / 审批 / 显卡选择</text>
            <text x="785" y="50">持久化文件 / Python 环境</text><text x="785" y="70" className="architecture-caption">停止容器仍保留</text>
            <text x="785" y="201">成员隔离容器</text><text x="785" y="221" className="architecture-caption">工作区 / 调试 / 训练</text>
            <text x="780" y="285">GPU 显卡池</text>
          </g>
        </svg>
      </div>
    </section>
    <section className="panel">
      <h2>1. 登录与远程访问</h2>
      <ol className="steps">
        <li>在“远程访问”复制当前 HTTPS 链接，在其他设备打开后使用同一门户账号登录。</li>
        <li>初次登录后到“我的账号”修改初始密码。修改后所有旧登录会失效，请使用新密码登录。</li>
        <li>宿主机和 Docker 需要保持运行。Cloudflare 临时隧道重启会产生新的地址。</li>
      </ol>
    </section>
    {admin ? <>
      <section className="panel">
        <h2>2. 管理账号与宿主机</h2>
        <ol className="steps">
          <li>在“用户管理”创建成员，选择默认 PyTorch 模板、GPU 上限和调试免审批上限，复制登录信息给成员。初始密码只在创建后的信息卡中临时显示。</li>
          <li>“宿主机 → 远程 vscode”连接真实 Ubuntu，以 Linux local 用户访问文件和 Docker。所有管理员共享这个宿主机身份。</li>
          <li>打开 VS Code 后选择 Terminal → New Terminal。系统操作使用 sudo，输入 Linux local 用户密码；它与门户密码不同。</li>
          <li>“存储”的 workspace 地址可以复制，也可直接在远程 vscode 打开该成员目录，帮助导入文件或排查问题。</li>
        </ol>
        <pre>{'docker ps\nnvidia-smi\npython -c "import torch; print(torch.__version__, torch.cuda.is_available())"\nsudo systemctl status docker'}</pre>
      </section>
      <section className="panel">
        <h2>3. 管理训练与调试</h2>
        <p>管理员查看、编辑、停止和删除记录，使用成员账号提交实验。排队中的记录可以修改资源、GPU 选择、时长和训练命令；运行中只可修改总时长，截止时间按原启动时间计算。启动中或已经结束的记录不能编辑。</p>
        <p>超过 10 小时的调试在批准前不占 GPU，也不进入运行队列。管理员在“在线调试”批准或拒绝；审批意见保存在记录中。编辑待审批申请后仍须点击批准。</p>
        <p>停止或取消任务会释放 GPU。删除记录需要任务先结束，仅删除记录和日志，保留工作区及结果。删除工作区会清除代码、Python 环境和缓存；删除用户前须停用账号并结束任务。共享数据和宿主机目录受到保护。</p>
      </section>
    </> : <>
      <section className="panel">
        <h2>2. 工作区与 Python</h2>
        <ol className="steps">
          <li>在“工作区”点击启动，等待运行中后打开 VS Code；确认目录可信，再选择 Trust Folder &amp; Continue。</li>
          <li>选择 Terminal → New Terminal。代码保存在 /workspace，共享数据从只读 /datasets 读取，输出保存在 /results，缓存位于 /scratch。</li>
          <li>默认 Python 是 /opt/user-env/venv/bin/python，终端自动激活持久化环境。使用 pip 安装的包可在工作区、调试和训练中复用。</li>
          <li>停止或重新创建容器保留文件和 Python 包；容器中通过 apt 安装的软件不随容器重建保留。</li>
        </ol>
        <pre>{'python -c "import sys, torch; print(sys.executable, torch.__version__)"\npip install rich'}</pre>
      </section>
      <section className="panel">
        <h2>3. 调试、训练与公共队列</h2>
        <p>工作区使用 CPU。交互式 GPU 实验到“在线调试”提交会话；批量实验到“训练任务”填写命令和资源。训练输出目录通过环境变量 LAB_RESULT_DIR 提供。</p>
        <p>自动分配使用可用显卡，也可以指定显卡。指定的卡忙碌时等待该卡，不会换成其他卡。平台避开外部进程占用的 GPU；监控不可用时 GPU 任务等待恢复。容器内的一张 GPU 显示为 CUDA 设备 0。</p>
        <p>十小时以内按账号限额直接申请；超过十小时（最多七天）填写理由并等待管理员批准。会话运行后开始计时，关闭浏览器不会停止会话；结束实验时点击停止。使用 PyTorch 建议分配至少 4096 MB 内存。</p>
        <p>所有成员的任务摘要与队列公开。你只能打开、读取日志、取消或重试自己的任务，其他人的命令、日志和编辑器入口不公开。</p>
        <pre>{'nvcc --version\nnvidia-smi\npython -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"'}</pre>
      </section>
    </>}
    <section className="panel">
      <h2>4. 环境变量与固定模板</h2>
      <p>{admin ? '管理员可设置全局变量，也可选择单个用户设置个人变量。' : '全局变量由管理员设置，你可以新增、修改或删除自己的变量。相同名称的个人变量覆盖全局值。'}优先级为任务覆盖、个人设置、全局设置、默认值。修改立即同步到门户，在下一次创建工作区、调试或训练容器时注入；已经运行的容器不会自动改变。</p>
      <p>变量名使用字母、数字和下划线，不能修改 PATH、HOME、CUDA_VISIBLE_DEVICES 或以 LAB_、NVIDIA_ 开头的系统变量。删除个人变量后，下次创建容器会恢复同名全局值。</p>
      <p>Python 环境固定在管理员分配的镜像模板上。模板版本在“环境”查看；更换镜像需要用户空闲并确认 Python 兼容性。共享 /datasets 只读；存储统计包括工作目录、结果和缓存，不包括 Python volume。</p>
    </section>
  </div>;
}
