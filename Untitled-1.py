import atexit
import json
import os
import shutil
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from yt_dlp import YoutubeDL # type: ignore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HAS_FFMPEG = shutil.which("ffmpeg") is not None

# Diretório temporário por instância do servidor — apagado automaticamente ao encerrar
TEMP_DIR = tempfile.mkdtemp(prefix="ytdl_")
TEMP_DIR_ABS = os.path.abspath(TEMP_DIR)
atexit.register(lambda: shutil.rmtree(TEMP_DIR, ignore_errors=True))

urls: list[dict] = []
messages: list[str] = []
completed: list[dict] = []  # {"filename": str, "fmt": str, "seq": int}
completed_seq: int = 0

state_lock = threading.Lock()
download_thread: threading.Thread | None = None

ALLOWED_FORMATS = {"mp3", "mp4", "mkv", "avi", "mov", "wmv"}
MAX_MESSAGES = 500


def log(msg: str) -> None:
    with state_lock:
        messages.append(msg)
        if len(messages) > MAX_MESSAGES:
            del messages[:100]


def add_completed(filename: str, fmt: str) -> None:
    global completed_seq
    with state_lock:
        completed_seq += 1
        completed.append({"filename": filename, "fmt": fmt, "seq": completed_seq})
        if len(completed) > 100:
            del completed[:50]


class DownloadTracker:
    """Captura o caminho final do arquivo após yt-dlp (inclusive pós-processadores)."""

    def __init__(self) -> None:
        self.final_path: str | None = None

    def progress_hook(self, d: dict) -> None:
        if d.get("status") == "finished":
            self.final_path = d.get("filename")

    def pp_hook(self, d: dict) -> None:
        if d.get("status") == "finished":
            fp = d.get("info_dict", {}).get("filepath")
            if fp:
                self.final_path = fp


# cookies_source.txt é montado como read-only pelo Docker
# O código copia para TEMP_DIR antes de cada download para yt-dlp poder escrever
COOKIES_SOURCE = os.path.join(BASE_DIR, "cookies_source.txt")
COOKIES_FILE = os.path.join(TEMP_DIR, "cookies.txt")


def get_ydl_options(fmt: str, tracker: DownloadTracker) -> dict:
    base = {
        "noplaylist": True,
        "outtmpl": os.path.join(TEMP_DIR, "%(title)s.%(ext)s"),
        "progress_hooks": [tracker.progress_hook],
        "postprocessor_hooks": [tracker.pp_hook],
        # Robustez
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        },
    }

    # Copia os cookies originais para o temp a cada download (evita sobrescrita pelo yt-dlp)
    if os.path.isfile(COOKIES_SOURCE):
        shutil.copy2(COOKIES_SOURCE, COOKIES_FILE)

    if os.path.isfile(COOKIES_FILE):
        base["cookiefile"] = COOKIES_FILE

    if not HAS_FFMPEG:
        if fmt != "mp4":
            raise RuntimeError(
                f"ffmpeg não encontrado. O formato {fmt.upper()} requer ffmpeg para conversão. "
                "Instale o ffmpeg ou escolha MP4."
            )
        return {**base, "format": "best"}

    if fmt == "mp3":
        return {
            **base,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

    # merge_output_format só suporta mp4/mkv/webm/flv/ogg.
    # Para avi/mov/wmv usamos mkv como container intermediário e ffmpeg converte no final.
    merge_fmt = fmt if fmt in ("mp4", "mkv", "webm", "flv") else "mkv"

    video_format = (
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
        "/bestvideo+bestaudio"
        "/best[ext=mp4]"
        "/best"
    )
    opts = {
        **base,
        "format": video_format,
        "merge_output_format": merge_fmt,
    }
    # Só adiciona o convertor quando o formato final difere do container de merge
    if fmt != merge_fmt:
        opts["postprocessors"] = [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": fmt,
        }]
    return opts


def download_worker() -> None:
    global download_thread
    while True:
        with state_lock:
            if not urls:
                download_thread = None
                return
            item = urls.pop(0)

        url = item["url"]
        fmt = item["fmt"]
        log(f"Iniciando download [{fmt.upper()}]: {url}")
        tracker = DownloadTracker()
        try:
            with YoutubeDL(get_ydl_options(fmt, tracker)) as ydl:
                ydl.download([url])
        except Exception as exc:
            log(f"Erro ao baixar {url}: {exc}")
        else:
            filename = os.path.basename(tracker.final_path) if tracker.final_path else None
            if filename:
                add_completed(filename, fmt)
            log(f"Download concluído [{fmt.upper()}]: {url}")


