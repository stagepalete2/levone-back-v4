import secrets


def generate_code():
    """Генерирует 5-значный код. Использует secrets для криптографической стойкости."""
    return str(secrets.randbelow(90000) + 10000)
