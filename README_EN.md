<div align="center">

# Side Translate

A lightweight and bright Windows desktop translator with mouse-selection, hotkey, and screenshot translation.

[简体中文](README.md) | [English](README_EN.md)

![Windows](https://img.shields.io/badge/Windows-10%2F11-2563EB)
![Python](https://img.shields.io/badge/Python-3.10%2B-0F766E)
![Translation](https://img.shields.io/badge/Engine-Baidu_Translate-EA580C)

</div>

![Side Translate main window](docs/images/app-quick.png)

## Features

- Automatically translate text after selecting it with the mouse in any application
- Translate the current text selection with a global hotkey
- Open Windows Screen Snipping, recognize the selected region with Baidu OCR, and translate it
- Show results in a rounded popup near the cursor that can be moved, resized, and pinned
- Automatically detect the source language and support multiple target languages
- Configure global hotkeys, popup placement, always-on-top behavior, and mouse-selection translation
- Record clipboard, OCR, network, and total timings for performance diagnostics
- Encrypt Baidu credentials with Windows DPAPI and store them only for the current Windows user
- Run from source without third-party Python runtime packages

## Default Hotkeys

| Action | Hotkey |
| --- | --- |
| Translate selected text | `Ctrl+Alt+T` |
| Screenshot translation | `Ctrl+Alt+S` |
| Toggle mouse-selection translation | `Ctrl+Alt+A` |
| Exit | Press `Ctrl+Q` in the main window |

The first three hotkeys can be changed on the Settings page.

## Translation Popup

![Translation popup](docs/images/translation-popup.png)

The popup appears near the cursor by default. Drag its title bar to switch to a fixed position, and resize it from the bottom-right corner.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or later, only when running from source
- A working Tcl/Tk runtime, normally included by the official Windows Python installer
- Network access to Baidu translation services

## Configure Baidu Services

Side Translate uses two independent sets of Baidu credentials:

| Feature | Service | Credentials |
| --- | --- | --- |
| Text translation | [Baidu Translate Open Platform](https://fanyi-api.baidu.com/) | `App ID` and secret key |
| Screenshot OCR | [Baidu Cloud OCR](https://cloud.baidu.com/product/ocr.html) | `API Key` and `Secret Key` |

1. Create an application on Baidu Translate Open Platform and enable the general text translation API.
2. If screenshot translation is required, create an OCR application in Baidu Cloud.
3. Start Side Translate and enter the corresponding credentials on the Settings page.
4. Save the settings.

OCR credentials are not required when only text translation is used.

## Run From Source

Download or clone the repository, then run this command in the project directory:

```powershell
python main.py
```

You can also double-click `start.bat`. Global hotkeys and mouse-selection monitoring remain active while the main window is minimized. Closing the main window exits the application.

Run the tests with:

```powershell
python -m unittest discover -s tests -v
```

## Build the EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The script installs PyInstaller on its first run. The executable is generated at:

```text
dist\SideTranslate\SideTranslate.exe
```

The current build uses PyInstaller's one-folder mode. Keep the complete `dist\SideTranslate` folder when running or distributing the application; the EXE cannot be distributed by itself.

Create an archive for a GitHub Release:

```powershell
Compress-Archive `
  -Path .\dist\SideTranslate `
  -DestinationPath .\SideTranslate-Windows-x64.zip `
  -Force
```

## Configuration, Logs, and Privacy

Configuration file:

```text
%APPDATA%\SideTranslate\config.json
```

Log file:

```text
%APPDATA%\SideTranslate\logs\app.log
```

- Baidu credentials are encrypted with Windows DPAPI and cannot be directly decrypted by another Windows user.
- Log files rotate at 1 MB, with three backups retained.
- Logs contain stages, timings, character counts, and image sizes. They do not contain source text, translated text, or Baidu credentials.
- Text translation sends the selected text to the Baidu Translate API.
- Screenshot translation sends the selected image to Baidu OCR and then sends the recognized text to Baidu Translate.

Common timing events:

| Log event | Meaning |
| --- | --- |
| `selection.capture.complete` | Time spent copying the selection and reading the clipboard |
| `screenshot.capture.complete` | Time spent waiting for and reading the screenshot |
| `ocr_auth.complete` | OCR authentication time |
| `http.complete operation=ocr` | OCR network request time |
| `http.complete operation=translation` | Translation network request time |
| `operation.complete` | Total operation time |

## Project Structure

```text
.
├── main.py                       # Application entry point
├── side_translate/
│   ├── app.py                    # Main window, popup, and event flow
│   ├── baidu.py                  # Baidu Translate and OCR client
│   ├── config.py                 # Configuration and DPAPI encryption
│   ├── logging_setup.py          # Rotating application logs
│   └── windows.py                # Global hotkeys, mouse hook, and clipboard
├── tests/test_core.py            # Core logic tests
├── build.ps1                     # PyInstaller build script
└── start.bat                     # Windowed launcher
```

## Publish Manually to GitHub

This project does not create a repository or push code automatically. Before publishing, verify that:

- `.gitignore` excludes `build/`, `dist/`, `*.spec`, caches, and local tool directories
- No Baidu credentials, configuration files, or logs are present in the repository
- The repository's MIT `LICENSE` file remains included

Create an empty repository on GitHub without an automatically generated README, then run:

```powershell
git init
git add .
git commit -m "Initial release"
git branch -M main
git remote add origin https://github.com/<YOUR_ACCOUNT>/<REPOSITORY_NAME>.git
git push -u origin main
```

To publish binaries, create a GitHub Release and upload `SideTranslate-Windows-x64.zip`. Do not commit `dist/` to the source branch.

## Known Limitations

- Windows is the only supported platform.
- Side Translate may also need to run as administrator when copying text from an elevated application.
- Mouse-selection translation does not work in applications that do not support standard copy operations; use screenshot translation instead.
- Baidu API latency, quotas, and request-rate limits depend on the associated Baidu account plan.

## License

This project is licensed under the [MIT License](LICENSE).
