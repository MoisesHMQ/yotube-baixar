# YouTube Downloader

Projeto simples para baixar vídeos e áudios do YouTube usando `yt-dlp` com uma interface web local.

## O que faz

- Roda um servidor web local em `http://localhost:8000`
- O usuário cola a URL do YouTube e escolhe o formato de saída
- Cada URL é adicionada a uma fila e o download começa automaticamente em segundo plano
- Ao concluir, uma notificação toast aparece no navegador
- Os arquivos são salvos na pasta `videos/`
- É possível abrir a pasta `videos/` diretamente pelo link na página

## Formatos suportados

| Formato | Tipo | Requer ffmpeg |
|---------|------|:---:|
| MP3 | Áudio | Sim |
| MP4 | Vídeo | Não* |
| MKV | Vídeo | Sim |
| AVI | Vídeo | Sim |
| MOV | Vídeo | Sim |
| WMV | Vídeo | Sim |

\* MP4 sem ffmpeg baixa o melhor stream disponível com áudio integrado, sem conversão. Todos os outros formatos exigem ffmpeg.

## Arquivos principais

- `Untitled-1.py` — aplicação principal em Python
- `Dockerfile` — imagem Docker para rodar o projeto
- `requirements.txt` — dependências Python
- `.dockerignore` — arquivos ignorados no build Docker
- `videos/` — pasta de saída onde os downloads são salvos

## Requisitos

- Python 3.12+
- `yt-dlp`
- `ffmpeg` (recomendado; no Docker já vem instalado)

## Executar localmente

1. Instale as dependências:

```powershell
pip install -r requirements.txt
```

2. Execute:

```powershell
python Untitled-1.py
```

3. Abra no navegador:

```
http://localhost:8000
```

4. Cole a URL do YouTube, escolha o formato e clique em **Adicionar à fila**.

## Uso via Docker

1. Construa a imagem:

```powershell
docker build -t ytdownloader .
```

2. Rode o container:

```powershell
docker run --rm -p 8000:8000 -v "${PWD}/videos:/app/videos" ytdownloader
```

No Windows com PowerShell, use:

```powershell
docker run --rm -p 8000:8000 -v "${PWD}\videos:/app/videos" ytdownloader
```

3. Abra no navegador:

```
http://localhost:8000
```

> O comando `docker run` monta a pasta `videos/` do host no container para que os arquivos fiquem acessíveis localmente.

## Como funciona

- O servidor web usa `http.server` com `ThreadingMixIn`
- URLs submetidas via POST são validadas (apenas `http://` e `https://`) e adicionadas à fila
- Um worker em thread separada consome a fila sequencialmente e chama `yt-dlp`
- O formato escolhido determina as opções passadas ao `yt-dlp` e ao `ffmpeg`
- Um endpoint `GET /status` retorna o estado atual (fila, mensagens, status do worker) para o cliente em JSON
- O cliente faz polling a cada 3 segundos e exibe toasts para conclusões e erros

## Observações

- Se `ffmpeg` não estiver disponível, apenas o formato MP4 é aceito; os demais são rejeitados com mensagem de erro.
- A pasta `videos/` é criada automaticamente na primeira execução.
- O histórico de mensagens é limitado a 500 entradas; a interface exibe as 20 mais recentes.
