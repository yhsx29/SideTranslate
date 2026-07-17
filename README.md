<div align="center">

# 旁译

一款轻量、明亮的 Windows 桌面翻译工具，支持划词、快捷键和截图翻译。

[简体中文](README.md) | [English](README_EN.md)

![Windows](https://img.shields.io/badge/Windows-10%2F11-2563EB)
![Python](https://img.shields.io/badge/Python-3.10%2B-0F766E)
![Translation](https://img.shields.io/badge/Engine-Baidu_Translate-EA580C)

</div>

![旁译主界面](docs/images/app-quick.png)

## 功能

- 在任意应用中划选文本，释放鼠标后自动翻译
- 使用全局快捷键翻译当前选中的文本
- 调用 Windows 截图工具，使用百度 OCR 识别并翻译框选区域
- 在鼠标附近显示可拖动、可缩放、可固定的圆角翻译浮窗
- 支持自动检测源语言以及多种目标语言
- 可配置全局快捷键、浮窗位置、置顶状态和划词翻译开关
- 记录剪贴板、OCR、网络请求及总耗时，便于排查性能问题
- 百度凭据使用 Windows DPAPI 加密，仅保存在当前 Windows 用户下
- 源码运行不依赖第三方 Python 包

## 默认快捷键

| 操作 | 快捷键 |
| --- | --- |
| 翻译选中文本 | `Ctrl+Alt+T` |
| 截图翻译 | `Ctrl+Alt+S` |
| 开启或关闭划词翻译 | `Ctrl+Alt+A` |
| 退出程序 | 主窗口中按 `Ctrl+Q` |

前三个快捷键都可以在设置页修改。

## 翻译浮窗

![翻译浮窗](docs/images/translation-popup.png)

浮窗默认显示在鼠标附近。拖动标题栏后会切换为固定位置；右下角可以调整大小。

## 系统要求

- Windows 10 或 Windows 11
- Python 3.10 或更高版本，仅源码运行时需要
- 可用的 Tcl/Tk 运行环境，通常随 Windows Python 安装器提供
- 可访问百度翻译服务的网络连接

## 配置百度服务

旁译使用两套独立的百度凭据：

| 功能 | 服务 | 所需凭据 |
| --- | --- | --- |
| 文本翻译 | [百度翻译开放平台](https://fanyi-api.baidu.com/) | `App ID`、密钥 |
| 截图文字识别 | [百度智能云 OCR](https://cloud.baidu.com/product/ocr.html) | `API Key`、`Secret Key` |

1. 在百度翻译开放平台创建应用，并开通通用文本翻译 API。
2. 如需截图翻译，在百度智能云创建文字识别应用。
3. 启动旁译，打开“设置”页填写对应凭据。
4. 保存设置。

只使用文本翻译时，不需要填写 OCR 凭据。

## 从源码运行

下载或克隆仓库后，在项目目录执行：

```powershell
python main.py
```

也可以双击 `start.bat`。最小化主窗口后，全局快捷键和划词监听仍会继续工作。关闭主窗口会退出程序。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 打包为 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

首次运行脚本会安装 PyInstaller。打包结果位于：

```text
dist\SideTranslate\SideTranslate.exe
```

当前使用 PyInstaller 目录发布模式。运行或分发时需要保留整个 `dist\SideTranslate` 文件夹，不能只复制 EXE。

创建 GitHub Release 压缩包：

```powershell
Compress-Archive `
  -Path .\dist\SideTranslate `
  -DestinationPath .\SideTranslate-Windows-x64.zip `
  -Force
```

## 配置、日志与隐私

配置文件：

```text
%APPDATA%\SideTranslate\config.json
```

日志文件：

```text
%APPDATA%\SideTranslate\logs\app.log
```

- 百度凭据使用 Windows DPAPI 加密，其他 Windows 用户无法直接解密。
- 日志按 1 MB 滚动，保留 3 个历史文件。
- 日志记录阶段、耗时、字符数量和图片大小，不记录原文、译文或百度凭据。
- 文本翻译会将选中的文本发送到百度翻译 API。
- 截图翻译会将框选图片发送到百度 OCR，然后将识别文本发送到百度翻译 API。

常用耗时日志：

| 日志事件 | 含义 |
| --- | --- |
| `selection.capture.complete` | 复制选区和读取剪贴板耗时 |
| `screenshot.capture.complete` | 等待截图和读取图片耗时 |
| `ocr_auth.complete` | OCR 鉴权耗时 |
| `http.complete operation=ocr` | OCR 网络请求耗时 |
| `http.complete operation=translation` | 翻译网络请求耗时 |
| `operation.complete` | 本次操作总耗时 |

## 项目结构

```text
.
├── main.py                       # 程序入口
├── side_translate/
│   ├── app.py                    # 主窗口、浮窗与事件流程
│   ├── baidu.py                  # 百度翻译和 OCR 客户端
│   ├── config.py                 # 配置与 DPAPI 加密
│   ├── logging_setup.py          # 滚动日志
│   └── windows.py                # 全局快捷键、鼠标钩子和剪贴板
├── tests/test_core.py            # 核心逻辑测试
├── build.ps1                     # PyInstaller 打包脚本
└── start.bat                     # 无控制台窗口启动脚本
```

## 手动发布到 GitHub

本项目不会自动创建仓库或推送代码。发布前请确认：

- `.gitignore` 已排除 `build/`、`dist/`、`*.spec`、缓存和本机工具目录
- 仓库中不存在百度凭据、配置文件或日志
- 仓库中的 MIT `LICENSE` 文件保持不变

在 GitHub 创建一个空仓库，不要自动添加 README，然后在项目目录执行：

```powershell
git init
git add .
git commit -m "Initial release"
git branch -M main
git remote add origin https://github.com/<YOUR_ACCOUNT>/<REPOSITORY_NAME>.git
git push -u origin main
```

发布二进制文件时，建议在 GitHub 的 Releases 页面新建版本，并上传 `SideTranslate-Windows-x64.zip`，不要把 `dist/` 提交到源码分支。

## 已知限制

- 当前仅支持 Windows。
- 从以管理员身份运行的应用中复制文本时，旁译可能也需要以管理员身份运行。
- 某些不支持标准复制操作的应用无法进行划词翻译，可改用截图翻译。
- 百度 API 的响应速度、配额和频率限制由对应百度账号套餐决定。

## 许可证

本项目使用 [MIT License](LICENSE)。
