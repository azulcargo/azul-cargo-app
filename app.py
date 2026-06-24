"""
Azul Cargo - Servidor de Rastreamento Automático
Acessa Gmail + Site da Azul Logística e atualiza os dados
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import time
import re
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
import base64

app = Flask(__name__)
CORS(app)

# ─── Configurações ────────────────────────────────────────────────────────────
GMAIL_SCOPES    = ['https://www.googleapis.com/auth/gmail.readonly']
CTE_REMETENTE   = 'cte-azul@nfe24h.com.br'
AZUL_URL        = 'https://www.azullogistica.com.br/Rastreio'
DATA_FILE       = 'envios.json'
TOKEN_FILE      = 'token.json'
CREDENTIALS_FILE= 'credentials.json'

# ─── Utilitários ──────────────────────────────────────────────────────────────
def carregar_envios():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def salvar_envios(envios):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(envios, f, ensure_ascii=False, indent=2)

def extrair_awb_da_chave(chave):
    """Extrai o AWB do nome do arquivo CTE: '577' + chave[35:43]"""
    chave = re.sub(r'[^0-9]', '', chave)
    if len(chave) >= 43:
        return '577' + chave[35:43]
    return None

def get_chrome_driver():
    """Cria driver Chrome headless"""
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
    """Busca novos CTEs no Gmail que ainda não estão na lista"""
    try:
        service   = get_gmail_service()
        awbs_atuais = {e['awb'] for e in envios_existentes}
        novos_awbs  = []

        # Busca emails do remetente CTE
        query   = f'from:{CTE_REMETENTE}'
        results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
        msgs    = results.get('messages', [])

        for msg_ref in msgs:
            msg = service.users().messages().get(
                userId='me', id=msg_ref['id'], format='full'
            ).execute()

            # Percorre partes da mensagem procurando anexos XML
            parts = msg.get('payload', {}).get('parts', [])
            for part in parts:
                filename = part.get('filename', '')
                if filename.endswith('.xml') or filename.endswith('-cte-proc.xml'):
                    awb = extrair_awb_da_chave(filename)
                    if awb and awb not in awbs_atuais:
                        # Pegar data do email
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
    """Rastreia lista de AWBs no site da Azul Logística. Retorna dict awb->status"""
    resultados = {}
    if not awbs:
        return resultados

    driver = get_chrome_driver()
    try:
        # Processar em lotes de 30
        for i in range(0, len(awbs), 30):
            lote = awbs[i:i+30]
            driver.get(AZUL_URL)
            wait = WebDriverWait(driver, 15)

            # Aguardar campo de input
            inp = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[placeholder*="rastreio"], input[placeholder*="código"]')
            ))

            # Preencher via JS (site React)
            awbs_str = ','.join(lote)
            driver.execute_script(
                "const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
                "s.call(arguments[0],arguments[1]);"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
                inp, awbs_str
            )
            time.sleep(1)

            # Clicar Adicionar
            btn_add = driver.find_element(By.XPATH, "//button[contains(text(),'Adicionar')]")
            btn_add.click()
            time.sleep(2)

            # Clicar Consultar
            btn_cons = driver.find_element(By.XPATH, "//button[contains(text(),'Consultar')]")
            btn_cons.click()
            time.sleep(8)

            # Ler texto da página
            texto = driver.find_element(By.TAG_NAME, 'body').text

            # Extrair status por AWB
            for awb in lote:
                status = 'Em andamento'
                # Procurar o AWB no texto e identificar o status próximo
                idx = texto.find(awb)
                if idx >= 0:
                    trecho = texto[idx:idx+500]
                    if 'Entrega Realizada' in trecho or 'ENTREGA REALIZADA' in trecho:
                        status = 'Entregue'
                    elif 'Saiu para Entrega' in trecho or 'SAIU PARA ENTREGA' in trecho:
                        status = 'Saiu para Entrega'
                    elif 'Em Separação' in trecho:
                        status = 'Em Separação no Destino'
                    elif 'Trânsito' in trecho or 'TRÂNSITO' in trecho:
                        status = 'Em andamento'
                    elif 'Preparação' in trecho or 'PREPARAÇÃO' in trecho:
                        status = 'Em andamento'

                # Extrair data prevista
                prev = None
                m = re.search(r'Entrega até[:\s]*(\d{2}/\d{2}/\d{4})', trecho if idx >= 0 else '')
                if m:
                    prev = m.group(1)

                # Extrair destino
                destino = None
                m2 = re.search(r'Destino\s*\n([^\n]+)', trecho if idx >= 0 else '')
                if m2:
                    destino = m2.group(1).strip()

                resultados[awb] = {
                    'status': status,
                    'prev_entrega': prev,
                    'destino': destino,
                    'ultima_atualizacao': datetime.now().strftime('%d/%m/%Y %H:%M'),
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
    """Retorna todos os envios salvos"""
    envios = carregar_envios()
    return jsonify({
        'success': True,
        'total': len(envios),
        'ultima_atualizacao': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'envios': envios
    })

@app.route('/api/atualizar', methods=['POST'])
def atualizar():
    """
    Endpoint principal — executado quando o botão Atualizar é clicado.
    1. Busca CTEs novos no Gmail
    2. Rastreia todos os não entregues no site da Azul
    3. Salva e retorna os dados atualizados
    """
    try:
        print("\n=== INÍCIO DA ATUALIZAÇÃO ===")
        envios = carregar_envios()

        # 1. Buscar CTEs novos no Gmail
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
            })

        # 2. Rastrear todos os não entregues
        nao_entregues = [e['awb'] for e in envios if e.get('status') != 'Entregue']
        rastreio = rastrear_awbs(nao_entregues)

        # 3. Atualizar status
        for envio in envios:
            awb = envio['awb']
            if awb in rastreio:
                r = rastreio[awb]
                envio['status'] = r['status']
                envio['ultima_atualizacao'] = r['ultima_atualizacao']
                if r.get('prev_entrega') and not envio.get('prev_entrega'):
                    envio['prev_entrega'] = r['prev_entrega']
                if r.get('destino') and not envio.get('destino'):
                    envio['destino'] = r['destino']
                if r['status'] == 'Entregue' and not envio.get('data_entrega'):
                    envio['data_entrega'] = datetime.now().strftime('%d/%m/%Y')

        salvar_envios(envios)
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
    Recebe dados atualizados de envios enviados pelo Claude (scheduled task).
    Aceita JSON com lista de envios e salva em envios.json.
    """
    try:
        payload = request.get_json()
        if not payload or 'envios' not in payload:
            return jsonify({'success': False, 'erro': 'Payload inválido'}), 400
        envios = payload['envios']
        salvar_envios(envios)
        print(f"[update-data] {len(envios)} envios recebidos e salvos")
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
    """Health check"""
    return jsonify({'status': 'online', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
