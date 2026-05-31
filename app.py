import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, HttpUrl

from doubao_parser.image import doubao_image_parse, qianwen_image_parse
from doubao_parser.video import doubao_video_parse, yunque_video_parse

app = FastAPI(title="豆包千问去水印 API", description="从豆包|千问对话链接中提取图片和视频资源", version="1.0.4")

if os.path.exists("icons"):
    app.mount("/icons", StaticFiles(directory="icons"), name="icons")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DouBaoRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"url": "https://www.doubao.com/thread/aef4c7a4c78c2", "return_raw": False}}
    )

    url: HttpUrl
    return_raw: bool = False


class DouBaoResponse(BaseModel):
    success: bool
    image_count: int
    images: list[dict]


class VideoRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"url": "https://www.doubao.com/video-sharing?share_id=xxx&video_id=xxx", "return_raw": False}
        }
    )

    url: HttpUrl
    return_raw: bool = False


class VideoResponse(BaseModel):
    success: bool
    video_count: int
    videos: list[dict]


class DownloadResource(BaseModel):
    url: HttpUrl
    filename: str | None = None
    type: str = "image"


class DownloadAllRequest(BaseModel):
    resources: list[DownloadResource]
    download_dir: str | None = None


class DownloadAllResponse(BaseModel):
    success: bool
    download_dir: str
    downloaded_count: int
    files: list[str]
    failed: list[dict]


class SelectDownloadDirResponse(BaseModel):
    success: bool
    download_dir: str


def _resolve_download_dir(download_dir: str | None) -> Path:
    target = (download_dir or "~/Downloads/doubao-nomark").strip() or "~/Downloads/doubao-nomark"
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _safe_filename(filename: str | None, url: str, index: int, resource_type: str) -> str:
    suffix = ".mp4" if resource_type == "video" else ".jpg"
    parsed_suffix = Path(urlparse(url).path).suffix
    if parsed_suffix and len(parsed_suffix) <= 8:
        suffix = parsed_suffix.split("?")[0]

    base = filename or f"doubao_{resource_type}_{index + 1}{suffix}"
    safe_name = "".join(char if char.isalnum() or char in "._- " else "_" for char in base).strip()
    if not safe_name:
        safe_name = f"doubao_{resource_type}_{index + 1}{suffix}"
    if not Path(safe_name).suffix:
        safe_name += suffix
    return safe_name


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


@app.get("/", summary="首页", include_in_schema=False)
async def root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {
        "message": "Doubao Parser - Extract images and videos from Doubao links",
        "docs": "/docs",
        "version": "1.0.4",
    }


@app.post("/parse", summary="解析豆包|千问对话图片")
async def parse_doubao(request: DouBaoRequest):
    try:
        if "doubao.com" in str(request.url):
            result = await doubao_image_parse(str(request.url), return_raw=request.return_raw)
        else:
            result = await qianwen_image_parse(str(request.url), return_raw=request.return_raw)

        if request.return_raw:
            return {"success": True, "data": result}

        return DouBaoResponse(success=True, image_count=len(result), images=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Exception: {e}")
        raise HTTPException(status_code=500, detail="图片解析失败，请检查链接是否正确")


@app.get("/parse", summary="解析豆包|千问对话图片(GET)")
async def parse_doubao_get(url: str, return_raw: bool = False):
    try:
        if "doubao.com" in url:
            result = await doubao_image_parse(url, return_raw=return_raw)
        else:
            result = await qianwen_image_parse(url, return_raw=return_raw)

        if return_raw:
            return {"success": True, "data": result}

        return DouBaoResponse(success=True, image_count=len(result), images=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Exception: {e}")
        raise HTTPException(status_code=500, detail="图片解析失败，请检查链接是否正确")


@app.post("/parse-video", summary="解析豆包|云雀视频")
async def parse_video(request: VideoRequest):
    try:
        url_str = str(request.url)
        if "doubao.com" in url_str:
            video_data = await doubao_video_parse(url_str, return_raw=request.return_raw)
        else:
            video_data = await yunque_video_parse(str(request.url), return_raw=request.return_raw)

        if request.return_raw:
            return {"success": True, "data": video_data}

        return VideoResponse(success=True, video_count=len(video_data), videos=video_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Exception: {e}")
        raise HTTPException(status_code=500, detail="视频解析失败，请检查链接是否正确")


@app.get("/parse-video", summary="解析豆包|云雀视频(GET)")
async def parse_video_get(url: str, return_raw: bool = False):
    try:
        if "doubao.com" in url:
            video_data = await doubao_video_parse(url, return_raw=return_raw)
        else:
            video_data = await yunque_video_parse(url, return_raw=return_raw)
        if return_raw:
            return {"success": True, "data": video_data}

        return VideoResponse(success=True, video_count=len(video_data), videos=video_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Exception: {e}")
        raise HTTPException(status_code=500, detail="视频解析失败，请检查链接是否正确")


@app.post("/download-all", response_model=DownloadAllResponse, summary="批量下载图片或视频到指定目录")
async def download_all(request: DownloadAllRequest):
    if not request.resources:
        raise HTTPException(status_code=400, detail="没有可下载的资源")

    download_dir = _resolve_download_dir(request.download_dir)
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36",
    }
    files = []
    failed = []

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        for index, resource in enumerate(request.resources):
            url = str(resource.url)
            resource_type = "video" if resource.type == "video" else "image"
            filename = _safe_filename(resource.filename, url, index, resource_type)
            file_path = _dedupe_path(download_dir / filename)

            try:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    with file_path.open("wb") as file:
                        async for chunk in response.aiter_bytes():
                            file.write(chunk)
                files.append(str(file_path))
            except Exception as e:
                if file_path.exists() and file_path.stat().st_size == 0:
                    file_path.unlink()
                failed.append({"url": url, "error": str(e)})

    return DownloadAllResponse(
        success=len(files) > 0 and not failed,
        download_dir=str(download_dir),
        downloaded_count=len(files),
        files=files,
        failed=failed,
    )


@app.get("/select-download-dir", response_model=SelectDownloadDirResponse, summary="选择下载目录")
async def select_download_dir():
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择下载路径")'],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("已取消选择文件夹")
            download_dir = result.stdout.strip()
        else:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            download_dir = filedialog.askdirectory(title="选择下载路径")
            root.destroy()
            if not download_dir:
                raise ValueError("已取消选择文件夹")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Exception: {e}")
        raise HTTPException(status_code=500, detail="无法打开文件夹选择器")

    return SelectDownloadDirResponse(success=True, download_dir=str(Path(download_dir).expanduser().resolve()))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