def start_download_thread() -> None:
    global download_thread
    if download_thread is None:
        download_thread = threading.Thread(target=download_worker, daemon=True)
        download_thread.start()


def escape_html(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))


def build_html() -> str:
    with state_lock:
        queue_items = "".join(
            f"<li><span class='fmt-badge'>{escape_html(item['fmt'].upper())}</span> {escape_html(item['url'])}</li>"
            for item in urls
        )
        recent_messages = list(messages[-20:])
        running = download_thread is not None
        msg_count = len(messages)
        init_seq = completed[-1]["seq"] if completed else 0

    message_items = "".join(f"<li>{escape_html(msg)}</li>" for msg in recent_messages)
    ffmpeg_warning = "" if HAS_FFMPEG else (
        "<div class='warn'>Aviso: ffmpeg não encontrado. Apenas MP4 está disponível.</div>"
    )
    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Downloader YouTube</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; max-width: 960px; background: #f3f6fb; color: #1a1a1a; }}
        header {{ margin-bottom: 24px; }}
        .card {{ background: white; border-radius: 16px; padding: 22px; box-shadow: 0 18px 40px rgba(0,0,0,.08); margin-bottom: 20px; }}
        .form-row {{ display: flex; gap: 10px; align-items: flex-end; margin-top: 8px; }}
        .form-row input[type=text] {{ flex: 1; padding: 12px 14px; border-radius: 10px; border: 1px solid #d5dce9; box-sizing: border-box; }}
        .form-row select {{ padding: 12px 14px; border-radius: 10px; border: 1px solid #d5dce9; background: white; font-size: 1rem; cursor: pointer; min-width: 100px; }}
        .form-row input[type=submit] {{ padding: 12px 20px; border-radius: 10px; border: none; background: #2563eb; color: white; font-weight: 600; cursor: pointer; white-space: nowrap; }}
        .form-row input[type=submit]:hover {{ background: #1d4ed8; }}
        label {{ font-weight: 600; display: block; margin-bottom: 4px; }}
        .label-row {{ display: flex; gap: 10px; }}
        .label-row label {{ flex: 1; }}
        .label-row .label-fmt {{ min-width: 100px; }}
        h1 {{ margin-bottom: 8px; }}
        h2 {{ margin-top: 0; }}
        ol {{ padding-left: 20px; margin: 10px 0; }}
        .small {{ color: #6b7280; font-size: 0.95rem; }}
        .warn {{ background: #fef9c3; border: 1px solid #fde047; border-radius: 10px; padding: 10px 14px; margin-bottom: 14px; color: #854d0e; font-size: 0.95rem; }}
        .status-chip {{ display: inline-block; padding: 6px 12px; border-radius: 999px; background: #e0f2fe; color: #0369a1; font-weight: 600; margin-bottom: 14px; }}
        .fmt-badge {{ display: inline-block; padding: 2px 8px; border-radius: 6px; background: #dbeafe; color: #1d4ed8; font-size: 0.78rem; font-weight: 700; margin-right: 6px; vertical-align: middle; }}
        #toast-container {{ position: fixed; right: 20px; top: 20px; width: 320px; z-index: 1000; }}
        .toast {{ background: #0d9488; color: #fff; padding: 14px 16px; border-radius: 12px; box-shadow: 0 10px 30px rgba(15,23,42,.15); margin-top: 12px; opacity: 0; transform: translateX(20px); transition: opacity .3s ease, transform .3s ease; }}
        .toast.show {{ opacity: 1; transform: translateX(0); }}
        .toast.error {{ background: #dc2626; }}
    </style>
</head>
<body>
    <header>
        <h1>Downloader YouTube</h1>
        <p class="small">Cole uma URL, escolha o formato e ela será enviada diretamente para o seu navegador.</p>
    </header>
    <div class="card">
        {ffmpeg_warning}
        <form method="post" action="/">
            <div class="label-row">
                <label for="url">URL do YouTube</label>
                <label class="label-fmt" for="fmt">Formato</label>
            </div>
            <div class="form-row">
                <input type="text" id="url" name="url" placeholder="https://www.youtube.com/watch?v=..." required />
                <select id="fmt" name="fmt">
                    <option value="mp3">MP3</option>
                    <option value="mp4" selected>MP4</option>
                    <option value="mkv">MKV</option>
                    <option value="avi">AVI</option>
                    <option value="mov">MOV</option>
                    <option value="wmv">WMV</option>
                </select>
                <input type="submit" value="Adicionar à fila" />
            </div>
        </form>
    </div>
    <div class="card">
        <h2>Fila de downloads</h2>
        <span class="status-chip">{"Em execução" if running else "Aguardando novos URLs"}</span>
        <ol id="queue-list">{queue_items}</ol>
    </div>
    <div class="card">
        <h2>Mensagens recentes</h2>
        <ol id="message-list">{message_items}</ol>
    </div>
    <div id="toast-container"></div>
    <script>
        let lastMessageCount = {msg_count};
        let lastCompletedSeq = {init_seq};

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function createToast(message, isError = false) {{
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast' + (isError ? ' error' : '');
            toast.innerHTML = escapeHtml(message);
            container.appendChild(toast);
            requestAnimationFrame(() => toast.classList.add('show'));
            setTimeout(() => toast.classList.remove('show'), 5000);
            setTimeout(() => container.removeChild(toast), 5600);
        }}

        function triggerBrowserDownload(filename) {{
            const a = document.createElement('a');
            a.href = '/download/' + encodeURIComponent(filename);
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => document.body.removeChild(a), 200);
        }}

        function updateStatus(data) {{
            const queueList = document.getElementById('queue-list');
            const messageList = document.getElementById('message-list');
            const statusChip = document.querySelector('.status-chip');

            queueList.innerHTML = data.urls.map(item =>
                `<li><span class="fmt-badge">${{escapeHtml(item.fmt.toUpperCase())}}</span> ${{escapeHtml(item.url)}}</li>`
            ).join('');
            messageList.innerHTML = data.messages.map(msg => `<li>${{escapeHtml(msg)}}</li>`).join('');
            statusChip.textContent = data.running ? 'Em execução' : 'Aguardando novos URLs';

            if (data.total_messages > lastMessageCount) {{
                const newMsgs = data.messages.slice(data.messages.length - (data.total_messages - lastMessageCount));
                for (const msg of newMsgs) {{
                    if (msg.startsWith('Download concluído')) createToast(msg);
                    else if (msg.startsWith('Erro')) createToast(msg, true);
                }}
                lastMessageCount = data.total_messages;
            }}

            if (data.completed) {{
                for (const item of data.completed) {{
                    if (item.seq > lastCompletedSeq) {{
                        lastCompletedSeq = item.seq;
                        triggerBrowserDownload(item.filename);
                    }}
                }}
            }}
        }}

        async function fetchStatus() {{
            try {{
                const response = await fetch('/status');
                if (!response.ok) return;
                const data = await response.json();
                updateStatus(data);
            }} catch (error) {{
                console.warn('Erro ao atualizar status:', error);
            }}
        }}

        setInterval(fetchStatus, 3000);
        fetchStatus();
    </script>
</body>
</html>
"""


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/status":
            with state_lock:
                data = {
                    "urls": [{"url": item["url"], "fmt": item["fmt"]} for item in urls],
                    "messages": messages[-20:],
                    "total_messages": len(messages),
                    "running": download_thread is not None,
                    "completed": list(completed),
                }
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path.startswith("/download/"):
            raw = self.path[len("/download/"):]
            filename = urllib.parse.unquote(raw)
            filepath = os.path.abspath(os.path.join(TEMP_DIR, filename))
            if not filepath.startswith(TEMP_DIR_ABS + os.sep):
                self.send_error(403)
                return
            if not os.path.isfile(filepath):
                self.send_error(404)
                return
            encoded_name = urllib.parse.quote(filename)
            size = os.path.getsize(filepath)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{encoded_name}",
            )
            self.send_header("Content-Length", str(size))
            self.end_headers()
            try:
                with open(filepath, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                # Apaga o arquivo após enviar — servidor não acumula arquivos
                try:
                    os.unlink(filepath)
                except OSError:
                    pass
            return

        if self.path != "/":
            self.send_error(404)
            return

        content = build_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        content_length = max(0, int(self.headers.get("Content-Length", 0)))
        body = self.rfile.read(content_length).decode("utf-8")
        data = urllib.parse.parse_qs(body)
        url = data.get("url", [""])[0].strip()
        fmt = data.get("fmt", ["mp4"])[0].strip().lower()

        if fmt not in ALLOWED_FORMATS:
            fmt = "mp4"

        if url:
            if not url.startswith(("http://", "https://")):
                log(f"URL rejeitada (deve começar com http:// ou https://): {url}")
            else:
                with state_lock:
                    urls.append({"url": url, "fmt": fmt})
                    start_download_thread()
                log(f"URL adicionada à fila [{fmt.upper()}]: {url}")

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def run_server() -> None:
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("", port), SimpleHandler)
    print(f"Acesse http://localhost:{port} no navegador e cole a URL para adicionar à fila.")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
