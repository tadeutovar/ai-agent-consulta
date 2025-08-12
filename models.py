# models.py

from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class Paciente(Base):
    """
    Define a estrutura da tabela 'pacientes'.
    Cada linha representa um único paciente.
    """
    __tablename__ = "pacientes"
    
    cpf = Column(String, primary_key=True, index=True)
    nome_completo = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    telefone = Column(String)
    data_cadastro = Column(String)
    
    # Relacionamento para o histórico de consultas do paciente
    consultas = relationship("Consulta", back_populates="paciente")

class Consulta(Base):
    """
    Define a estrutura da tabela 'consultas'.
    Cada linha representa um único evento de consulta.
    """
    __tablename__ = "consultas"

    id_consulta = Column(String, primary_key=True, index=True)
    cpf_paciente = Column(String, ForeignKey("pacientes.cpf"))
    id_evento_google = Column(String, unique=True)
    data_consulta = Column(String)
    horario_consulta = Column(String)
    status = Column(String, default="agendado")
    observacoes = Column(String, nullable=True)
    
    # Relacionamento de volta para o objeto Paciente
    paciente = relationship("Paciente", back_populates="consultas")