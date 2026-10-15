from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    trade_db: Path
    auth_db: Path
    base_url: str = "https://localhost"
    ib_host: str = "127.0.0.1"
    ib_port: int = 4004
    ib_client_id: int = 71
    ib_account: str = ""
    execute_paper_orders: bool = False
    poll_seconds: int = 60
    protocol: Path = Path("../../research/protocol.json")
    local_dev: bool = False

    @property
    def loopback_http(self):
        parsed = urlsplit(self.base_url)
        return self.local_dev and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}

    @classmethod
    def from_env(cls):
        default_root = (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "MyQuant"
                        if os.name == "nt" else Path("/workspace/MyQuant/runtime"))
        root = Path(os.environ.get("MYQUANT_RUNTIME", str(default_root)))
        url = os.environ.get("DASHBOARD_BASE_URL", "https://localhost").rstrip("/")
        parsed = urlsplit(url)
        if (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                or not parsed.hostname):
            raise ValueError("DASHBOARD_BASE_URL must contain only scheme, hostname and optional port")
        if parsed.scheme != "https" and not (
            os.environ.get("DASHBOARD_LOCAL_DEV") == "1"
            and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError("Public dashboard requires HTTPS; local HTTP is permitted only for loopback development")
        return cls(
            trade_db=Path(os.environ.get("TRADE_DB", str(root / "trading" / "paper.sqlite3"))),
            auth_db=Path(os.environ.get("AUTH_DB", str(root / "auth" / "auth.sqlite3"))),
            base_url=url, ib_host=os.environ.get("IBKR_HOST", "127.0.0.1"),
            ib_port=int(os.environ.get("IBKR_PORT", "4004")),
            ib_client_id=int(os.environ.get("IBKR_CLIENT_ID", "71")),
            ib_account=os.environ.get("IBKR_PAPER_ACCOUNT", ""),
            execute_paper_orders=os.environ.get("PAPER_ORDERS_ENABLED", "false").lower() == "true",
            poll_seconds=max(15, int(os.environ.get("WORKER_POLL_SECONDS", "60"))),
            protocol=Path(os.environ.get("RESEARCH_PROTOCOL", "../../research/protocol.json")),
            local_dev=os.environ.get("DASHBOARD_LOCAL_DEV") == "1",
        )
