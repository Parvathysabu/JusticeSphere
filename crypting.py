from cryptography.fernet import Fernet

HARDCODED_KEY = b'cJPrQhaabUa9JLeu6ObhjVBiS2giptJHnOK7Ys71TIE='

class NoKeyEncryptor:
    def __init__(self):
        self.cipher = Fernet(HARDCODED_KEY)
    def encrypt(self, message: str) -> str:
        return self.cipher.encrypt(message.encode('utf-8')).decode('utf-8')
    def decrypt(self, encrypted: str) -> str:
        return self.cipher.decrypt(encrypted.encode('utf-8')).decode('utf-8')
