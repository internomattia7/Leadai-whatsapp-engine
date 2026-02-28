from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

pw = "Mattia123"
print(pwd_context.hash(pw))