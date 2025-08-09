import os
import datetime
import dateparser
import json
from openai import OpenAI
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# --- Configurações e Autenticações ---
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

def autenticar_google_calendar():
    # Esta função permanece a mesma
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


# --- FERRAMENTAS QUE A IA PODERÁ USAR ---

def buscar_horarios_disponiveis(data: str):
    """
    Verifica os horários de consulta disponíveis em uma data específica.
    Já trata dias da semana e eventos de dia inteiro.
    """
    print(f"--- Ferramenta 'buscar_horarios_disponiveis' chamada com data: {data} ---")
    service = autenticar_google_calendar()
    
    data_parseada_obj = dateparser.parse(data, languages=['pt'])
    if not data_parseada_obj:
        return json.dumps({"error": "Data não compreendida. Peça ao usuário para tentar um formato diferente."})

    data_selecionada = data_parseada_obj.date()
    data_formatada = data_selecionada.strftime('%Y-%m-%d')
    
    # --- REGRAS DE NEGÓCIO IMPLEMENTADAS DIRETAMENTE NA FERRAMENTA ---
    if data_selecionada < datetime.date.today():
        return json.dumps({"info": "Não é possível agendar em datas passadas. Informe o usuário."})

    if data_selecionada.weekday() > 4:  # Segunda é 0, Sexta é 4. > 4 é Sábado ou Domingo.
        return json.dumps({"info": f"O Dr. João não atende aos fins de semana. A data {data_formatada} é um(a) {'Sábado' if data_selecionada.weekday() == 5 else 'Domingo'}."})
    # --- FIM DAS REGRAS DE NEGÓCIO ---

    try:
        inicio_dia = datetime.datetime(data_selecionada.year, data_selecionada.month, data_selecionada.day, HORARIO_INICIO, 0, 0, tzinfo=SAO_PAULO_TZ)
        fim_dia = datetime.datetime(data_selecionada.year, data_selecionada.month, data_selecionada.day, HORARIO_FIM, 0, 0, tzinfo=SAO_PAULO_TZ)

        eventos_resultado = service.events().list(
            calendarId='primary', timeMin=inicio_dia.isoformat(), timeMax=fim_dia.isoformat(),
            singleEvents=True, orderBy='startTime'
        ).execute().get('items', [])

        horarios_ocupados = []
        for ev in eventos_resultado:
            if 'dateTime' in ev['start']:
                inicio_dt = datetime.datetime.fromisoformat(ev['start']['dateTime'])
                fim_dt = datetime.datetime.fromisoformat(ev['end']['dateTime'])
                horarios_ocupados.append((inicio_dt, fim_dt))
            elif 'date' in ev['start']:
                print(f"--- Encontrado evento de dia inteiro: '{ev.get('summary', 'Sem Título')}' ---")
                horarios_ocupados.append((inicio_dia, fim_dia))

        horarios_livres = []
        for hora in range(HORARIO_INICIO, HORARIO_FIM):
            slot_inicio = datetime.datetime(data_selecionada.year, data_selecionada.month, data_selecionada.day, hora, 0, 0, tzinfo=SAO_PAULO_TZ)
            slot_fim = slot_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)
            
            conflito = any(slot_inicio < ocupado_fim.astimezone(SAO_PAULO_TZ) and slot_fim > ocupado_inicio.astimezone(SAO_PAULO_TZ) for ocupado_inicio, ocupado_fim in horarios_ocupados)
            
            if not conflito:
                horarios_livres.append(slot_inicio.strftime('%H:%M'))
        
        if not horarios_livres:
            return json.dumps({"info": f"Nenhum horário disponível encontrado para {data_formatada}. Todos os horários podem estar ocupados."})
        
        return json.dumps({"horarios_disponiveis": horarios_livres})

    except HttpError as e:
        return json.dumps({"error": f"Ocorreu um erro ao conectar com a agenda do Google: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Ocorreu um erro interno inesperado: {e}"})

