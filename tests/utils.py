from datetime import datetime, timedelta, timezone
from unittest import mock

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def gerar_chaves():
    """(privada PEM, pública PEM) RS256 de teste."""
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_privada = privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pem_publica = privada.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return pem_privada, pem_publica


PRIVADA, PUBLICA = gerar_chaves()
OUTRA_PRIVADA, _ = gerar_chaves()


def access(chave=PRIVADA, **claims):
    """Access token com os claims que o AuthService emite hoje."""
    agora = datetime.now(timezone.utc)
    corpo = {
        "token_type": "access",
        "exp": agora + timedelta(minutes=60),
        "iat": agora,
        "jti": "teste",
        "user_id": "1",
        "username": "maria",
        "email": "maria@ifsuldeminas.edu.br",
        "is_superuser": False,
        "is_staff": False,
        "groups": [],
        **claims,
    }
    return jwt.encode(corpo, chave, algorithm="RS256")


def resposta(status=200, dados=None, sem_json=False):
    r = mock.Mock(status_code=status)
    if sem_json:
        r.json.side_effect = ValueError("não é JSON")
    else:
        r.json.return_value = dados if dados is not None else {}
    return r


def simular_post(*respostas):
    """Patch de requests.post devolvendo as respostas em ordem (ou levantando, se for exceção)."""
    return mock.patch("pci_auth.cliente.requests.post", side_effect=list(respostas))


ErroConexao = requests.ConnectionError("recusada")
