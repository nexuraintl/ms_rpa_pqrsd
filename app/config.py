import os

class Settings:
    PROJECT_NAME: str = "PQRSD RPA Microservice"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Microservicio RPA para consulta y gestión de PQRSD en Portal Suite Neptuno (Floridablanca)"
    PORTAL_BASE_URL: str = os.getenv("PORTAL_BASE_URL", "https://portal.floridablanca.suiteneptuno.com/Correspondencia/Consulta/Consulta")
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))

settings = Settings()
