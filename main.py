import os
import datetime
import dateparser
import json
import pandas as pd
import re
from openai import OpenAI
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# --- Configurações e Constantes ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("A variável de ambiente OPENAI_API_KEY não foi definida.")

client = OpenAI(api_key=OPENAI_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/calendar']
SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
HORARIO_INICIO = 10
HORARIO_FIM = 17
DURACAO_CONSULTA = 1
hoje = datetime.datetime.now(SAO_PAULO_TZ).strftime('%Y-%m-%d')
DB_PACIENTES = 'pacientes.csv'
DB_CONSULTAS = 'consultas.csv'

def autenticar_google_calendar():
    token_path = 'token.json'
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def _limpar_cpf(cpf_bruto: str) -> str:
    return re.sub(r'\D', '', cpf_bruto)

# --- FERRAMENTAS ROBUSTAS E DEFINITIVAS ---

def verificar_paciente_existente(cpf: str):
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- Ferramenta 'verificar_paciente_existente' chamada com CPF: {cpf_limpo} ---")
    if not os.path.exists(DB_PACIENTES):
        return json.dumps({"status": "nao_encontrado"})
    df = pd.read_csv(DB_PACIENTES, dtype={'cpf': str})
    df['cpf'] = df['cpf'].apply(_limpar_cpf)
    paciente = df[df['cpf'] == cpf_limpo]
    if paciente.empty:
        return json.dumps({"status": "nao_encontrado"})
    else:
        return json.dumps({"status": "encontrado", "dados": paciente.iloc[0].to_dict()})

def buscar_horarios_disponiveis(data: str):
    print(f"--- Ferramenta 'buscar_horarios_disponiveis' chamada com data: '{data}' ---")
    data_parseada_obj = None
    try:
        data_parseada_obj = datetime.datetime.strptime(data, '%Y-%m-%d')
    except ValueError:
        data_parseada_obj = dateparser.parse(data, languages=['pt'], settings={'PREFER_DATES_FROM': 'future', 'STRICT_PARSING': False})

    if not data_parseada_obj:
        return json.dumps({"error": f"A data '{data}' não pôde ser compreendida."})

    data_selecionada = data_parseada_obj.date()
    data_formatada = data_selecionada.strftime('%Y-%m-%d')
    
    if data_selecionada < datetime.date.today():
        return json.dumps({"info": f"A data {data_formatada} é no passado. Não é possível agendar."})

    if data_selecionada.weekday() > 4:
        nome_dia = "Sábado" if data_selecionada.weekday() == 5 else "Domingo"
        return json.dumps({"info": f"A data {data_formatada} é um {nome_dia}. O Dr. João não atende."})

    try:
        service = autenticar_google_calendar()
        inicio_dia = datetime.datetime(data_selecionada.year, data_selecionada.month, data_selecionada.day, HORARIO_INICIO, 0, 0, tzinfo=SAO_PAULO_TZ)
        fim_dia = datetime.datetime(data_selecionada.year, data_selecionada.month, data_selecionada.day, HORARIO_FIM, 0, 0, tzinfo=SAO_PAULO_TZ)
        eventos_resultado = service.events().list(calendarId='primary', timeMin=inicio_dia.isoformat(), timeMax=fim_dia.isoformat(), singleEvents=True, orderBy='startTime').execute().get('items', [])
        horarios_ocupados = []
        for ev in eventos_resultado:
            if 'dateTime' in ev['start']:
                horarios_ocupados.append((datetime.datetime.fromisoformat(ev['start']['dateTime']), datetime.datetime.fromisoformat(ev['end']['dateTime'])))
            elif 'date' in ev['start']:
                horarios_ocupados.append((inicio_dia, fim_dia))
        horarios_livres = []
        for hora in range(HORARIO_INICIO, HORARIO_FIM):
            slot_inicio = datetime.datetime(data_selecionada.year, data_selecionada.month, data_selecionada.day, hora, 0, 0, tzinfo=SAO_PAULO_TZ)
            slot_fim = slot_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)
            if not any(slot_inicio < ocupado_fim.astimezone(SAO_PAULO_TZ) and slot_fim > ocupado_inicio.astimezone(SAO_PAULO_TZ) for ocupado_inicio, ocupado_fim in horarios_ocupados):
                horarios_livres.append(slot_inicio.strftime('%H:%M'))
        if not horarios_livres:
            return json.dumps({"info": f"Nenhum horário disponível encontrado para {data_formatada}."})
        return json.dumps({"horarios_disponiveis": horarios_livres, "data_confirmada": data_formatada})
    except Exception as e:
        print(f"ERRO CRÍTICO em buscar_horarios_disponiveis: {e}")
        return json.dumps({"error": "Ocorreu um erro interno ao acessar a agenda."})

