"""
MinerU PDF 云端解析模块。

通过 MinerU API 将 PDF URL 提交到云端解析，获取高质量的文本提取结果。
支持 Token 过期检测、每日额度耗尽检测，失败时自动降级到 PyMuPDF 本地解析。

API 文档: https://mineru.net/apiManage/docs
"""

import io
import os
import time
import logging
import zipfile
import requests
from urllib.parse import urlparse
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

DEFAULT_MINERU_BASE_URL = "https://mineru.net/api/v4"

# MinerU API 错误码 → 是否应降级到 PyMuPDF（True = 降级，False = 可重试）
MINERU_ERROR_CODES = {
    "A0202": ("Token 错误，请检查 MINERU_API_KEY 是否正确", True),
    "A0211": (
        "Token 已过期（有效期 3 个月），请到 https://mineru.net/apiManage/apiKey 重新申请",
        True,
    ),
    "-60018": ("MinerU 每日解析任务数量已达上限，明日重置", True),
    "-60019": ("MinerU HTML 解析额度不足", True),
    "-60007": ("MinerU 模型服务暂时不可用", False),
    "-60009": ("MinerU 任务提交队列已满", False),
    "-60008": ("文件读取超时，请检查 PDF URL 是否可访问", False),
    "-60005": ("文件大小超出 200MB 限制", True),
    "-60006": ("文件页数超过 600 页限制", True),
    "-500": ("MinerU 传参错误", True),
    "-10001": ("MinerU 服务异常", False),
    "-10002": ("MinerU 请求参数错误", True),
}


def _normalize_mineru_base_url(base_url: str) -> str:
    """Accept either the API root or the Swagger docs URL."""
    normalized = (base_url or DEFAULT_MINERU_BASE_URL).split("#", 1)[0].rstrip("/")
    if normalized.endswith("/docs"):
        normalized = normalized[: -len("/docs")]
    return normalized.rstrip("/")


def _should_force_official_mineru() -> bool:
    """GitHub-hosted runners cannot reach private LAN MinerU services."""
    allow_local = os.environ.get("MINERU_ALLOW_LOCAL_IN_CI", "").lower() in {"1", "true", "yes"}
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true" and not allow_local


