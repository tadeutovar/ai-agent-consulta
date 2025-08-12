# main.py

import os
import json
import datetime
from openai import OpenAI
from dotenv import load_dotenv
import models
import services
from database import engine, SessionLocal
from zoneinfo import ZoneInfo

# --- INICIALIZAÇÃO E AUTENTICAÇÃO ---
print("--- Iniciando o sistema e verificando autenticação do Google... ---")
services.inicializar_google_calendar()
print("--- Sistema pronto. ---")

models.Base.metadata.create_all(bind=engine)
load_dotenv()

# --- VERIFICAÇÃO ROBUSTA DA API KEY ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("A variável de ambiente OPENAI_API_KEY não foi definida. Verifique seu arquivo .env.")
client = OpenAI(api_key=OPENAI_API_KEY)

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")

def main():
    tools = [
        {"type": "function", "function": {"name": "verificar_paciente_existente", "description": "Verifica se um paciente já está cadastrado usando o CPF.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}}, "required": ["cpf"]}}},
        {"type": "function", "function": {"name": "buscar_horarios_disponiveis", "description": "Busca horários de consulta livres em uma data específica.", "parameters": {"type": "object", "properties": {"data": {"type": "string"}}, "required": ["data"]}}},
        {"type": "function", "function": {"name": "cadastrar_paciente_e_agendar", "description": "Cadastra um NOVO paciente e agenda sua primeira consulta.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}, "nome": {"type": "string"}, "email": {"type": "string"}, "telefone": {"type": "string"}, "data_consulta": {"type": "string"}, "horario_consulta": {"type": "string"}}, "required": ["cpf", "nome", "email", "telefone", "data_consulta", "horario_consulta"]}}},
        {"type": "function", "function": {"name": "agendar_consulta_retorno", "description": "Agenda uma nova consulta para um paciente EXISTENTE.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}, "data_consulta": {"type": "string"}, "horario_consulta": {"type": "string"}}, "required": ["cpf", "data_consulta", "horario_consulta"]}}},
        {"type": "function", "function": {"name": "listar_consultas_agendadas", "description": "Lista todas as consultas futuras e agendadas de um paciente pelo CPF.", "parameters": {"type": "object", "properties": {"cpf": {"type": "string"}}, "required": ["cpf"]}}},
        {"type": "function", "function": {"name": "cancelar_consulta", "description": "Cancela uma consulta específica pelo seu 'id_consulta' único.", "parameters": {"type": "object", "properties": {"id_consulta": {"type": "string"}}, "required": ["id_consulta"]}}}
    ]
    
    available_tools = { "verificar_paciente_existente": services.verificar_paciente_existente, "buscar_horarios_disponiveis": services.buscar_horarios_disponiveis, "cadastrar_paciente_e_agendar": services.cadastrar_paciente_e_agendar, "agendar_consulta_retorno": services.agendar_consulta_retorno, "listar_consultas_agendadas": services.listar_consultas_agendadas, "cancelar_consulta": services.cancelar_consulta }

    # --- SYSTEM PROMPT UNIFICADO E DINÂMICO ---
    # A data de hoje será inserida dinamicamente no prompt a cada chamada.
    base_system_prompt = """
        Você é a assistente virtual Sofia, do consultório do Dr. João. Sua personalidade é empática, profissional e RESOLUTIVA.
        O contexto da data de hoje é: {hoje}.

        **Regra de Ouro - Tratamento de Erros:** Se uma ferramenta retornar um JSON com a chave "error", sua resposta DEVE ser humana e direta: "Peço desculpas, parece que nosso sistema encontrou um problema ao buscar essa informação. Poderia, por favor, repetir sua solicitação para eu tentar novamente?".

        **FLUXO DE CONVERSA OBRIGATÓRIO:**
        1.  **SAUDAÇÃO:** Apresente-se como Sofia.
        2.  **IDENTIFICAR INTENÇÃO:** Aguarde o comando do usuário.
        3.  **AGENDAR (CPF PRIMEIRO):** Se o usuário quer agendar, sua primeira ação é pedir o CPF.
        4.  **NOVO PACIENTE:** Se o CPF não for encontrado, diga: "Entendi. Vejo que é sua primeira vez conosco, seja muito bem-vindo! Para criarmos seu cadastro, preciso apenas do seu nome completo, e-mail e telefone, por favor.". Após receber, peça consentimento LGPD. Só então pergunte a data desejada.
        5.  **PACIENTE RECORRENTE:** Se o CPF for encontrado, use o nome dele: "Olá, Sr. [Nome], que bom tê-lo de volta! Para qual dia gostaria de agendar?".
        """
    
    messages = [] # Começa vazio e o prompt de sistema é adicionado a cada loop.
    
    print("Assistente: Olá! Sou a Sofia, assistente virtual do Dr. João Silva. Como posso lhe ajudar hoje?")
    
    while True:
        entrada = input("Você: ")
        if not entrada: continue
        
        # --- GERENCIAMENTO DE SESSÃO CORRETO ---
        db_session = SessionLocal()
        try:
            hoje = datetime.datetime.now(SAO_PAULO_TZ).strftime('%Y-%m-%d')
            
            # Adiciona a entrada do usuário ao histórico da conversa
            messages.append({"role": "user", "content": entrada})
            
            # Monta a conversa para a chamada da API, com o prompt de sistema sempre atualizado
            conversa_atual = [{"role": "system", "content": base_system_prompt.format(hoje=hoje)}] + messages
            
            response = client.chat.completions.create(model="gpt-4o", messages=conversa_atual, tools=tools, tool_choice="auto")
            response_message = response.choices[0].message
            
            # Adiciona a resposta da IA ao histórico da conversa
            messages.append(response_message)
            
            if response_message.tool_calls:
                print("--- IA decidiu usar uma ferramenta ---")
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    if function_name not in available_tools:
                        print(f"Erro: Ferramenta desconhecida '{function_name}'")
                        continue
                    
                    function_to_call = available_tools[function_name]
                    function_args = json.loads(tool_call.function.arguments)
                    function_args['db'] = db_session
                    function_response = function_to_call(**function_args)
                    messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": function_response})

                # Monta a conversa novamente, agora com o resultado da ferramenta, para a resposta final
                conversa_final = [{"role": "system", "content": base_system_prompt.format(hoje=hoje)}] + messages
                final_response = client.chat.completions.create(model="gpt-4o", messages=conversa_final)
                final_message = final_response.choices[0].message.content
                print("Assistente:", final_message)
                messages.append({"role": "assistant", "content": final_message})
            else:
                final_message = response_message.content
                print("Assistente:", final_message)
        
        finally:
            db_session.close() # Garante que a sessão seja fechada após cada interação

if __name__ == "__main__":
    main()