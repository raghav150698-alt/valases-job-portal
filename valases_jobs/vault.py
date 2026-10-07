"""Application encryption for stored resumes; uploads themselves are never retained."""
from cryptography.fernet import Fernet

class Vault:
    def __init__(self, settings):
        self.cipher = Fernet(settings.encryption_key.encode()) if settings.encryption_key else None
    def store(self, value):
        return 'enc:v1:'+self.cipher.encrypt(value.encode()).decode() if self.cipher else value
    def read(self, value):
        if not value.startswith('enc:v1:'): return value
        if not self.cipher: raise RuntimeError('Resume encryption key unavailable')
        return self.cipher.decrypt(value[7:].encode()).decode()
