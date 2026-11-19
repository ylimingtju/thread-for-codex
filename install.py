#!/usr/bin/env python3
"""Install the local Director edition or switch back to the installed upstream copy."""
import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCAL = "codex-director@director-local"
UPSTREAM = "codex-director@novotnyllc"


def rpc(method, params):
    """Use the local Codex app server so Codex owns writes to its configuration."""
    with subprocess.Popen(
        ["codex", "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True,
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


def installed():
    plugins = {}
    for market in ("director-local", "novotnyllc"):
        data = subprocess.check_output(
            ["codex", "plugin", "list", "--marketplace", market, "--json"], text=True,
        )
        plugins.update((p["pluginId"], p) for p in json.loads(data)["installed"])
    return plugins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-original", action="store_true", help="切回已安装的作者原版")
    args = parser.parse_args()
    if not args.restore_original:
        subprocess.run(["codex", "plugin", "marketplace", "add", str(ROOT)], check=True)
        subprocess.run(["codex", "plugin", "add", LOCAL], check=True)
    plugins = installed()
    active, other = (UPSTREAM, LOCAL) if args.restore_original else (LOCAL, UPSTREAM)
    if active not in plugins:
        raise SystemExit(f"本机没有安装 {active}。")
    edits = [
        {"keyPath": f'plugins.{key}.enabled', "value": enabled, "mergeStrategy": "replace"}
        for key, enabled in ((active, True), (other, False))
        if key in plugins and plugins[key]["enabled"] != enabled
    ]
    if edits:
        rpc("config/batchWrite", {"edits": edits})
    plugins = installed()
    if not plugins[active]["enabled"] or plugins.get(other, {}).get("enabled"):
        raise SystemExit("版本切换未生效，请查看 Codex 插件设置。")
    print(f"已启用 {active} {plugins[active]['version']}。请在新聊天中启动 Director。")


if __name__ == "__main__":
    main()
