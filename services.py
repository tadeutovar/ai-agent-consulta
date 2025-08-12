# services.py

import datetime
import json
import re
from sqlalchemy.orm import Session
from googleapiclient.errors import HttpError
import models
import dateparser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from zoneinfo import ZoneInfo
import os

# --- Constantes e Funções Auxiliares Internas ---
SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
HORARIO_INICIO = 10
HORARIO_FIM = 17
DURACAO_CONSULTA = 1
SCOPES = ['https://www.googleapis.com/auth/calendar']

# --- Inicialização Centralizada do Serviço Google ---
GOOGLE_CALENDAR_SERVICE = None

def inicializar_google_calendar():
    global GOOGLE_CALENDAR_SERVICE
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    GOOGLE_CALENDAR_SERVICE = build('calendar', 'v3', credentials=creds)
    print("--- Serviço do Google Calendar autenticado e pronto para uso. ---")

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

# --- Implementação Completa e Corrigida das Ferramentas ---

def verificar_paciente_existente(db: Session, cpf: str):
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- DB | Verificando CPF: {cpf_limpo} ---")
    paciente = db.query(models.Paciente).filter(models.Paciente.cpf == cpf_limpo).first()
    if paciente:
        return json.dumps({"status": "encontrado", "dados": {"nome_completo": paciente.nome_completo}})
    return json.dumps({"status": "nao_encontrado"})

def buscar_horarios_disponiveis(db: Session, data: str):
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

def cadastrar_paciente_e_agendar(db: Session, cpf: str, nome: str, email: str, telefone: str, data_consulta: str, horario_consulta: str):
    if not GOOGLE_CALENDAR_SERVICE: return json.dumps({"status": "erro", "mensagem": "Serviço do Google não ativo."})
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- DB | Cadastrando e agendando para CPF: {cpf_limpo} ---")
    try:
        data_hora_inicio = datetime.datetime.strptime(f"{data_consulta} {horario_consulta}", '%Y-%m-%d %H:%M').astimezone(SAO_PAULO_TZ)
        evento_criado = GOOGLE_CALENDAR_SERVICE.events().insert(calendarId='primary', body={'summary': f'Consulta - {nome}', 'description': f'1ª Consulta: {nome}\nCPF: {cpf_limpo}', 'start': {'dateTime': data_hora_inicio.isoformat()}, 'end': {'dateTime': (data_hora_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)).isoformat()}, 'attendees': [{'email': email}]}, sendUpdates='all').execute()
        
        db_paciente = models.Paciente(cpf=cpf_limpo, nome_completo=nome, email=email, telefone=telefone, data_cadastro=datetime.date.today().isoformat())
        db.add(db_paciente)
        
        id_consulta = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{cpf_limpo}"
        db_consulta = models.Consulta(id_consulta=id_consulta, cpf_paciente=cpf_limpo, id_evento_google=evento_criado.get('id'), data_consulta=data_consulta, horario_consulta=horario_consulta)
        db.add(db_consulta)
        
        db.commit()
        return json.dumps({"status": "sucesso"})
    except Exception as e:
        db.rollback(); print(f"ERRO CRÍTICO ao cadastrar: {e}"); return json.dumps({"status": "erro"})

def agendar_consulta_retorno(db: Session, cpf: str, data_consulta: str, horario_consulta: str):
    if not GOOGLE_CALENDAR_SERVICE: return json.dumps({"status": "erro", "mensagem": "Serviço do Google não ativo."})
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- DB | Agendando retorno para CPF: {cpf_limpo} ---")
    try:
        paciente = db.query(models.Paciente).filter(models.Paciente.cpf == cpf_limpo).first()
        if not paciente: return json.dumps({"status": "erro", "mensagem": "Paciente não encontrado."})
        
        data_hora_inicio = datetime.datetime.strptime(f"{data_consulta} {horario_consulta}", '%Y-%m-%d %H:%M').astimezone(SAO_PAULO_TZ)
        evento_criado = GOOGLE_CALENDAR_SERVICE.events().insert(calendarId='primary', body={'summary': f'Consulta - {paciente.nome_completo} (Retorno)', 'description': f'Paciente: {paciente.nome_completo}\nCPF: {cpf_limpo}', 'start': {'dateTime': data_hora_inicio.isoformat()}, 'end': {'dateTime': (data_hora_inicio + datetime.timedelta(hours=DURACAO_CONSULTA)).isoformat()}, 'attendees': [{'email': paciente.email}]}, sendUpdates='all').execute()

        id_consulta = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{cpf_limpo}"
        db_consulta = models.Consulta(id_consulta=id_consulta, cpf_paciente=cpf_limpo, id_evento_google=evento_criado.get('id'), data_consulta=data_consulta, horario_consulta=horario_consulta)
        db.add(db_consulta)
        
        db.commit()
        return json.dumps({"status": "sucesso"})
    except Exception as e:
        db.rollback(); print(f"ERRO CRÍTICO ao agendar retorno: {e}"); return json.dumps({"status": "erro"})

def listar_consultas_agendadas(db: Session, cpf: str):
    cpf_limpo = _limpar_cpf(cpf)
    print(f"--- DB | Listando consultas para CPF: {cpf_limpo} ---")
    consultas = db.query(models.Consulta).filter(models.Consulta.cpf_paciente == cpf_limpo, models.Consulta.status == 'agendado', models.Consulta.data_consulta >= datetime.date.today().isoformat()).order_by(models.Consulta.data_consulta).all()
    if not consultas: return json.dumps({"info": "Nenhuma consulta futura agendada foi encontrada."})
    return json.dumps({"consultas": [{"id_consulta": c.id_consulta, "data_consulta": c.data_consulta, "horario_consulta": c.horario_consulta} for c in consultas]})

def cancelar_consulta(db: Session, id_consulta: str):
    if not GOOGLE_CALENDAR_SERVICE: return json.dumps({"status": "erro", "mensagem": "Serviço do Google não ativo."})
    print(f"--- DB | Cancelando consulta ID: {id_consulta} ---")
    try:
        consulta = db.query(models.Consulta).filter(models.Consulta.id_consulta == id_consulta).first()
        if not consulta: return json.dumps({"status": "erro", "mensagem": "ID da consulta não encontrado."})
        
        try: GOOGLE_CALENDAR_SERVICE.events().delete(calendarId='primary', eventId=consulta.id_evento_google, sendUpdates='all').execute()
        except HttpError as e:
            if e.resp.status != 410: raise e
        
        consulta.status = 'cancelado'
        db.commit()
        return json.dumps({"status": "sucesso"})
    except Exception as e:
        db.rollback(); print(f"ERRO CRÍTICO ao cancelar: {e}"); return json.dumps({"status": "erro"})