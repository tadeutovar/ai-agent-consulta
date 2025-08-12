# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Define o caminho do nosso arquivo de banco de dados SQLite.
DATABASE_URL = "sqlite:///./consultorio.db"

# Cria o "motor" do SQLAlchemy, que gerencia a conexão.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# Cria uma fábrica de sessões.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Cria uma classe Base da qual nossos modelos de dados (tabelas) irão herdar.
Base = declarative_base()