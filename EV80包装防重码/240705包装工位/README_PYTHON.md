# Python 包装工位

这是原 LabVIEW 包装工位的 Python 迁移实现。原 `.vi` 文件保持不变，仅新增 `python_app/`。

当前生产规则固定每箱 12 件，界面提供 12 个产品格。数据库历史重码或当前箱内重码会立即停止扫码，必须在屏幕上人工确认后才能继续；旧 `D:\数量.txt` 保留但不再读取。

## 开发运行

```powershell
powershell -ExecutionPolicy Bypass -File ".\运行包装工位.ps1"
```

启动脚本会把 Python 程序同步到 `%LOCALAPPDATA%\PackagingStation\runtime` 后运行，避免直接从 `U:` 网络盘导入模块导致长时间无界面。首次启动会自动安装缺失依赖。

远程电脑必须先安装 Python 3.12/3.13/3.14 x64，并确认下面命令能显示真实安装路径；`C:\Windows\System32\WindowsApps\python.exe` 只是系统占位别名，不能使用。

```powershell
where.exe python
py -3.12 --version
```

正式运行前，将 `python_app/config.example.toml` 复制为 `%ProgramData%\PackagingStation\config.toml`，通过 `PACKAGING_DB_PASSWORD` 提供数据库密码，并在目标现场电脑核对 BarTender、标签模板和 D 盘状态文件。

扫码枪既可走 TCP（`mode = "tcp"`，填 `host`/`port`），也可直接接串口（`mode = "serial"`，填 `com_port`/`baudrate`，串口模式需要 `pyserial`，启动脚本会自动安装）。

现场 `test.information` 表按 `[columns]` 映射读取：以 `上线码` 作为装箱码，取该码最新一条记录的 `干检结果`（`OK` 才允许装箱），装箱时把箱码回写到 `装箱码` 列；历史重码 = 该上线码任一记录 `装箱码` 非空，当前箱重码 = 本箱 12 格内重复。界面工序灯显示 `干检`/`氦检`/`拧紧` 的最新结果，其中只有 `[checks]` 里打开的工序会阻断装箱（当前只开 `dry_test`，氦检/拧紧仅显示）；`pack_min_length = 22` 表示 22 位及以上的扫码进入装箱流程，更短的按仅查询处理。

## 测试与打包

```powershell
pytest -q
pyinstaller --noconfirm --clean --onedir --windowed --name PackagingStation python_app/__main__.py
```

首次现场切换必须先执行只读预检、备份原 VI/标签/状态文件并人工确认；数据库、扫码器或打印机异常时程序会阻止包装。

## 可选：奇瑞 KD 标签二维码

默认关闭。在 `%ProgramData%\PackagingStation\config.toml` 中设置：

```toml
[chery_label]
enabled = true
part_no = "30100351AA"
batch = "你的发运批次"
layers = "4"
qr_payload_file = "D:/奇瑞二维码.txt"
```

开启后，箱满完成时仍按原路径写入 `装箱上线码0~11.txt`、`数量.txt`、`最终装箱码.txt`；随后额外写入 `奇瑞二维码.txt`（mbcs），供 BarTender 模板读取。供应商代码固定 `8KN`，纸箱唯一码按零件前缀自动递增。界面在开启时会显示零件/发运批次/码放层数字段；也可用配置默认值驱动。

