# 将工作区数据集迁入共享 DATASET

`$DATASET` 在宿主机指向 `/media/local/NVME-Storage/dataset`，在成员容器指向 `/home/<username>/dataset`，兼容 `/datasets`。两者是同一份数据。共享目录对成员只读，所以成员容器内不能直接执行 `mv ... "$DATASET"`；由管理员在“宿主机 → 远程 vscode”的终端中导入。`$DATASET_ELAB_SHARE` 是只读 NAS 数据源，不作为上传目标。

按 `$DATASET/<用户名>/<数据集名>` 分目录，避免不同成员的同名数据集相互覆盖。放入共享目录的数据对所有成员可读，个人私有数据继续保存在工作区。

## 1. 成员告诉管理员源位置

例如成员 yinshengwang 的 `/workspace/my_dataset`，在宿主机对应：

```text
/home/local/gpu-cluster-system/runtime/users/yinshengwang/workspace/my_dataset
```

如果源目录在项目内部，例如 `/workspace/project/data`，下方 `src` 也应改成对应的 `workspace/project/data`。导入期间暂停向源目录写入，尤其是下载、解压和预处理；不需要停止只读取其他目录的训练。

## 2. 管理员复制到临时目录，校验后发布

在真实宿主机的 local 用户终端运行。先修改下面的 `member`、`name`、`src`，逐行核对。`sudo` 使用宿主机 local 用户密码。

```bash
bash <<'BASH'
set -euo pipefail
member=yinshengwang
name=my_dataset
src="/home/local/gpu-cluster-system/runtime/users/$member/workspace/$name"
shared=/media/local/NVME-Storage/dataset
dst="$shared/$member/$name"
staging="$shared/$member/.$name.importing-$(date +%Y%m%d-%H%M%S)"

test -d "$src" && test ! -L "$src"
test -d "$shared"
test "$(findmnt -n -o UUID -T "$shared")" = aa347f5c-9f6d-4d60-b63e-d1fc2370177a
test ! -e "$dst" && test ! -L "$dst"
test ! -e "$staging" && test ! -L "$staging"
install -d -m 0755 "$shared/$member"

sudo rsync -aH --chown="$(id -u):$(id -g)" --chmod=D755,F644 \
  --info=progress2 -- "$src/" "$staging/"

changes=$(sudo rsync -rcln --delete --itemize-changes -- "$src/" "$staging/")
if [ -n "$changes" ]; then
  printf '%s\n' "$changes"
  echo '校验发现差异，请暂停源目录写入并检查；原目录和临时目录均保留。' >&2
  exit 1
fi

# 在同一 NVMe 文件系统内原子发布；不覆盖已有数据集。
mv -Tn -- "$staging" "$dst"
test ! -e "$staging"
printf '已发布到 %s；源目录保留。\n' "$dst"
BASH
```

`rsync -rcln` 中 `-c` 校验文件内容，`-n` 是 dry run。这里的 `--delete` 仅报告目标多出的目录项，不执行删除。若中途失败，保留源目录和临时目录供检查，不执行任何源文件清理。

这是本机 NVMe 的 UUID 检查，用来避免磁盘未挂载时误把数据复制回系统盘。`--chown` 和 `--chmod` 只调整目标副本的所有者和读权限，源文件权限保持不变。`install -d -m 0755` 确保成员父目录可读，即使宿主机管理员终端使用严格的 umask 0077。导入目录中的外部软链接不会自动复制其目标内容，应先检查这些链接是否能在成员容器里解析。

发布后，已有工作区、调试和训练容器的共享挂载会立即看到该数据集，无需重启容器。

## 3. 成员验证访问，再切换旧路径

在成员自己的容器终端中：

```bash
ls "$DATASET/$(id -un)/my_dataset"
```

代码也可直接读取 `os.environ['DATASET']` 下的 `<用户名>/my_dataset`。

如果希望原来的 `/workspace/my_dataset` 路径继续使用，在确认共享目录内容正确、暂停使用原目录的预处理/训练后，由成员执行以下命令。它将原件改名保留，再用容器内的共享路径建立软链接：

```bash
bash <<'BASH'
set -euo pipefail
src=/workspace/my_dataset
shared="${DATASET:?}/$(id -un)/my_dataset"
backup="$src.before-shared-$(date +%Y%m%d-%H%M%S)"
test -d "$src" && test ! -L "$src"
test -d "$shared"
test ! -e "$backup" && test ! -L "$backup"
mv -T -- "$src" "$backup"
if ! ln -s -- "$shared" "$src"; then
  mv -T -- "$backup" "$src"
  exit 1
fi
printf '原件保留在 %s；请验证训练后再联系管理员清理。\n' "$backup"
BASH
```

软链接保存的是成员容器内的路径。不要在成员工作区建立指向宿主机 `/media/local/...` 的链接，因为该路径没有直接挂载到成员容器中。

保留原件阶段尚未释放工作区磁盘空间。确认代码和训练均正常读取共享目录、没有旧目录的读写进程后，管理员再清理已核验的备份；本流程不提供或自动执行删除命令。