def agendar_consulta(data: str, horario: str):
    """
    Agenda uma nova consulta no calendário para uma data e horário específicos.
    """
    print(f"--- Ferramenta 'agendar_consulta' chamada com data: {data} e horário: {horario} ---")
    service = autenticar_google_calendar()

    try:
        data_hora_inicio_str = f"{data} {horario}"
        data_hora_inicio = datetime.datetime.strptime(data_hora_inicio_str, '%Y-%m-%d %H:%M').astimezone(SAO_PAULO_TZ)
        data_hora_fim = data_hora_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)

        evento = {
            'summary': 'Consulta (agendada por IA)',
            'description': 'Consulta agendada via assistente virtual inteligente.',
            'start': {'dateTime': data_hora_inicio.isoformat(), 'timeZone': str(SAO_PAULO_TZ)},
            'end': {'dateTime': data_hora_fim.isoformat(), 'timeZone': str(SAO_PAULO_TZ)},
        }

        evento_criado = service.events().insert(calendarId='primary', body=evento).execute()
        link = evento_criado.get('htmlLink')
        
        return json.dumps({"status": "sucesso", "mensagem": f"Consulta agendada com sucesso para {data} às {horario}.", "link_evento": link})
    
    except Exception as e:
        return json.dumps({"status": "erro", "mensagem": "Não foi possível criar o evento no calendário."})


# --- O Cérebro do Agente (com as novas regras) ---

def main():
    tools = [
        { "type": "function", "function": {
                "name": "buscar_horarios_disponiveis",
                "description": "Verifica os horários de consulta livres para uma data específica.",
                "parameters": { "type": "object", "properties": {
                        "data": {"type": "string", "description": "A data para a busca, ex: 'amanhã', '25/12/2025'"},
                    },"required": ["data"],}, }, },
        { "type": "function", "function": {
                "name": "agendar_consulta",
                "description": "Realiza o agendamento de uma consulta em uma data e horário específicos.",
                "parameters": { "type": "object", "properties": {
                        "data": {"type": "string", "description": "A data da consulta no formato AAAA-MM-DD."},
                        "horario": {"type": "string", "description": "O horário da consulta no formato HH:MM."},
                    },"required": ["data", "horario"],}, }, }
    ]

    available_tools = {
        "buscar_horarios_disponiveis": buscar_horarios_disponiveis,
        "agendar_consulta": agendar_consulta,
    }

    # --- NOVO SYSTEM_PROMPT MAIS INTELIGENTE ---
    messages = [
        {"role": "system", "content": f"""
        Você é um assistente de agendamento para o Dr. João Silva, cardiologista. Hoje é {hoje}.
        Sua principal função é marcar consultas usando as ferramentas disponíveis. Seja sempre cordial e prestativo.

        Regras de Atendimento:
        - O Dr. João Silva atende APENAS de segunda a sexta-feira.
        - O horário de atendimento é estritamente das {HORARIO_INICIO}h às {HORARIO_FIM}h.
        - Cada consulta tem a duração de {DURACAO_CONSULTA} hora.

        Instruções para o Agendamento:
        1. Se o usuário pedir para marcar uma consulta, você deve primeiro usar a ferramenta 'buscar_horarios_disponiveis'.
        2. Se a data que o usuário informar for um sábado ou domingo, informe imediatamente que o Dr. João não atende nesses dias e peça para ele escolher um dia de semana, sem usar a ferramenta.
        3. Se a data for válida, liste os horários disponíveis que a ferramenta retornar.
        4. Se o usuário escolher um horário que NÃO está na lista, informe educadamente que aquele horário não está disponível e mostre a lista novamente.
        5. Se o usuário confirmar um horário VÁLIDO, use a ferramenta 'agendar_consulta' para criar o evento.

        Restrições:
        - Nunca invente horários. Confie apenas no resultado das ferramentas.
        - Responda em português.
        """}
    ]

    print("Assistente virtual do Dr. João Silva. Como posso ajudar?")

    while True:
        entrada = input("Você: ")
        if not entrada: continue # Ignora entradas vazias
        
        messages.append({"role": "user", "content": entrada})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        response_message = response.choices[0].message
        messages.append(response_message)

        tool_calls = response_message.tool_calls
        if tool_calls:
            print("--- IA decidiu usar uma ferramenta ---")
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_to_call = available_tools[function_name]
                function_args = json.loads(tool_call.function.arguments)
                
                function_response = function_to_call(**function_args)
                
                messages.append(
                    { "tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": function_response, }
                )

            final_response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
            )
            print("Assistente:", final_response.choices[0].message.content)
            messages.append(final_response.choices[0].message)
        
        else:
            print("Assistente:", response_message.content)
            
if __name__ == "__main__":
    main()