#!/usr/bin/env python3
"""Install the local Director edition or switch back to the installed upstream copy."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCAL = "codex-director@director-local"
UPSTREAM = "codex-director@novotnyllc"
MARKETPLACE = Path(".agents/plugins/marketplace.json")
PLUGIN = Path("plugins/codex-director")


def find_codex(explicit):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file() or (sys.platform == "win32" and path.suffix.lower() != ".exe"):
            raise SystemExit("--codex 必须指向可执行的 Codex CLI 文件。")
        return str(path)

    if sys.platform == "win32":
        # Match the desktop app's config format before trying an independent CLI.
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
            "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        try:
            result = subprocess.run(
                [str(powershell), "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
                 "Get-AppxPackage -Name OpenAI.Codex | "
                 "Sort-Object Version -Descending | Select-Object -First 1 -ExpandProperty InstallLocation"],
                capture_output=True, encoding="utf-8", check=True, timeout=10,
            )
            if result.stdout.strip():
                packaged = Path(result.stdout.strip()) / "app/resources/codex.exe"
                if packaged.is_file():
                    return str(packaged)
        except (OSError, subprocess.SubprocessError):
            pass
        command = shutil.which("codex.exe")
        if command:
            return command
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            standalone = Path(local_app_data) / "Programs/OpenAI/CodexCLI/codex.exe"
            if standalone.is_file():
                return str(standalone)
    else:
        command = shutil.which("codex")
        if command:
            return command
    raise SystemExit("找不到支持 codex plugin 的 Codex CLI。请使用 --codex 指定其路径。")


def _windows_file_path(path):
    """Use Win32 extended-length paths for staging filesystem operations."""
    value = str(path)
    if value.startswith("\\\\?\\"):
        return path
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def windows_marketplace():
    """Prepare the Windows checkout payload before Codex copies it into its plugin cache."""
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    market = (codex_home / "codex-director").resolve() / "windows-marketplace"
    target = _windows_file_path(market)
    source = _windows_file_path(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="marketplace-", dir=target.parent) as temp:
        stage = Path(temp) / "new"
        backup = Path(temp) / "previous"
        (stage / MARKETPLACE.parent).mkdir(parents=True)
        shutil.copy2(source / MARKETPLACE, stage / MARKETPLACE)
        shutil.copy2(source / "LICENSE", stage)
        shutil.copytree(source / PLUGIN, stage / PLUGIN, ignore=shutil.ignore_patterns("__pycache__"))
        config = stage / PLUGIN / ".mcp.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        server = data["mcpServers"]["director-panel"]
        server["command"] = sys.executable
        server["env_vars"].extend(["USERPROFILE", "SYSTEMROOT"])
        config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        hooks_file = stage / PLUGIN / "hooks" / "hooks.json"
        hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
        footer_hook = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        python_path = sys.executable.replace("'", "''")
        footer_hook["commandWindows"] = (
            f"& '{python_path}' -B -X utf8 (Join-Path $env:PLUGIN_ROOT 'worker_reply.py')"
        )
        hooks_file.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")

        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise
    return market


def install_local(codex):
    market = ROOT
    previous = None
    if sys.platform == "win32":
        market = windows_marketplace()
        data = subprocess.check_output(
            [codex, "plugin", "marketplace", "list", "--json"], encoding="utf-8",
        )
        # Migrate an earlier manual installation from this checkout to the Windows payload.
        for entry in json.loads(data)["marketplaces"]:
            if entry["name"] == "director-local" and Path(entry["root"]).resolve() == ROOT:
                subprocess.run([codex, "plugin", "marketplace", "remove", "director-local"], check=True)
                previous = ROOT
                break
    try:
        subprocess.run([codex, "plugin", "marketplace", "add", str(market)], check=True)
    except subprocess.CalledProcessError:
        if previous:
            subprocess.run([codex, "plugin", "marketplace", "add", str(previous)])
        raise
    subprocess.run([codex, "plugin", "add", LOCAL], check=True)


def rpc(codex, method, params):
    """Use the local Codex app server so Codex owns writes to its configuration."""
    with subprocess.Popen(
        [codex, "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, encoding="utf-8",
    ) as process:
        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def request(number, name, arguments):
            send({"id": number, "method": name, "params": arguments})
            for line in process.stdout:
                response = json.loads(line)
                if response.get("id") == number:
                    if "error" in response:
                        raise RuntimeError(response["error"])
                    return response["result"]
            raise RuntimeError("Codex 服务在返回结果前退出。")

        try:
            request(1, "initialize", {"clientInfo": {"name": "director-local", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
            send({"method": "initialized"})
            return request(2, method, params)
        finally:
            process.stdin.close()
            process.terminate()


def installed(codex):
    plugins = {}
    for market in ("director-local", "novotnyllc"):
        data = subprocess.check_output(
            [codex, "plugin", "list", "--marketplace", market, "--json"], encoding="utf-8",
        )
        plugins.update((p["pluginId"], p) for p in json.loads(data)["installed"])
    return plugins


def main():
    if sys.version_info < (3, 9):
        raise SystemExit("Thread for Codex 需要 Python 3.9 或以上。")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-original", action="store_true", help="切回已安装的作者原版")
    parser.add_argument("--codex", help="指定 Codex CLI 的完整路径")
    args = parser.parse_args()
    codex = find_codex(args.codex)
    if not args.restore_original:
        install_local(codex)
    plugins = installed(codex)
    active, other = (UPSTREAM, LOCAL) if args.restore_original else (LOCAL, UPSTREAM)
    if active not in plugins:
        raise SystemExit(f"本机没有安装 {active}。")
    edits = [
        {"keyPath": f'plugins.{key}.enabled', "value": enabled, "mergeStrategy": "replace"}
        for key, enabled in ((active, True), (other, False))
        if key in plugins and plugins[key]["enabled"] != enabled
    ]
    if edits:
        rpc(codex, "config/batchWrite", {"edits": edits})
    plugins = installed(codex)
    if not plugins[active]["enabled"] or plugins.get(other, {}).get("enabled"):
        raise SystemExit("版本切换未生效，请查看 Codex 插件设置。")
    print(f"已启用 {active} {plugins[active]['version']}。请在新聊天中启动 Director。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        sys.exit(str(error))
