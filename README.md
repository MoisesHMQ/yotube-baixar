# YouTube Downloader

Projeto simples para baixar vídeos do YouTube usando `yt-dlp` com uma interface web básica.

## O que faz

- roda um servidor web local em `http://localhost:8000`
- o usuário cola URLs do YouTube em um formulário
- cada URL é adicionada a uma fila de downloads
- o download é executado em segundo plano
- ao concluir, uma mensagem de toast aparece no navegador
- os arquivos são salvos na pasta `videos/`
- é possível abrir a pasta `videos/` diretamente pelo link na página

## Arquivos principais

- `Untitled-1.py` - aplicação principal em Python
- `Dockerfile` - imagem Docker para rodar o projeto
- `requirements.txt` - dependências Python
- `.dockerignore` - arquivos ignorados no build Docker
- `videos/` - pasta de saída onde os downloads são salvos

## Requisitos

- Python 3.12
- `yt-dlp`
- `ffmpeg` (no Docker já instalado)

## Executar localmente

1. Instale dependências:

```powershell
pip install -r requirements.txt
```

2. Execute:

```powershell
python Untitled-1.py
```

3. Abra no navegador:

```text
http://localhost:8000
```

4. Cole a URL do YouTube e envie.

## Uso via Docker

1. Construa a imagem:

```powershell
docker build -t ytdownloader .
```

2. Rode o container:

```powershell
docker run --rm -p 8000:8000 -v ${PWD}:/app/videos ytdownloader
```

3. Abra no navegador:

```text
http://localhost:8000
```

> Observação: o comando de `docker run` acima monta a pasta `videos/` do host no container para que os arquivos baixados fiquem acessíveis localmente.

## Como funciona

- o servidor web usa `http.server` e `ThreadingMixIn`
- URLs submetidas pelo formulário POST são adicionadas a `urls`
- um worker em thread consome a fila e chama `yt_dlp`
- mensagens de status são exibidas na interface
- um endpoint `GET /status` retorna o estado atual para o cliente

## Observações

- Se `ffmpeg` não estiver disponível, o script baixa um único arquivo de melhor qualidade em vez de mesclar áudio/vídeo.
- A pasta `videos/` é criada automaticamente.
- O aplicativo mantém no máximo 20 mensagens recentes na interface.