def cadastrar_paciente_e_agendar(cpf: str, nome: str, email: str, telefone: str, data_nascimento: str, data_consulta: str, horario_consulta: str):
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- Ferramenta 'cadastrar_paciente_e_agendar' chamada para CPF: {cpf_limpo} ---")
    try:
        service = autenticar_google_calendar()
        data_hora_inicio = datetime.datetime.strptime(f"{data_consulta} {horario_consulta}", '%Y-%m-%d %H:%M').astimezone(SAO_PAULO_TZ)
        evento_criado = service.events().insert(calendarId='primary', body={'summary': f'Consulta - {nome}', 'description': f'Paciente (1ª Consulta): {nome}\nCPF: {cpf_limpo}', 'start': {'dateTime': data_hora_inicio.isoformat()}, 'end': {'dateTime': (data_hora_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)).isoformat()}, 'attendees': [{'email': email}]}, sendUpdates='all').execute()
        id_evento = evento_criado.get('id')
        print(f"--- Evento criado no Google Calendar com ID: {id_evento} ---")
        novo_paciente_df = pd.DataFrame([{'cpf': cpf_limpo, 'nome_completo': nome, 'email': email, 'telefone': telefone, 'data_nascimento': data_nascimento, 'data_cadastro': hoje}])
        pacientes_df = pd.concat([pd.read_csv(DB_PACIENTES, dtype={'cpf': str}), novo_paciente_df], ignore_index=True) if os.path.exists(DB_PACIENTES) else novo_paciente_df
        pacientes_df.to_csv(DB_PACIENTES, index=False)
        print(f"--- Paciente {nome} salvo em {DB_PACIENTES} ---")
        id_consulta = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{cpf_limpo}"
        nova_consulta_df = pd.DataFrame([{'id_consulta': id_consulta, 'cpf_paciente': cpf_limpo, 'id_evento_google': id_evento, 'data_consulta': data_consulta, 'horario_consulta': horario_consulta, 'status': 'agendado', 'observacoes': ''}])
        consultas_df = pd.concat([pd.read_csv(DB_CONSULTAS), nova_consulta_df], ignore_index=True) if os.path.exists(DB_CONSULTAS) else nova_consulta_df
        consultas_df.to_csv(DB_CONSULTAS, index=False)
        print(f"--- Consulta salva em {DB_CONSULTAS} ---")
        return json.dumps({"status": "sucesso"})
    except Exception as e:
        print(f"ERRO CRÍTICO em cadastrar_paciente_e_agendar: {e}")
        return json.dumps({"status": "erro"})

# --- FUNÇÃO QUE FALTAVA ---
def agendar_consulta_retorno(cpf: str, data_consulta: str, horario_consulta: str):
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- Ferramenta 'agendar_consulta_retorno' chamada para CPF: {cpf_limpo} ---")
    try:
        pacientes_df = pd.read_csv(DB_PACIENTES, dtype={'cpf': str})
        pacientes_df['cpf'] = pacientes_df['cpf'].apply(_limpar_cpf)
        paciente_info = pacientes_df[pacientes_df['cpf'] == cpf_limpo].iloc[0]
        nome, email = paciente_info['nome_completo'], paciente_info['email']
        service = autenticar_google_calendar()
        data_hora_inicio = datetime.datetime.strptime(f"{data_consulta} {horario_consulta}", '%Y-%m-%d %H:%M').astimezone(SAO_PAULO_TZ)
        evento_criado = service.events().insert(calendarId='primary', body={'summary': f'Consulta - {nome} (Retorno)', 'description': f'Paciente: {nome}\nCPF: {cpf_limpo}', 'start': {'dateTime': data_hora_inicio.isoformat()}, 'end': {'dateTime': (data_hora_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)).isoformat()}, 'attendees': [{'email': email}]}, sendUpdates='all').execute()
        id_evento = evento_criado.get('id')
        print(f"--- Evento de retorno criado com ID: {id_evento} ---")
        id_consulta = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{cpf_limpo}"
        nova_consulta_df = pd.DataFrame([{'id_consulta': id_consulta, 'cpf_paciente': cpf_limpo, 'id_evento_google': id_evento, 'data_consulta': data_consulta, 'horario_consulta': horario_consulta, 'status': 'agendado', 'observacoes': ''}])
        consultas_df = pd.concat([pd.read_csv(DB_CONSULTAS), nova_consulta_df], ignore_index=True) if os.path.exists(DB_CONSULTAS) else nova_consulta_df
        consultas_df.to_csv(DB_CONSULTAS, index=False)
        print(f"--- Consulta de retorno salva em {DB_CONSULTAS} ---")
        return json.dumps({"status": "sucesso"})
    except Exception as e:
        print(f"ERRO CRÍTICO em agendar_consulta_retorno: {e}")
        return json.dumps({"status": "erro"})

