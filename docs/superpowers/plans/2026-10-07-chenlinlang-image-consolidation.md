# chenlinlang 镜像迁移与清理执行记录

**Goal:** 将 chenlinlang 工作区迁移到另外两位成员同一镜像，并仅清理不影响学生使用的无用旧镜像和停止容器。

**Architecture:** 原项目/results/scratch 与个人 Python/state 卷保留；先备份，再交换容器并注入已验证权限修复。迁移后验证公网与真实 CUDA。用户随后收窄范围为镜像/容器，卷/目录/备份清理取消。必要服务镜像标签被手动删除后，从受控 Dockerfile 重建，生产服务保持原实例。

**Tech Stack:** Docker SDK、PostgreSQL/SQLAlchemy、FastAPI、Cloudflare。

- [x] 核对成员、镜像、UID、挂载及活跃任务。
- [x] 保存数据库、chenlinlang HOME（不含数据集）、个人 Python/state 卷及容器配置。
- [x] 迁移 chenlinlang 至3216ed3c5fa8镜像，原挂载和个人状态保留。
- [x] 三位成员公网、Python/Torch、DATASET 验证；chenlinlang真实GPU矩阵运算通过。
- [x] 保存旧HOME归档中的私人历史到对应成员状态卷并验证SHA256。
- [x] 删除旧chenlinlang停止容器、4个停止合成容器、1dbddb125c0b旧镜像。
- [x] 清理3个冗余镜像别名，设置学生实际镜像的清晰标签。
- [x] 受控重建被删的PostgreSQL/Traefik部署镜像并在独立无生产卷容器中验收，生产服务未重启。
- [x] 核对所有运行实例、挂载、卷及成员工作区目录未变，更新实际结果文档。

取消的扩展清理：测试卷、空目录、历史备份均保留，不执行此前完整清理计划。

结果文档：docs/IMAGE_CONSOLIDATION_2026-10-07.md。
