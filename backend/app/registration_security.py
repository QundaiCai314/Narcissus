"""Registration password guidance; existing login credentials remain compatible."""
import re
from .errors import fail

COMMON_STEMS = {
    'password', 'qwerty', 'asdfgh', 'zxcvbn', 'narcissus', 'admin',
    'administrator', 'letmein', 'welcome', 'iloveyou',
}


def password_problem(value):
    if not 10 <= len(value) <= 128:
        return '密码需为10至128位，建议使用15位以上的不重复短语'
    if len(set(value)) < 4 or re.fullmatch(r'(.{1,64})\1+', value, re.S):
        return '密码重复性过高，请使用不重复的较长短语'
    stem = re.sub('[^a-z]', '', value.lower())
    sequential = any(value.lower() in sequence * 14 for sequence in ('0123456789', '9876543210', 'abcdefghijklmnopqrstuvwxyz', 'zyxwvutsrqponmlkjihgfedcba'))
    if stem in COMMON_STEMS or sequential:
        return '这是容易猜到的常见密码，请换一个较长的密码或短语'
    return None


def validate_password(value):
    problem = password_problem(value)
    if problem:
        fail(422, 'weak_password', problem)