def main():
    tools = [
        {"type": "function", "function": {"name": "verificar_paciente_existente", "description": "Verifica um paciente pelo CPF.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}}, "required": ["cpf"]}}},
        {"type": "function", "function": {"name": "buscar_horarios_disponiveis", "description": "Busca horários livres em uma data.", "parameters": {"type": "object", "properties": {"data": {"type": "string"}}, "required": ["data"]}}},
        {"type": "function", "function": {"name": "cadastrar_paciente_e_agendar", "description": "Cadastra um NOVO paciente e agenda sua primeira consulta.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}, "nome": {"type": "string"}, "email": {"type": "string"}, "telefone": {"type": "string"}, "data_nascimento": {"type": "string", "description": "Formato AAAA-MM-DD"}, "data_consulta": {"type": "string"}, "horario_consulta": {"type": "string"}}, "required": ["cpf", "nome", "email", "telefone", "data_nascimento", "data_consulta", "horario_consulta"]}}},
        {"type": "function", "function": {"name": "agendar_consulta_retorno", "description": "Agenda uma consulta para um paciente EXISTENTE.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}, "data_consulta": {"type": "string"}, "horario_consulta": {"type": "string"}}, "required": ["cpf", "data_consulta", "horario_consulta"]}}}
    ]
    available_tools = {"verificar_paciente_existente": verificar_paciente_existente, "buscar_horarios_disponiveis": buscar_horarios_disponiveis, "cadastrar_paciente_e_agendar": cadastrar_paciente_e_agendar, "agendar_consulta_retorno": agendar_consulta_retorno}

    messages = [{"role": "system", "content": f"""
        Você é um assistente virtual do consultório do Dr. João Silva. Sua personalidade é prestativa, educada e humana. Hoje é {hoje}.

        **FLUXO DE CONVERSA PRINCIPAL (Modelo Reativo e Preciso):**
        1.  **SAUDAÇÃO INICIAL:** Comece de forma calorosa e aberta. Nunca peça o CPF de imediato.
        2.  **AGUARDE A INTENÇÃO:** Espere o usuário dizer o que deseja (marcar, cancelar, etc.).
        3.  **PEÇA O CPF (QUANDO NECESSÁRIO):** Se a ação exigir dados pessoais, peça o CPF educadamente.
        4.  **VERIFIQUE O PACIENTE:** Use a ferramenta `verificar_paciente_existente`.
        5.  **CAMINHO - PACIENTE RECORRENTE:** Se encontrado, saúde-o pelo nome e pergunte para qual dia ele deseja a consulta.
        6.  **CAMINHO - NOVO PACIENTE:** Se não encontrado, informe-o e peça os dados de cadastro (Nome, E-mail, Telefone, Data de Nascimento). Após coletar, peça consentimento (LGPD). Após o consentimento, pergunte: "Perfeito, cadastro realizado! Para qual data você gostaria de agendar sua primeira consulta?". NUNCA busque horários sem o usuário informar a data.
        7.  **BUSCANDO HORÁRIOS:** Ao receber a data do usuário, use `buscar_horarios_disponiveis`. Se retornar horários, sua única tarefa é apresentar a lista e perguntar qual o usuário prefere. Se retornar erro ou info, apenas repasse a mensagem.
        8.  **AGENDAMENTO FINAL:** Após o usuário escolher um horário válido, use a ferramenta apropriada (`cadastrar_paciente_e_agendar` para novos, `agendar_consulta_retorno` para existentes).
        Siga estas instruções rigorosamente.
        """}]
    
    print("Assistente: Olá! Sou o assistente virtual do Dr. João Silva. Como posso ajudar você hoje?")
    
    while True:
        entrada = input("Você: ")
        if not entrada: continue
        messages.append({"role": "user", "content": entrada})
        response = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools, tool_choice="auto")
        response_message = response.choices[0].message
        messages.append(response_message)
        tool_calls = response_message.tool_calls
        if tool_calls:
            print("--- IA decidiu usar uma ferramenta ---")
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                if function_name not in available_tools:
                    print(f"Erro: A IA tentou chamar uma ferramenta desconhecida: {function_name}")
                    continue
                function_to_call = available_tools[function_name]
                try:
                    function_args = json.loads(tool_call.function.arguments)
                    function_response = function_to_call(**function_args)
                    messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": function_response})
                except json.JSONDecodeError:
                    print(f"Erro: Argumentos inválidos da IA para a ferramenta {function_name}.")
                except TypeError as e:
                    print(f"Erro de argumento na chamada da ferramenta {function_name}: {e}")

            final_response = client.chat.completions.create(model="gpt-4o", messages=messages)
            print("Assistente:", final_response.choices[0].message.content)
            messages.append(final_response.choices[0].message)
        else:
            print("Assistente:", response_message.content)

if __name__ == "__main__":
    main()