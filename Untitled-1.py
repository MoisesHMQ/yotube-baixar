import json
import os
import shutil
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from yt_dlp import YoutubeDL # type: ignore

BASE_DIR = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "videos")

# Verificar se a pasta videos já existe
if os.path.exists(OUTPUT_DIR):
    if not os.path.isdir(OUTPUT_DIR):
        raise RuntimeError(f"'{OUTPUT_DIR}' existe mas não é uma pasta.")
else:
    os.makedirs(OUTPUT_DIR)

urls = []
messages = []
queue_lock = threading.Lock()
download_thread = None


def get_ydl_options() -> dict:
    has_ffmpeg = shutil.which("ffmpeg") is not None
    if has_ffmpeg:
        return {
            "noplaylist": True,
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
        }

    if not any(msg.startswith("Aviso: ffmpeg") for msg in messages):
        messages.append("Aviso: ffmpeg não encontrado. Será usado um único arquivo com áudio integrado.")
    return {
        "noplaylist": True,
        "format": "best[height<=1080]",
        "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
    }


def download_worker() -> None:
    global download_thread
    while True:
        with queue_lock:
            if not urls:
                download_thread = None
                return
            url = urls.pop(0)

        messages.append(f"Iniciando download: {url}")
        try:
            with YoutubeDL(get_ydl_options()) as ydl:
                ydl.download([url])
        except Exception as exc:
            messages.append(f"Erro ao baixar {url}: {exc}")
        else:
            messages.append(f"Download concluído: {url}")


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


def open_output_folder() -> None:
    if os.name == "nt":
        os.startfile(OUTPUT_DIR)
    elif os.name == "posix":
        os.system(f"xdg-open '{OUTPUT_DIR}'")
    else:
        raise RuntimeError("Não é possível abrir a pasta automaticamente neste sistema.")


def build_html() -> str:
    with queue_lock:
        queue_items = "".join(f"<li>{escape_html(url)}</li>" for url in urls)
    message_items = "".join(f"<li>{escape_html(msg)}</li>" for msg in messages[-20:])
    running = download_thread is not None
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
        input[type=text] {{ width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid #d5dce9; margin-top: 8px; box-sizing: border-box; }}
        input[type=submit] {{ margin-top: 12px; padding: 12px 20px; border-radius: 10px; border: none; background: #2563eb; color: white; font-weight: 600; cursor: pointer; }}
        input[type=submit]:hover {{ background: #1d4ed8; }}
        h1 {{ margin-bottom: 8px; }}
        h2 {{ margin-top: 0; }}
        ol {{ padding-left: 20px; margin: 10px 0; }}
        .small {{ color: #6b7280; font-size: 0.95rem; }}
        .status-chip {{ display: inline-block; padding: 6px 12px; border-radius: 999px; background: #e0f2fe; color: #0369a1; font-weight: 600; margin-bottom: 14px; }}
        #toast-container {{ position: fixed; right: 20px; top: 20px; width: 320px; z-index: 1000; }}
        .toast {{ background: #0d9488; color: #fff; padding: 14px 16px; border-radius: 12px; box-shadow: 0 10px 30px rgba(15,23,42,.15); margin-top: 12px; opacity: 0; transform: translateX(20px); transition: opacity .3s ease, transform .3s ease; }}
        .toast.show {{ opacity: 1; transform: translateX(0); }}
        .toast.error {{ background: #dc2626; }}
    </style>
</head>
<body>
    <header>
        <h1>Downloader YouTube</h1>
        <p class="small">Cole uma URL e ela será adicionada à fila. O download começa automaticamente.</p>
    </header>
    <div class="card">
        <form method="post" action="/">
            <label for="url">URL do YouTube</label>
            <input type="text" id="url" name="url" placeholder="https://www.youtube.com/watch?v=..." required />
            <input type="submit" value="Adicionar à fila" />
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
    <div class="card">
        <p class="small">Os arquivos serão salvos em <strong><a href="/open-folder" target="_self">videos/</a></strong>.</p>
    </div>
    <div id="toast-container"></div>
    <script>
        let lastMessageCount = {len(messages)};

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

        function updateStatus(data) {{
            const queueList = document.getElementById('queue-list');
            const messageList = document.getElementById('message-list');
            const statusChip = document.querySelector('.status-chip');
            queueList.innerHTML = data.urls.map(url => `<li>${{escapeHtml(url)}}</li>`).join('');
            messageList.innerHTML = data.messages.map(msg => `<li>${{escapeHtml(msg)}}</li>`).join('');
            statusChip.textContent = data.running ? 'Em execução' : 'Aguardando novos URLs';
            if (data.messages.length > lastMessageCount) {{
                for (let i = lastMessageCount; i < data.messages.length; i++) {{
                    const msg = data.messages[i];
                    if (msg.startsWith('Download concluído')) {{
                        createToast(msg);
                    }} else if (msg.startsWith('Erro')) {{
                        createToast(msg, true);
                    }}
                }}
                lastMessageCount = data.messages.length;
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
            with queue_lock:
                data = {
                    "urls": list(urls),
                    "messages": messages[-20:],
                    "running": download_thread is not None,
                }
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/open-folder":
            try:
                open_output_folder()
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            except Exception as exc:
                self.send_error(500, str(exc))
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
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        data = urllib.parse.parse_qs(body)
        url = data.get("url", [""])[0].strip()

        if url:
            with queue_lock:
                urls.append(url)
            messages.append(f"URL adicionada à fila: {url}")
            start_download_thread()

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def run_server() -> None:
    port = 8000
    server = ThreadingHTTPServer(("", port), SimpleHandler)
    print(f"Acesse http://localhost:{port} no navegador e cole a URL para adicionar à fila.")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
