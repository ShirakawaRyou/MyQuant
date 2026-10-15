"""Build a local-use delivery with allowlisted source and cached research; never broker runtime."""

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = {Path(name) for name in [".gitignore", ".gitattributes", ".dockerignore", ".python-version",
                                   "README.md", "pyproject.toml", "uv.lock"]}
    for folder, extensions in [
        ("src", {".py", ".otf", ".txt", ".md"}), ("tests", {".py"}),
        ("research", {".json", ".md", ".zip"}), ("windows", {".ps1", ".cmd", ".md"}),
        ("scripts", {".py"}), (".github/workflows", {".yml"}),
        ("deploy", {".md", ".py", ".yaml"}),
        ("services/dashboard", {".py", ".toml", ".lock", ".html", ".js", ".css", ".md"}),
        ("data/research-20261015", {".json", ".csv"}),
        ("reports/research-portable-20261015", {".json", ".csv", ".md", ".png"}),
    ]:
        for path in (ROOT / folder).rglob("*"):
            relative = path.relative_to(ROOT)
            if (path.is_file() and path.suffix in extensions
                    and not set(relative.parts) & {".venv", "__pycache__", ".pytest_cache", "runtime", "secrets"}):
                names.add(relative)
    names.update(Path(name) for name in ["deploy/Dockerfile", "deploy/Caddyfile", "deploy/.env.example"])
    manifest = json.loads((ROOT / "data/research-20261015/manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    for symbol, record in manifest["symbols"].items():
        for suffix, key in [("csv", "csv_sha256"), ("raw.json", "raw_sha256")]:
            data = ROOT / "data/research-20261015" / f"{symbol}.{suffix}"
            assert hashlib.sha256(data.read_bytes()).hexdigest() == record[key]
    output = ROOT / "reports/delivery/myquant-windows.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Delivery already exists; preserve it before rebuilding")
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(names):
            assert not name.name.startswith(".env") or name == Path("deploy/.env.example")
            assert not set(name.parts) & {"runtime", "secrets", ".git", ".venv"}
            archive.write(ROOT / name, Path("MyQuant") / name)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    output.with_suffix(".zip.sha256").write_text(hashlib.sha256(output.read_bytes()).hexdigest() + "  " + output.name + "\n")
    print(f"本地部署包：{output}；{len(names)} 个文件，{output.stat().st_size:,} 字节。")
    print("只含源码、固定研究数据与报告；不含 IBKR 凭据、运行账本、会话或日志。")


if __name__ == "__main__":
    main()