class MineruParser:
    """
    MinerU 云端 PDF 解析器。

    工作流程:
    1. 提交 PDF URL 到 MinerU API 创建解析任务
    2. 轮询任务状态直到完成
    3. 下载解析结果 ZIP 并提取 Markdown 文本
    4. 任何环节失败时返回 None，由调用方决定是否降级

    属性:
        api_key: MinerU API Token
        model_version: 模型版本 (pipeline / vlm)
        poll_interval: 轮询间隔（秒）
        poll_timeout: 超时时间（秒）
        _available: 标记本次运行中 MinerU 是否可用（避免重复失败）
    """

    DEFAULT_BASE_URL = DEFAULT_MINERU_BASE_URL

    def __init__(self):
        self.api_key = settings.MINERU_API_KEY
        self.base_url = _normalize_mineru_base_url(
            getattr(settings, "MINERU_BASE_URL", self.DEFAULT_BASE_URL)
        )
        self.api_mode = getattr(settings, "MINERU_API_MODE", "auto").lower()
        if _should_force_official_mineru():
            self.base_url = self.DEFAULT_BASE_URL
            self.api_mode = "official"
        self.model_version = settings.MINERU_MODEL_VERSION
        self.poll_interval = settings.MINERU_POLL_INTERVAL
        self.poll_timeout = settings.MINERU_POLL_TIMEOUT
        self._available = True  # 本次运行内的可用性标记

    def _is_local_api(self) -> bool:
        """判断当前配置是否使用本地 MinerU FastAPI 协议。"""
        if self.api_mode == "local":
            return True
        if self.api_mode == "official":
            return False
        return "mineru.net/api/v4" not in self.base_url

    def _get_headers(self) -> dict:
        """构建 MinerU API 请求头。"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def is_configured(self) -> bool:
        """检查 MinerU API 是否已配置。"""
        if self._is_local_api():
            return bool(self.base_url)
        return bool(self.api_key)

    def is_available(self) -> bool:
        """
        检查 MinerU 是否可用（已配置且本次运行中未被标记为不可用）。

        当 Token 过期、额度耗尽等不可恢复的错误发生时，_available 会被设为 False，
        后续同一次运行中的所有论文将直接跳过 MinerU，避免重复请求浪费时间。
        """
        return self.is_configured() and self._available

    def _mark_unavailable(self, reason: str, error_code: str = ""):
        """标记 MinerU 在本次运行中不可用，并发送错误告警通知。"""
        self._available = False
        logger.warning(f"MinerU 已标记为不可用（本次运行），原因: {reason}")
        logger.warning("后续论文将自动使用 PyMuPDF 本地解析")
        self._send_error_notification(reason, error_code)

    def _send_error_notification(self, reason: str, error_code: str = ""):
        """通过通知系统发送 MinerU 错误告警。"""
        try:
            if not settings.ENABLE_NOTIFICATIONS:
                return
            from notifications.notifier import NotifierAgent

            notifier = NotifierAgent()

            suggestion_map = {
                "A0211": "请到 https://mineru.net/apiManage/apiKey 重新申请 Token 并更新 .env",
                "A0202": "请检查 .env 中 MINERU_API_KEY 是否填写正确",
                "-60018": "每日额度已耗尽，明日自动重置；或临时切换 pdf_parser.mode 为 pymupdf",
                "-60019": "HTML 解析额度不足，请联系 MinerU 客服或升级套餐",
                "-60005": "PDF 文件超过 200MB 限制，建议使用 pymupdf 本地解析",
                "-60006": "PDF 页数超过 600 页限制，建议使用 pymupdf 本地解析",
            }
            suggestion = suggestion_map.get(
                error_code, "请检查网络连接和 MinerU API 配置，或切换 pdf_parser.mode 为 pymupdf"
            )

            notifier.notify_error(
                "error_mineru",
                error_code=error_code or "N/A",
                error_detail=reason,
                suggestion=suggestion,
            )
        except Exception as e:
            logger.debug(f"MinerU 错误告警发送失败: {e}")

    def _submit_task(self, pdf_url: str) -> Optional[str]:
        """
        提交 PDF 解析任务。

        参数:
            pdf_url: PDF 文件的 URL 地址

        返回:
            task_id 或 None（失败时）
        """
        url = f"{self.base_url}/extract/task"
        data = {
            "url": pdf_url,
            "model_version": self.model_version,
            "enable_formula": False,  # 学术论文场景下关闭公式识别以节省额度
            "enable_table": True,
        }

        try:
            resp = requests.post(url, headers=self._get_headers(), json=data, timeout=30)

            # HTTP 层面的错误
            if resp.status_code == 401 or resp.status_code == 403:
                self._mark_unavailable("API 认证失败，Token 可能错误或已过期", "A0202")
                return None

            result = resp.json()
            code = str(result.get("code", ""))

            if code == "0":
                task_id = result.get("data", {}).get("task_id")
                logger.info(f"MinerU 任务已提交: task_id={task_id}")
                return task_id

            # 处理已知错误码
            if code in MINERU_ERROR_CODES:
                msg, should_degrade = MINERU_ERROR_CODES[code]
                logger.error(f"MinerU 任务提交失败: {msg} (错误码: {code})")
                if should_degrade:
                    self._mark_unavailable(msg, code)
                return None

            # 未知错误码
            msg = result.get("msg", "未知错误")
            logger.error(f"MinerU 任务提交失败: {msg} (错误码: {code})")
            return None

        except requests.exceptions.Timeout:
            logger.error("MinerU API 请求超时")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("MinerU API 连接失败，请检查网络")
            self._mark_unavailable("网络连接失败", "NETWORK")
            return None
        except Exception as e:
            logger.error(f"MinerU 任务提交异常: {e}")
            return None

    def _poll_task(self, task_id: str) -> Optional[str]:
        """
        轮询任务状态，等待完成后返回结果 ZIP 下载 URL。

        参数:
            task_id: 任务 ID

        返回:
            full_zip_url 或 None（失败/超时时）
        """
        url = f"{self.base_url}/extract/task/{task_id}"
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.poll_timeout:
                logger.error(f"MinerU 任务超时（{self.poll_timeout}s）: task_id={task_id}")
                return None

            try:
                resp = requests.get(url, headers=self._get_headers(), timeout=30)
                result = resp.json()

                code = str(result.get("code", ""))
                if code != "0":
                    # 轮询过程中出现错误码
                    if code in MINERU_ERROR_CODES:
                        msg, should_degrade = MINERU_ERROR_CODES[code]
                        logger.error(f"MinerU 任务查询失败: {msg}")
                        if should_degrade:
                            self._mark_unavailable(msg, code)
                    return None

                data = result.get("data", {})
                state = data.get("state", "")

                if state == "done":
                    zip_url = data.get("full_zip_url", "")
                    if zip_url:
                        logger.info(f"MinerU 任务完成: task_id={task_id}")
                        return zip_url
                    logger.error("MinerU 任务完成但未返回 ZIP URL")
                    return None

                elif state == "failed":
                    err_msg = data.get("err_msg", "未知原因")
                    logger.error(f"MinerU 解析失败: {err_msg}")
                    return None

                elif state in ("pending", "running", "converting"):
                    # 显示进度信息
                    progress = data.get("extract_progress", {})
                    if progress:
                        extracted = progress.get("extracted_pages", 0)
                        total = progress.get("total_pages", 0)
                        logger.debug(f"MinerU 解析中: {extracted}/{total} 页 (task_id={task_id})")

                    time.sleep(self.poll_interval)
                else:
                    logger.warning(f"MinerU 未知任务状态: {state}")
                    time.sleep(self.poll_interval)

            except requests.exceptions.Timeout:
                logger.warning("MinerU 任务状态查询超时，重试中...")
                time.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"MinerU 任务状态查询异常: {e}")
                return None

    def _download_and_extract_text(self, zip_url: str) -> Optional[str]:
        """
        下载解析结果 ZIP 并提取 Markdown 文本内容。

        MinerU 返回的 ZIP 中包含 .md 文件（Markdown 格式的解析结果）。

        参数:
            zip_url: ZIP 下载 URL

        返回:
            提取的文本内容 或 None
        """
        try:
            resp = requests.get(zip_url, timeout=60)
            resp.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                # 查找 .md 文件（MinerU 默认输出 Markdown）
                md_files = [f for f in zf.namelist() if f.endswith(".md")]

                if not md_files:
                    # 回退到任何文本文件
                    txt_files = [f for f in zf.namelist() if f.endswith((".txt", ".json"))]
                    if not txt_files:
                        logger.error(f"MinerU ZIP 中未找到文本文件，包含: {zf.namelist()}")
                        return None
                    target_file = txt_files[0]
                else:
                    target_file = md_files[0]

                text = zf.read(target_file).decode("utf-8", errors="replace")
                logger.info(f"MinerU 文本提取成功: {len(text)} 字符 (from {target_file})")
                return text

        except zipfile.BadZipFile:
            logger.error("MinerU 返回的不是有效的 ZIP 文件")
            return None
        except Exception as e:
            logger.error(f"MinerU 结果下载/提取失败: {e}")
            return None

    def _local_backend(self) -> str:
        """把官方模型名映射到本地 FastAPI 的 backend 名称。"""
        backend = (self.model_version or "pipeline").strip().lower()
        if backend in {
            "pipeline",
            "vlm-engine",
            "hybrid-engine",
            "vlm-http-client",
            "hybrid-http-client",
        }:
            return backend
        if backend == "vlm":
            return "vlm-engine"
        return "pipeline"

    def _pdf_filename(self, pdf_url: str) -> str:
        """从 PDF URL 中取上传文件名。"""
        name = urlparse(pdf_url).path.rsplit("/", 1)[-1]
        return name if name.endswith(".pdf") else "paper.pdf"

    def _extract_local_markdown(self, result: dict) -> Optional[str]:
        """从本地 MinerU JSON 响应中提取第一个 Markdown 内容。"""
        if isinstance(result.get("md_content"), str):
            return result["md_content"]

        results = result.get("results")
        if isinstance(results, dict):
            for item in results.values():
                if isinstance(item, dict) and isinstance(item.get("md_content"), str):
                    return item["md_content"]

        logger.error(f"本地 MinerU 响应中未找到 md_content: {result.keys()}")
        return None

    def _parse_pdf_local(self, pdf_url: str) -> Optional[str]:
        """
        使用本地 MinerU FastAPI 服务解析 PDF。

        本地服务不支持官方的 URL task 协议，因此先下载 PDF，再上传到 /file_parse。
        """
        try:
            pdf_resp = requests.get(pdf_url, timeout=60)
            pdf_resp.raise_for_status()

            filename = self._pdf_filename(pdf_url)
            files = {
                "files": (
                    filename,
                    io.BytesIO(pdf_resp.content),
                    "application/pdf",
                )
            }
            data = {
                "backend": self._local_backend(),
                "parse_method": "auto",
                "formula_enable": "false",
                "table_enable": "true",
                "return_md": "true",
                "return_images": "false",
                "response_format_zip": "false",
            }
            resp = requests.post(
                f"{self.base_url}/file_parse",
                files=files,
                data=data,
                timeout=max(self.poll_timeout, 60),
            )
            resp.raise_for_status()
            return self._extract_local_markdown(resp.json())

        except requests.exceptions.Timeout:
            logger.error("本地 MinerU API 请求超时")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("本地 MinerU API 连接失败，请检查服务地址")
            self._mark_unavailable("本地 MinerU 网络连接失败", "NETWORK")
            return None
        except Exception as e:
            logger.error(f"本地 MinerU 解析异常: {e}")
            return None

    def parse_pdf(self, pdf_url: str) -> Optional[str]:
        """
        使用 MinerU API 解析 PDF 并返回文本内容。

        完整流程: 提交任务 → 轮询状态 → 下载结果 → 提取文本

        参数:
            pdf_url: PDF 文件的 URL 地址

        返回:
            解析出的文本内容，失败返回 None
        """
        if not self.is_available():
            return None

        logger.info(f"使用 MinerU 解析 PDF: {pdf_url}")

        if self._is_local_api():
            return self._parse_pdf_local(pdf_url)

        # 1. 提交任务
        task_id = self._submit_task(pdf_url)
        if not task_id:
            return None

        # 2. 轮询等待完成
        zip_url = self._poll_task(task_id)
        if not zip_url:
            return None

        # 3. 下载并提取文本
        return self._download_and_extract_text(zip_url)
