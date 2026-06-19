# Azul Cargo — Dashboard de Rastreamento

## Como publicar (passo a passo)

### PARTE 1 — Configurar o Gmail API (5 minutos)

1. Acesse https://console.cloud.google.com
2. Crie um projeto novo (botão "Novo Projeto", dê qualquer nome)
3. No menu lateral: **APIs e Serviços → Biblioteca**
4. Busque por **"Gmail API"** e clique em **Ativar**
5. Vá em **APIs e Serviços → Credenciais**
6. Clique em **Criar credenciais → ID do cliente OAuth**
7. Tipo de aplicativo: **Aplicativo para computador**
8. Baixe o arquivo JSON e renomeie para **`credentials.json`**
9. Coloque o `credentials.json` na pasta `azul_cargo_app`
10. Rode localmente uma vez: `python app.py`
    - Vai abrir o navegador pedindo autorização Gmail
    - Autorize e feche — isso gera o arquivo `token.json`

---

### PARTE 2 — Publicar no Railway (10 minutos)

1. Acesse https://railway.app e crie conta (pode usar GitHub)
2. Clique em **New Project → Deploy from GitHub repo**
3. Conecte seu GitHub e suba a pasta `azul_cargo_app` como repositório
   - Ou use **Deploy from local** e arraste a pasta
4. Railway vai detectar o Python automaticamente
5. Após publicar, vá em **Settings → Domains → Generate Domain**
6. Copie a URL gerada (ex: `https://azul-cargo.up.railway.app`)

---

### PARTE 3 — Conectar o Dashboard (2 minutos)

1. Abra o arquivo `index.html`
2. Na linha que tem `const API_URL = 'https://SEU-PROJETO.up.railway.app'`
3. Substitua pela URL gerada no Railway
4. Salve e publique o `index.html` no Netlify Drop (arrastar e soltar em app.netlify.com/drop)

---

### Resultado final

- **Dashboard** (Netlify): qualquer pessoa com o link vê os dados
- **Botão "Atualizar agora"**: chama o servidor Railway que:
  1. Loga no Gmail e busca CTEs novos
  2. Acessa o site da Azul e rastreia todos em aberto
  3. Retorna os dados atualizados para o dashboard

---

## Estrutura dos arquivos

```
azul_cargo_app/
├── app.py              ← Servidor Python (Railway)
├── requirements.txt    ← Dependências Python
├── Procfile            ← Configuração Railway
├── railway.json        ← Configuração Railway
├── nixpacks.toml       ← Instala Chrome no Railway
├── envios.json         ← Dados dos envios (atualizado automaticamente)
├── credentials.json    ← Chave Gmail API (você adiciona)
├── token.json          ← Token de acesso Gmail (gerado automaticamente)
└── index.html          ← Dashboard (Netlify)
```

## Suporte

Em caso de dúvidas, abra uma conversa com o Claude e peça ajuda com
"meu dashboard Azul Cargo no Railway".
