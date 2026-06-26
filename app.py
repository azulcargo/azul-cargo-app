"""
Azul Cargo - Servidor de Rastreamento Automático
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import time
import re
import base64
import urllib.request
import urllib.error
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app)

# ─── Configurações ────────────────────────────────────────────────────────────
GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
CTE_REMETENTE = 'cte-azul@nfe24h.com.br'
AZUL_URL = 'https://www.azullogistica.com.br/Rastreio'
DATA_FILE = 'envios.json'
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'
GITHUB_REPO = 'azulcargo/azul-cargo-app'
GITHUB_FILE_PATH = 'envios.json'

# ─── Persistência no GitHub ───────────────────────────────────────────────────
def push_to_github(envios):
    """
    Salva envios.json no repositório GitHub via API.
    Necessário: variável de ambiente GITHUB_TOKEN com um Personal Access Token
    com permissão de escrita no repositório.
    """
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        print("[GitHub] GITHUB_TOKEN não configurado — pulando push.")
        return False

    api_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}'
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
    }

    try:
        # 1. Obter SHA atual do arquivo (necessário para atualização)
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            file_info = json.loads(resp.read())
        sha = file_info['sha']

        # 2. Fazer PUT com o conteúdo atualizado
        content_b64 = base64.b64encode(
            json.dumps(envios, ensure_ascii=False, indent=2).encode('utf-8')
        ).decode('ascii')

        payload = json.dumps({
            'message': f'[skip ci] Auto-update envios.json {datetime.now().strftime("%d/%m/%Y %H:%M")}',
            'content': content_b64,
            'sha': sha,
        }).encode('utf-8')

        req = urllib.request.Request(api_url, data=payload, method='PUT', headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            print(f"[GitHub] Push OK — commit {result['commit']['sha'][:7]}")
            return True

    except Exception as e:
        print(f"[GitHub] Erro no push: {e}")
        return False

# ─── Utilitários ──────────────────────────────────────────────────────────────
def carregar_envios():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def salvar_envios(envios):
    """Salva no disco local. Use salvar_e_persistir para também gravar no GitHub."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(envios, f, ensure_ascii=False, indent=2)

def salvar_e_persistir(envios):
    """Salva no disco local E faz push ao GitHub para persistência entre deploys."""
    salvar_envios(envios)
    push_to_github(envios)

def extrair_awb_da_chave(chave):
    chave = re.sub(r'[^0-9]', '', chave)
    if len(chave) >= 43:
        return '577' + chave[35:43]
    return None

def get_chrome_driver():
    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1280,900')
    return webdriver.Chrome(options=opts)

# ─── Gmail ────────────────────────────────────────────────────────────────────
def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def buscar_ctes_novos(envios_existentes):
    try:
        service = get_gmail_service()
        awbs_atuais = {e['awb'] for e in envios_existentes}
        novos_awbs = []

        query = f'from:{CTE_REMETENTE}'
        results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
        msgs = results.get('messages', [])

        for msg_ref in msgs:
            msg = service.users().messages().get(
                userId='me', id=msg_ref['id'], format='full'
            ).execute()
            parts = msg.get('payload', {}).get('parts', [])
            for part in parts:
                filename = part.get('filename', '')
                if filename.endswith('.xml') or filename.endswith('-cte-proc.xml'):
                    awb = extrair_awb_da_chave(filename)
                    if awb and awb not in awbs_atuais:
                        headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
                        data_email = headers.get('Date', '')
                        novos_awbs.append({
                            'awb': awb,
                            'filename': filename,
                            'data_email': data_email,
                        })
                        awbs_atuais.add(awb)

        print(f"[Gmail] {len(novos_awbs)} CTEs novos encontrados")
        return novos_awbs

    except Exception as e:
        print(f"[Gmail] Erro: {e}")
        return []

