from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

flow = InstalledAppFlow.from_client_secrets_file('credentials.json', GMAIL_SCOPES)
creds = flow.run_local_server(port=8765)

with open('token.json', 'w') as f:
    f.write(creds.to_json())

print("\n\n=== TOKEN GERADO COM SUCESSO ===")
print("Arquivo token.json criado em:", "C:\\azul-cargo\\token.json")
input("\nPressione Enter para fechar...")