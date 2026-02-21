# Setup amb uv

## 1. Instal·lar uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Instal·lar dependències
```bash
uv sync
```

## 3. Configurar Google Calendar
- console.cloud.google.com
- Crear projecte + OAuth → google_credentials.json
- Moure a config/

## 4. Configurar Obsidian
Edita .env:
```env
OBSIDIAN_VAULT_PATH=/path/to/vault
```

## 5. Executar
```bash
uv run python src/reunio_interactiva.py
```
