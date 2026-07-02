"""
WebDAV 同步模块

按需同步配置和数据文件到 WebDAV 服务器。
不常驻运行，只在需要同步时临时调用。
"""

import logging
import time
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


class WebDAVSync:
    """
    WebDAV 文件同步客户端。

    按需启动，执行完立即退出，不占用持续资源。

    注意：坚果云等 WebDAV 服务器不支持 HEAD 请求，因此使用
    disable_check=True 绕过 webdavclient3 内置的 HEAD 检查，
    改用 PROPFIND 进行所有存在性检查。
    """

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        remote_path: str = "/arxiv-daily-researcher/",
        proxy_url: str = "",
    ):
        try:
            from webdav3.client import Client
        except ImportError:
            raise ImportError(
                "WebDAV 同步需要 webdavclient3 库。请运行: pip install webdavclient3"
            )

        # webdav_hostname 必须去除末尾斜杠，避免 webdavclient3 拼接出 // 导致 403 错误
        hostname = url.rstrip("/")
        options = {
            "webdav_hostname": hostname,
            "webdav_login": username,
            "webdav_password": password,
            # 坚果云等服务器不支持 HEAD 请求，必须禁用 check
            # 后续所有存在性检查改用 _check_remote()（基于 PROPFIND）
            "disable_check": True,
        }
        if proxy_url:
            options["proxy_hostname"] = proxy_url

        self.client = Client(options)
        self.remote_root = remote_path.strip("/")  # e.g. "arxiv-daily-researcher"
        self._project_root = Path(__file__).resolve().parent.parent.parent

        # 用于直接 HTTP 请求的 session（绕过 webdavclient3 的 HEAD check）
        self._http = requests.Session()
        if proxy_url:
            self._http.proxies = {"http": proxy_url, "https": proxy_url}
        self._http.auth = HTTPBasicAuth(username, password)
        self._base_url = url.rstrip("/")

    def _remote(self, rel_path: str) -> str:
        """将相对路径拼接到 remote_root 下，返回完整远程路径。"""
        rel = rel_path.strip("/")
        if self.remote_root:
            return f"{self.remote_root}/{rel}" if rel else self.remote_root
        return rel

    def _url(self, remote_path: str) -> str:
        """构建完整的 WebDAV URL。"""
        path = remote_path.strip("/")
        return f"{self._base_url}/{path}" if path else self._base_url

    def _check_remote(self, remote_path: str) -> bool:
        """
        使用 PROPFIND (Depth 0) 检查远程资源是否存在。

        坚果云等服务器不支持 HEAD，但完整支持 PROPFIND。
        """
        url = self._url(remote_path)
        try:
            resp = self._http.request("PROPFIND", url, headers={"Depth": "0"})
            return resp.status_code == 207
        except Exception as e:
            logger.debug(f"PROPFIND 检查失败 {url}: {e}")
            return False

    def test_connection(self) -> bool:
        """测试 WebDAV 连接是否正常，并验证对目标目录的访问权限。"""
        try:
            remote = self._remote("")
            # 使用 PROPFIND 检查目标目录是否存在（支持坚果云等不支持 HEAD 的服务器）
            if not self._check_remote(remote):
                # 如果不存在，尝试创建（以此验证凭据和写入权限）
                self._ensure_remote_dir(remote + "/")
            return True
        except Exception as e:
            logger.error(f"WebDAV 连接测试失败: {e}")
            return False

    def upload_configs(self) -> Dict[str, bool]:
        """
        上传配置文件到 WebDAV。

        上传: configs/config.json
        不上传: .env（安全考虑）

        返回:
            Dict[str, bool]: 各文件上传结果
        """
        results = {}

        # 尝试多个可能路径（本地 vs Docker 卷挂载）
        config_path = None
        for candidate in [
            self._project_root / "configs" / "config.json",
            Path("/app/configs/config.json"),
        ]:
            if candidate.exists():
                config_path = candidate
                break

        if config_path:
            try:
                remote_file = self._remote("configs/config.json")
                self._ensure_remote_dir(self._remote("configs") + "/")
                self.client.upload_file(remote_file, str(config_path))
                results["configs/config.json"] = True
                logger.info("已上传 configs/config.json")
            except Exception as e:
                results["configs/config.json"] = False
                logger.error(f"上传 configs/config.json 失败: {e}")
        else:
            results["configs/config.json"] = False
            logger.warning("configs/config.json 不存在，跳过")

        return results

    def upload_data(self, include_reports: bool = False) -> Dict[str, bool]:
        """
        上传数据文件到 WebDAV。

        上传: data/history/, data/keywords/
        可选: data/reports/

        参数:
            include_reports: 是否包含报告文件

        返回:
            Dict[str, bool]: 各目录上传结果
        """
        results = {}
        data_dir = self._project_root / "data"

        # 上传 history 目录
        history_dir = data_dir / "history"
        if history_dir.exists() and any(history_dir.iterdir()):
            results["data/history/"] = self._upload_directory(
                history_dir, self._remote("data/history") + "/"
            )
        else:
            logger.info("data/history/ 为空或不存在，跳过")
            results["data/history/"] = True  # 空目录不算失败

        # 上传 keywords 目录
        keywords_dir = data_dir / "keywords"
        if keywords_dir.exists() and any(keywords_dir.iterdir()):
            results["data/keywords/"] = self._upload_directory(
                keywords_dir, self._remote("data/keywords") + "/"
            )
        else:
            logger.info("data/keywords/ 为空或不存在，跳过")
            results["data/keywords/"] = True

        # 可选：上传报告
        if include_reports:
            reports_dir = data_dir / "reports"
            if reports_dir.exists() and any(reports_dir.iterdir()):
                results["data/reports/"] = self._upload_directory(
                    reports_dir, self._remote("data/reports") + "/"
                )
            else:
                results["data/reports/"] = True

        return results

    def download_configs(self) -> Dict[str, bool]:
        """
        从 WebDAV 下载配置文件恢复到本地。

        返回:
            Dict[str, bool]: 各文件下载结果
        """
        results = {}
        config_path = self._project_root / "configs" / "config.json"
        remote_file = self._remote("configs/config.json")

        try:
            if self._check_remote(remote_file):
                config_path.parent.mkdir(parents=True, exist_ok=True)
                self.client.download_file(remote_file, str(config_path))
                results["configs/config.json"] = True
                logger.info("已下载 configs/config.json")
            else:
                results["configs/config.json"] = False
                logger.warning("远程 configs/config.json 不存在")
        except Exception as e:
            results["configs/config.json"] = False
            logger.error(f"下载 configs/config.json 失败: {e}")

        return results

    def download_data(self, include_reports: bool = False) -> Dict[str, bool]:
        """
        从 WebDAV 下载数据文件到本地。

        使用 pull() 增量下载，不会删除本地已有文件。

        返回:
            Dict[str, bool]: 各目录下载结果
        """
        results = {}
        data_dir = self._project_root / "data"

        dirs_to_download = ["history", "keywords"]
        if include_reports:
            dirs_to_download.append("reports")

        for subdir in dirs_to_download:
            remote_dir = self._remote(f"data/{subdir}") + "/"
            local_dir = data_dir / subdir
            try:
                if self._check_remote(remote_dir.rstrip("/")):
                    local_dir.mkdir(parents=True, exist_ok=True)
                    # 使用 pull() 做增量同步，不删除本地已有文件
                    self.client.pull(remote_dir, str(local_dir))
                    results[f"data/{subdir}/"] = True
                    logger.info(f"已下载 data/{subdir}/")
                else:
                    logger.info(f"远程 data/{subdir}/ 不存在，跳过")
                    results[f"data/{subdir}/"] = True  # 远程不存在不算失败
            except Exception as e:
                results[f"data/{subdir}/"] = False
                logger.error(f"下载 data/{subdir}/ 失败: {e}")

        return results

    def sync_all(self, direction: str = "upload", include_reports: bool = False) -> Dict:
        """
        执行完整同步。

        参数:
            direction: "upload" 或 "download"
            include_reports: 是否包含报告

        返回:
            dict: 同步结果摘要
        """
        start = time.time()
        results = {}

        if direction == "upload":
            results.update(self.upload_configs())
            results.update(self.upload_data(include_reports=include_reports))
        elif direction == "download":
            results.update(self.download_configs())
            results.update(self.download_data(include_reports=include_reports))

        elapsed = time.time() - start
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        summary = {
            "direction": direction,
            "results": results,
            "success": success_count,
            "total": total_count,
            "elapsed_seconds": round(elapsed, 1),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        logger.info(
            f"WebDAV {direction} 完成: {success_count}/{total_count} 成功，"
            f"耗时 {elapsed:.1f}s"
        )
        return summary

    def _ensure_remote_dir(self, remote_dir: str):
        """确保远程目录存在，不存在则递归创建。"""
        parts = remote_dir.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            try:
                if not self._check_remote(current):
                    self.client.mkdir(current + "/")
                    logger.debug(f"已创建远程目录: {current}/")
            except Exception:
                try:
                    self.client.mkdir(current + "/")
                except Exception:
                    pass  # 目录可能已存在

    def _upload_directory(self, local_dir: Path, remote_dir: str) -> bool:
        """逐文件上传本地目录到远程（不使用 upload_directory 避免删除远程已有文件）。"""
        try:
            self._ensure_remote_dir(remote_dir)
            file_count = 0
            for item in local_dir.rglob("*"):
                if item.is_file():
                    relative = item.relative_to(local_dir)
                    # 统一使用 / 分隔符
                    rel_posix = str(relative).replace("\\", "/")
                    remote_file = f"{remote_dir.rstrip('/')}/{rel_posix}"
                    # 确保父目录存在
                    parent_parts = rel_posix.rsplit("/", 1)
                    if len(parent_parts) > 1:
                        parent_remote = f"{remote_dir.rstrip('/')}/{parent_parts[0]}/"
                        self._ensure_remote_dir(parent_remote)
                    self.client.upload_file(remote_file, str(item))
                    file_count += 1
            logger.info(f"已上传目录 {local_dir.name}/ ({file_count} 个文件)")
            return True
        except Exception as e:
            logger.error(f"上传目录 {local_dir.name}/ 失败: {e}")
            return False


def create_sync_client(
    url: str = "",
    username: str = "",
    password: str = "",
    remote_path: str = "",
) -> Optional[WebDAVSync]:
    """
    创建 WebDAVSync 实例。

    优先使用传入的参数（用于 WebUI 面板直接传值），
    参数为空时回退到 config.settings。

    返回:
        WebDAVSync 实例，配置不完整时返回 None
    """
    try:
        from config import settings

        # 如果未传入参数，从 settings 读取
        if not url:
            url = getattr(settings, "WEBDAV_URL", "")
        if not username:
            username = getattr(settings, "WEBDAV_USERNAME", "")
        if not password:
            password = getattr(settings, "WEBDAV_PASSWORD", "")
        if not remote_path:
            remote_path = getattr(settings, "WEBDAV_REMOTE_PATH", "/arxiv-daily-researcher/")

        if not url or not username:
            logger.warning("WebDAV URL 或用户名未配置")
            return None

        # 获取代理配置
        proxy_url = ""
        if getattr(settings, "PROXY_ENABLED", False) and getattr(settings, "PROXY_URL", ""):
            proxy_url = settings.PROXY_URL

        return WebDAVSync(
            url=url,
            username=username,
            password=password,
            remote_path=remote_path,
            proxy_url=proxy_url,
        )
    except Exception as e:
        logger.error(f"创建 WebDAV 客户端失败: {e}")
        return None


def sync_after_report(logger_instance=None):
    """
    报告生成后的同步钩子。
    仅在 sync_mode 为 'after_report' 时执行。
    """
    try:
        from config import settings

        if not getattr(settings, "WEBDAV_ENABLED", False):
            return

        sync_mode = getattr(settings, "WEBDAV_SYNC_MODE", "manual")
        if sync_mode != "after_report":
            return

        log = logger_instance or logger

        client = create_sync_client()
        if not client:
            return

        include_reports = getattr(settings, "WEBDAV_SYNC_REPORTS", False)
        log.info("[WebDAV] 报告后自动同步开始...")
        result = client.sync_all(direction="upload", include_reports=include_reports)
        log.info(
            f"[WebDAV] 同步完成: {result['success']}/{result['total']} 成功，"
            f"耗时 {result['elapsed_seconds']}s"
        )
    except Exception as e:
        if logger_instance:
            logger_instance.warning(f"[WebDAV] 报告后同步失败: {e}")
        else:
            logger.warning(f"[WebDAV] 报告后同步失败: {e}")