# ─── Azul Logística ───────────────────────────────────────────────────────────
def rastrear_awbs(awbs):
    resultados = {}
    if not awbs:
        return resultados

    driver = get_chrome_driver()
    try:
        for i in range(0, len(awbs), 30):
            lote = awbs[i:i+30]
            driver.get(AZUL_URL)
            wait = WebDriverWait(driver, 15)

            inp = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[placeholder*="rastreio"], input[placeholder*="código"]')
            ))

            awbs_str = ','.join(lote)
            driver.execute_script(
                "const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
                "s.call(arguments[0],arguments[1]);"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
                inp, awbs_str
            )
            time.sleep(1)

            btn_add = driver.find_element(By.XPATH, "//button[contains(text(),'Adicionar')]")
            btn_add.click()
            time.sleep(2)

            btn_cons = driver.find_element(By.XPATH, "//button[contains(text(),'Consultar')]")
            btn_cons.click()
            time.sleep(8)

            texto = driver.find_element(By.TAG_NAME, 'body').text

            for awb in lote:
                status = 'Em andamento'
                idx = texto.find(awb)
                trecho = texto[idx:idx+500] if idx >= 0 else ''

                if 'Entrega Realizada' in trecho or 'ENTREGA REALIZADA' in trecho:
                    status = 'Entregue'
                elif 'Saiu para Entrega' in trecho or 'SAIU PARA ENTREGA' in trecho:
                    status = 'Saiu para Entrega'
                elif 'Em Separação' in trecho:
                    status = 'Em Separação no Destino'

                prev = None
                m = re.search(r'Entrega até[:\s]*(\d{2}/\d{2}/\d{4})', trecho)
                if m:
                    prev = m.group(1)

                resultados[awb] = {
                    'status': status,
                    'prev_entrega': prev,
                    'ultima_atualizacao': datetime.now().strftime('%d/%m/%Y'),
                }

            print(f"[Azul] Lote {i//30+1}: {len(lote)} AWBs rastreados")

    except Exception as e:
        print(f"[Azul] Erro: {e}")
    finally:
        driver.quit()

    return resultados

# ─── Rotas da API ─────────────────────────────────────────────────────────────
@app.route('/api/envios', methods=['GET'])
def get_envios():
    envios = carregar_envios()
    return jsonify({
        'success': True,
        'total': len(envios),
        'ultima_atualizacao': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'envios': envios
    })

@app.route('/api/atualizar', methods=['POST'])
def atualizar():
    try:
        print("\n=== INÍCIO DA ATUALIZAÇÃO ===")
        envios = carregar_envios()

        novos = buscar_ctes_novos(envios)
        for n in novos:
            envios.append({
                'awb': n['awb'],
                'destinatario': '',
                'destino': '',
                'emissao': n.get('data_email', ''),
                'prev_entrega': '',
                'data_entrega': '',
                'frete': 0,
                'valor_produto': 0,
                'status': 'Em andamento',
                'ultima_atualizacao': '',
                'dias_uteis': None,
            })

        nao_entregues = [e['awb'] for e in envios if e.get('status') != 'Entregue']
        rastreio = rastrear_awbs(nao_entregues)

        for envio in envios:
            awb = envio['awb']
            if awb in rastreio:
                r = rastreio[awb]
                envio['status'] = r['status']
                envio['ultima_atualizacao'] = r['ultima_atualizacao']
                if r.get('prev_entrega') and not envio.get('prev_entrega'):
                    envio['prev_entrega'] = r['prev_entrega']
                    # Calcular dias_uteis ao atribuir prev_entrega
                    try:
                        d_em = datetime.strptime(envio.get('emissao', ''), '%d/%m/%Y')
                        d_pr = datetime.strptime(r['prev_entrega'], '%d/%m/%Y')
                        envio['dias_uteis'] = (d_pr - d_em).days
                    except Exception:
                        pass
                if r['status'] == 'Entregue' and not envio.get('data_entrega'):
                    envio['data_entrega'] = datetime.now().strftime('%d/%m/%Y')

        salvar_e_persistir(envios)
        print(f"=== ATUALIZAÇÃO CONCLUÍDA: {len(envios)} envios ===\n")

        return jsonify({
            'success': True,
            'novos_ctes': len(novos),
            'rastreados': len(rastreio),
            'total': len(envios),
            'envios': envios,
            'mensagem': f'{len(novos)} CTEs novos · {len(rastreio)} rastreados · {datetime.now().strftime("%d/%m/%Y %H:%M")}'
        })

    except Exception as e:
        print(f"[ERRO] {e}")
        return jsonify({'success': False, 'erro': str(e)}), 500

@app.route('/api/update-data', methods=['POST'])
def update_data():
    """
    Recebe dados enviados pelo Claude e salva no disco + GitHub.
    """
    try:
        payload = request.get_json()
        if not payload or 'envios' not in payload:
            return jsonify({'success': False, 'erro': 'Payload inválido'}), 400
        envios = payload['envios']
        salvar_e_persistir(envios)   # ← salva no disco E no GitHub
        print(f"[update-data] {len(envios)} envios salvos")
        return jsonify({
            'success': True,
            'total': len(envios),
            'mensagem': f'{len(envios)} envios salvos em {datetime.now().strftime("%d/%m/%Y %H:%M")}'
        })
    except Exception as e:
        print(f"[update-data] Erro: {e}")
        return jsonify({'success': False, 'erro': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({'status': 'online', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
